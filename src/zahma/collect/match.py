"""إسقاط قياسات Mapbox على شبكتنا — الخطوة التي تجعل البيانات قابلة للاستخدام.

**المشكلة:** Mapbox يعيد مساراً كسلسلة إحداثيات مع مدة لكل حافة. شبكتنا
مبنية من OSM ولها `seg_id` مختلف تماماً. بلا إسقاط، لا نستطيع أن نقول
«هذا المقطع بطيء الآن» — نعرف فقط أن الرحلة الكاملة استغرقت 24 دقيقة.

**الحل:** لكل حافة في مسار Mapbox، نجد أقرب مقطع في شبكتنا ضمن 40 متراً،
وننسب إليها السرعة المقاسة (distance/duration من نفس الحافة).

**لماذا 40 متراً:** شبكتنا من OSM ومسار Mapbox من بياناتهم الخاصة. الفرق
الهندسي بينهما في المدينة المزدحمة قد يصل 20–30 متراً (طرق مزدوجة،
جسور). أقل من ذلك نُسقط قياسات صحيحة؛ أكثر من ذلك ننسب قياس شارع إلى
شارع آخر.

**لماذا نحتفظ بالسرعة لا بالمدة:** المدة تعتمد على طول المقطع، والطول
يختلف بين شبكتنا وشبكتهم. السرعة كم/ساعة كمية فيزيائية مستقلة عن
تمثيل الشارع.
"""

from __future__ import annotations

import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import text

from zahma.config import get_settings
from zahma.db import session_scope

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"

# أقصى مسافة بين حافة Mapbox ومقطعنا لنعتبرهما نفس الشارع.
MATCH_RADIUS_M = 40.0

# أقصر حافة نقبلها — تحت هذا الحد تصبح السرعة ضجيجاً حسابياً
# (حافة 3 أمتار بزمن 0.2 ثانية تعطي 54 كم/س بلا معنى).
MIN_EDGE_M = 8.0


@dataclass
class EdgeMeasurement:
    """حافة واحدة من مسار Mapbox بعد إسقاطها على مقطعنا."""

    seg_id: int
    speed_kmh: float
    dist_m: float
    travel_s: float
    offset_m: float  # مسافة الإسقاط — مقياس جودة المطابقة


@dataclass
class RouteMeasurement:
    pair_id: int
    duration_s: float
    duration_typical_s: float | None
    distance_m: float
    edges: list[EdgeMeasurement] = field(default_factory=list)
    matched: int = 0
    unmatched: int = 0


def _fetch_route(
    client: httpx.Client,
    token: str,
    origin: tuple[float, float],
    dest: tuple[float, float],
    depart_at: str | None = None,
) -> dict | None:
    """مسار واحد من Mapbox مع المدة لكل حافة.

    نطلب `steps=true` لأن كل خطوة تحمل `duration` و`duration_typical`
    منفصلين — وهذا هو مفتاح قياس الازدحام. مقيس فعلياً: `congestion`
    على مستوى المقطع يرجع `"unknown"` لكل مقاطع الجزائر، أما
    `duration/typical` على مستوى الخطوة فيتغيّر مع الساعة (0.96 إلى 3.02).
    """
    coords = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
    params: dict = {
        "access_token": token,
        "overview": "full",
        "geometries": "geojson",
        "steps": "true",
        "annotations": "duration,distance,speed",
    }
    if depart_at:
        params["depart_at"] = depart_at

    r = client.get(f"{BASE}/{coords}", params=params)
    if r.status_code >= 400:
        return None
    routes = r.json().get("routes") or []
    return routes[0] if routes else None


def _match_edges(
    points: list[tuple[float, float, float]],
) -> dict[int, tuple[int, float]]:
    """يسقط نقاطاً على الشبكة. يُرجع {index: (seg_id, offset_m)}.

    نقطة واحدة لكل حافة (منتصفها). استعلام واحد لكل دفعة، مع GIST index
    على `segments.geom` — لا استعلام لكل نقطة (328 استعلاماً للمسار الواحد
    يجعل الجمع أبطأ 20×).
    """
    if not points:
        return {}

    idxs = [p[0] for p in points]
    lons = [p[1] for p in points]
    lats = [p[2] for p in points]

    # **الفرق بين نجاح وفشل**: `geom::geography` يُلغي فهرس GIST لأن
    # التحويل يغيّر النوع فيمنع الاستعلام من استخدام `segments_geom_idx`.
    # النتيجة المقاسة: 3 أزواج استغرقت أكثر من 15 دقيقة بلا نهاية.
    #
    # الحل: نُرشّح أولاً بمسافة بالدرجات على الهندسة نفسها (يستخدم
    # الفهرس)، ثم نحسب المسافة الدقيقة بالمتر على المرشّحين فقط.
    # 0.0005 درجة ≈ 55 متراً خط عرض، و≈ 45 متراً خط طول عند دائرة
    # عرض 36.7 — أي أوسع قليلاً من عتبتنا، وهذا مقصود حتى لا نُسقط
    # مقطعاً صحيحاً على حافة النطاق.
    DEG = 0.0005

    sql = text(
        """
        WITH pts AS (
            SELECT * FROM unnest(
                CAST(:idx AS int[]),
                CAST(:lon AS double precision[]),
                CAST(:lat AS double precision[])
            ) AS t(idx, lon, lat)
        ),
        ptg AS (
            SELECT idx, lon, lat,
                   ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
            FROM pts
        )
        SELECT p.idx, m.seg_id, m.d
        FROM ptg p
        CROSS JOIN LATERAL (
            SELECT s.seg_id,
                   ST_Distance(
                       s.geom::geography,
                       p.g::geography
                   ) AS d
            FROM segments s
            WHERE s.geom && ST_Expand(p.g, :deg)
              AND ST_DWithin(s.geom, p.g, :deg)
            ORDER BY s.geom <-> p.g
            LIMIT 1
        ) m
        WHERE m.d <= :radius
        """
    )

    out: dict[int, tuple[int, float]] = {}
    with session_scope() as s:
        rows = s.execute(
            sql,
            {
                "idx": idxs,
                "lon": lons,
                "lat": lats,
                "deg": DEG,
                "radius": MATCH_RADIUS_M,
            },
        ).all()
    for i, seg_id, d in rows:
        out[int(i)] = (int(seg_id), float(d))
    return out


def measure_pair(
    client: httpx.Client,
    token: str,
    pair: dict,
    depart_at: str | None = None,
) -> RouteMeasurement | None:
    """يقيس زوجاً واحداً ويسقط حافاته على شبكتنا.

    **لماذا `annotation` لا `steps`:**

    قياس فعلي على مسار باب الزوار ← الوسط: `steps` = 15 خطوة فقط،
    لكن `annotation` = 328 مدخلاً — واحد لكل زوج إحداثيات متتالٍ.
    الخطوة هي «شارع باسم واحد» وقد تمتد 7.6 كم (Rocade Nord)، فإسقاط
    خطوة واحدة على مقطع واحد يخسر 95% من الطريق.

    `annotation` يعطي `distance` و`duration` و`speed` لكل زوج إحداثيات،
    أي دقة ~48 متراً على هذا المسار. ومجموعها يساوي مدة المسار بالضبط
    (تحققنا: 1133.1 = 1133.1).
    """
    route = _fetch_route(
        client, token, pair["from"], pair["to"], depart_at=depart_at
    )
    if route is None:
        return None

    coords = (route.get("geometry") or {}).get("coordinates") or []
    legs = route.get("legs") or []
    if not coords or not legs:
        return None

    # الحافة i تقع بين coords[i] و coords[i+1]، ولكل خطوة مصفوفة
    # annotation خاصة بها — نصلها بالترتيب.
    edges: list[tuple[float, float, float | None]] = []
    for leg in legs:
        ann = leg.get("annotation") or {}
        durs = ann.get("duration") or []
        dists = ann.get("distance") or []
        spds = ann.get("speed") or []
        n = min(len(durs), len(dists))
        for i in range(n):
            spd = spds[i] if i < len(spds) else None
            edges.append((float(dists[i]), float(durs[i]), spd))

    if not edges:
        return None

    # منتصف كل حافة — نقطة واحدة للإسقاط.
    pts: list[tuple[float, float, float]] = []
    for i in range(min(len(coords) - 1, len(edges))):
        lon1, lat1 = coords[i][0], coords[i][1]
        lon2, lat2 = coords[i + 1][0], coords[i + 1][1]
        pts.append((i, (lon1 + lon2) / 2, (lat1 + lat2) / 2))

    matches = _match_edges(pts)

    # مقطع قد يُقاس أكثر من مرة في نفس المسار (شوارع مزدوجة، دورات).
    # نأخذ الوسيط لا المتوسط: قياس شاذ واحد يحرف المتوسط.
    per_seg: dict[int, list[float]] = defaultdict(list)
    matched = 0
    unmatched = 0

    for i, (seg_id, _offset) in matches.items():
        if i >= len(edges):
            continue
        dist_m, travel_s, _spd = edges[i]
        if dist_m < MIN_EDGE_M or travel_s <= 0:
            unmatched += 1
            continue
        # السرعة الفيزيائية: متر/ثانية × 3.6
        speed_kmh = (dist_m / travel_s) * 3.6
        # سرعة غير معقولة = خطأ في البيانات لا قياس حقيقي.
        if not (1.0 <= speed_kmh <= 160.0):
            unmatched += 1
            continue
        per_seg[seg_id].append(speed_kmh)
        matched += 1

    out_edges: list[EdgeMeasurement] = []
    for seg_id, speeds in per_seg.items():
        speeds.sort()
        med = speeds[len(speeds) // 2]
        out_edges.append(
            EdgeMeasurement(
                seg_id=seg_id,
                speed_kmh=round(med, 2),
                dist_m=0.0,
                travel_s=0.0,
                offset_m=0.0,
            )
        )

    dur = float(route.get("duration") or 0.0)
    dur_typ = route.get("duration_typical")
    return RouteMeasurement(
        pair_id=int(pair["pair_id"]),
        duration_s=dur,
        duration_typical_s=float(dur_typ) if dur_typ else None,
        distance_m=float(route.get("distance") or 0.0),
        edges=out_edges,
        matched=matched,
        unmatched=unmatched,
    )


def _bucket(dt: datetime, minutes: int = 5) -> datetime:
    return dt.replace(
        minute=(dt.minute // minutes) * minutes, second=0, microsecond=0
    )


def _parse_depart(depart_at: str | None) -> datetime | None:
    """يفهم `depart_at` الذي أرسلناه إلى Mapbox.

    Mapbox يقبل `YYYY-MM-DDThh:mm` ويعامله كوقت **محلي لموقع الانطلاق**،
    أي توقيت الجزائر (UTC+1). نُعيده هنا بتوقيت UTC صحيحاً.
    """
    if not depart_at:
        return None
    from zoneinfo import ZoneInfo

    algiers = ZoneInfo("Africa/Algiers")
    naive = datetime.fromisoformat(depart_at)
    return naive.replace(tzinfo=algiers).astimezone(UTC)


def store(
    measurements: list[RouteMeasurement],
    ts: datetime,
    source: str = "mapbox",
    forecast: bool = False,
) -> dict:
    """يخزّن القياسات في `samples` و`route_samples` — idempotent وحتمي.

    `forecast=True` يعني أن البيانات تنبؤ المزوّد لوقت مستقبلي (أرسلنا
    `depart_at`) لا قياساً آنياً. نفرّق بينهما في `raw_ref` حتى نعرف —
    عند تقييم دقة نموذجنا — أي صفوف كانت «الحقيقة» وأيها كانت تنبؤاً.

    **العيب الذي أصلحه التجميع هنا:** كان الكود يُدرج صفاً لكل حافة،
    والمفتاح `(segment_id, source, ts_bucket)` يقبل صفاً واحداً. فيحدث
    `ON CONFLICT DO UPDATE` — أي **آخر كاتب يفوز**. والكتابة تجري عبر
    `ThreadPoolExecutor`، فالفائز يعتمد على ترتيب إنهاء الطلبات، لا على
    الطريق.

    المقاس: 17.2 زوجاً في الشريحة تعطي ~6,800 حافة، لكن المخزَّن 4,350
    صفاً — أي أن **~36% من القياسات تُمحى بلا أثر**. وأثبتنا ذلك مباشرة:
    مقطع بقيمة 20 ثم 80 كم/س يبقى صف واحد بـ80، و20 ضاعت بلا سجل.

    **الإصلاح:** نجمع كل قياسات المقطع في الشريحة أولاً (وسيط موزون
    بمسافة الحافة، لأن حافة 5 م لا تساوي حافة 300 م)، ثم نكتب صفاً واحداً
    حتمياً. الترتيب لم يبق له أثر: الوسيط لا يعتمد على ترتيب الإدخال.

    `raw_ref` يحمل عدد الأزواج المساهمة — بلا ذلك لا يمكن معرفة أن الصف
    نتيجة تجميع لا قياس واحد.
    """
    bucket = _bucket(ts)
    tag = "forecast" if forecast else "live"

    # تجميع حتمي: (segment_id) ⇒ [(speed, dist, pair_id)]
    per_seg: dict[int, list[tuple[float, float, int]]] = {}
    for m in measurements:
        for e in m.edges:
            per_seg.setdefault(e.seg_id, []).append((e.speed_kmh, e.dist_m, m.pair_id))

    seg_rows = []
    for seg_id, obs in per_seg.items():
        obs.sort(key=lambda o: (o[0], o[2]))  # ترتيب ثابت: لا يعتمد على الخيوط
        total_w = sum(o[1] for o in obs) or 1.0
        # الوسيط الموزون بالمسافة: نصف المسافة الكلية.
        acc = 0.0
        chosen = obs[-1][0]
        for speed, dist, _ in obs:
            acc += dist
            if acc >= total_w / 2:
                chosen = speed
                break
        pairs = len({o[2] for o in obs})
        seg_rows.append(
            {
                "segment_id": seg_id,
                "source": source,
                "ts_utc": ts,
                "ts_bucket": bucket,
                "speed_kmh": round(chosen, 2),
                "travel_time_s": None,
                "confidence": 0.85,
                "raw_ref": f"pairs={pairs};{tag};mapbox_steps",
            }
        )

    route_rows = []
    for m in measurements:
        delay = (
            m.duration_s / m.duration_typical_s
            if m.duration_typical_s
            else None
        )
        route_rows.append(
            {
                "pair_id": m.pair_id,
                "source": source,
                "ts_utc": ts,
                "ts_bucket": bucket,
                "duration_s": m.duration_s,
                "duration_free_s": m.duration_typical_s,
                "distance_m": m.distance_m,
                "delay_ratio": delay,
                "confidence": 0.85,
            }
        )

    # تفصيل لكل زوج: كان `ON CONFLICT` يمحو هذا التفصيل بلا أثر.
    detail_rows = []
    for m in measurements:
        for e in m.edges:
            detail_rows.append(
                {
                    "segment_id": e.seg_id,
                    "pair_id": m.pair_id,
                    "source": source,
                    "ts_utc": ts,
                    "ts_bucket": bucket,
                    "speed_kmh": e.speed_kmh,
                    "dist_m": e.dist_m,
                    "offset_m": e.offset_m,
                }
            )

    ins_detail = text(
        """
        INSERT INTO segment_pair_samples
            (segment_id, pair_id, source, ts_utc, ts_bucket,
             speed_kmh, dist_m, offset_m)
        VALUES
            (:segment_id, :pair_id, CAST(:source AS source_kind), :ts_utc,
             :ts_bucket, :speed_kmh, :dist_m, :offset_m)
        ON CONFLICT (segment_id, pair_id, source, ts_bucket) DO UPDATE
        SET speed_kmh = EXCLUDED.speed_kmh,
            dist_m = EXCLUDED.dist_m,
            offset_m = EXCLUDED.offset_m
        """
    )

    ins_seg = text(
        """
        INSERT INTO samples
            (segment_id, source, ts_utc, ts_bucket, speed_kmh,
             travel_time_s, confidence, raw_ref)
        VALUES
            (:segment_id, CAST(:source AS source_kind), :ts_utc, :ts_bucket,
             :speed_kmh, :travel_time_s, :confidence, :raw_ref)
        ON CONFLICT (segment_id, source, ts_bucket) DO UPDATE
        SET speed_kmh = EXCLUDED.speed_kmh,
            confidence = EXCLUDED.confidence,
            raw_ref = EXCLUDED.raw_ref
        """
    )
    ins_route = text(
        """
        INSERT INTO route_samples
            (pair_id, source, ts_utc, ts_bucket, duration_s,
             duration_free_s, distance_m, delay_ratio, confidence)
        VALUES
            (:pair_id, CAST(:source AS source_kind), :ts_utc, :ts_bucket,
             :duration_s, :duration_free_s, :distance_m, :delay_ratio,
             :confidence)
        ON CONFLICT (pair_id, source, ts_bucket) DO UPDATE
        SET duration_s = EXCLUDED.duration_s,
            duration_free_s = EXCLUDED.duration_free_s,
            delay_ratio = EXCLUDED.delay_ratio,
            confidence = EXCLUDED.confidence
        """
    )

    with session_scope() as s:
        if detail_rows:
            s.execute(ins_detail, detail_rows)
        if seg_rows:
            s.execute(ins_seg, seg_rows)
        if route_rows:
            s.execute(ins_route, route_rows)

    return {
        "segments": len(seg_rows),
        "routes": len(route_rows),
        "detail_rows": len(detail_rows),
        "bucket": bucket.isoformat(),
    }


def collect(
    limit_pairs: int = 20,
    depart_at: str | None = None,
    dry_run: bool = False,
    workers: int = 4,
) -> dict:
    """يجمع قياسات حقيقية من Mapbox ويسقطها على الشبكة.

    `limit_pairs` مقصود: كل زوج = طلب واحد من حصة Mapbox الشهرية
    (100 ألف). 20 زوجاً كل نصف ساعة في ساعات الذروة = ~2,900 شهرياً،
    أي 3% من الحصة.

    `workers`: طلبات متوازية. حد Mapbox هو 300 طلب/دقيقة؛ 4 عمال
    ينتجون ~240/دقيقة بأمان. القياس التسلسلي كان 14.6 ثانية لـ20 زوجاً،
    أي أن جمع أسبوع كامل يستغرق 28 دقيقة — أطول من أن يكون عملياً.
    """
    s = get_settings()
    if not s.has_mapbox:
        return {"ok": False, "error": "MAPBOX_TOKEN missing"}

    with session_scope() as sess:
        rows = sess.execute(
            text(
                """
                SELECT pair_id,
                       ST_Y(ST_StartPoint(from_pt::geometry)) AS from_lat,
                       ST_X(ST_StartPoint(from_pt::geometry)) AS from_lon,
                       ST_Y(ST_StartPoint(to_pt::geometry)) AS to_lat,
                       ST_X(ST_StartPoint(to_pt::geometry)) AS to_lon
                FROM od_pairs
                WHERE active
                ORDER BY weight DESC
                LIMIT :n
                """
            ),
            {"n": limit_pairs},
        ).mappings().all()

    pairs = [
        {
            "pair_id": r["pair_id"],
            "from": (r["from_lat"], r["from_lon"]),
            "to": (r["to_lat"], r["to_lon"]),
        }
        for r in rows
    ]

    ts = _parse_depart(depart_at) or datetime.now(UTC)
    measurements: list[RouteMeasurement] = []
    failed = 0

    def one(client: httpx.Client, p: dict) -> RouteMeasurement | None:
        try:
            return measure_pair(client, s.mapbox_token, p, depart_at=depart_at)
        except Exception:  # noqa: BLE001
            return None

    # عميل واحد لكل عامل: httpx.Client ليس آمناً للمشاركة بين الخيوط.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for p in pairs:
            client = httpx.Client(timeout=25.0)
            futures.append(pool.submit(one, client, p))
        for f in futures:
            m = f.result()
            if m is None:
                failed += 1
            else:
                measurements.append(m)

    total_matched = sum(m.matched for m in measurements)
    total_unmatched = sum(m.unmatched for m in measurements)
    total_edges = sum(len(m.edges) for m in measurements)

    result = {
        "ok": len(measurements) > 0,
        "pairs": len(pairs),
        "failed": failed,
        "edges_matched": total_matched,
        "edges_unmatched": total_unmatched,
        "segments_measured": total_edges,
        "match_rate_pct": (
            round(total_matched / (total_matched + total_unmatched) * 100, 1)
            if (total_matched + total_unmatched)
            else 0.0
        ),
    }

    if dry_run:
        result["dry_run"] = True
        return result

    result.update(store(measurements, ts, forecast=bool(depart_at)))
    return result
