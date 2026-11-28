"""محرك التوجيه — Dijkstra بلغة C على مصفوفة متفرقة.

## لماذا أُعيدت كتابة هذا الملف

النسخة الأولى استخدمت `networkx`. القياس الفعلي على شبكة العاصمة
(294 ألف مقطع، 272 ألف عقدة):

| العملية | networkx | المطلوب |
|---|---|---|
| بناء الرسم | 94 ثانية | ثوانٍ |
| البحث عن أقرب عقدة | 45 ثانية | مللي ثانية |
| توجيه واحد | 52 ثانية | < 200 مللي ثانية |

توجيه واحد في 52 ثانية يعني أن أي خادم يخدم 10 مستخدمين يحتاج 10 أنوية
فقط للتوجيه. هذا ليس مقبولاً. البديل: `scipy.sparse.csgraph.dijkstra`
مكتوب بلغة C — نفس الخوارزمية بسرعة أعلى بثلاث مراتب.

## القرارات

1. **المصفوفة تُبنى مرة وتُخزَّن على القرص** (`.npz`). بناؤها من قاعدة
   البيانات في كل عملية يهدر ثواني بلا فائدة.
2. **السرعات المتغيرة لا تُعيد بناء المصفوفة**: نبني مصفوفة الأوزان من
   مصفوفة الأطوال والسرعات بـnumpy متجهياً (أجزاء من الثانية).
3. **العقد مرقّمة 0..N-1** بدل معرّفات OSM الكبيرة — شرط لـscipy.
4. **الحافة المعاكسة** تُضاف للطرق ذات الاتجاهين: pyrosm يُخرج كل طريق
   مرة واحدة، فبلا هذا يكون الرسم أحادياً ويستحيل الرجوع من الوجهة.
5. **اللصق على أكبر مكوّن قوي**: أقرب عقدة جغرافياً كثيراً ما تكون نهاية
   طريق مسدود. نلصق فقط على عقد يمكن الوصول بينها في الاتجاهين.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as cs_dijkstra
from sqlalchemy import text

from zahma.config import DATA_PROCESSED
from zahma.db import session_scope

CACHE_DIR = DATA_PROCESSED / "router_cache"
MATRIX_CACHE = CACHE_DIR / "matrix.npz"
ROUTABLE_CACHE = CACHE_DIR / "routable.json"

# حجم خلية الشبكة المكانية بالدرجات (~250 متر عند خط عرض 36°)
GRID_DEG = 0.0025
# أقصى عدد عقد بداية نجرّبها
MAX_SOURCES = 6


@dataclass(slots=True)
class PathResult:
    seg_ids: list[int]
    length_m: float
    nodes: list[int] = field(default_factory=list)
    found: bool = False
    duration_s: float = 0.0
    # **لماذا هذا الحقل ضروري:** `_nearest` يعيد أقرب عقدة بلا حدّ مسافة.
    # نقطة على 3 كم خارج الشبكة كانت تُسحَب إليها وتُعطي مساراً يبدو
    # صحيحاً — خطأ صامت أخطر من «لا أعرف». نسجّل المسافة لنرفض ما يبعد
    # أكثر من SNAP_MAX_KM، وليعرف المستدعي *كم* هو خارج التغطية.
    snap_from_km: float = 0.0
    snap_to_km: float = 0.0


# أقصى مسافة إسقاط نقبلها. القياس: داخل الجزائر الوسطى الإسقاط < 0.5 كم.
# بومرداس 11.3 كم — خارج التغطية قطعاً. 2 كم هامش سخي يغطي ضواحي
# الولاية دون أن يبتلع مدناً أخرى.
SNAP_MAX_KM = 2.0


# ============================================================
# بناء المصفوفة وتخزينها
# ============================================================

def _load_raw() -> dict:
    """يقرأ المقاطع والسرعات الحرة داخل المكوّن الرئيسي."""
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT seg_id, u, v, length_m, speed_free_kmh,
                       COALESCE(oneway,'no') AS oneway
                FROM segments
                WHERE u IS NOT NULL AND v IS NOT NULL AND in_main
                ORDER BY seg_id
                """
            )
        ).mappings().all()
    return {
        "seg_id": np.array([int(r["seg_id"]) for r in rows], dtype=np.int64),
        "u": np.array([int(r["u"]) for r in rows], dtype=np.int64),
        "v": np.array([int(r["v"]) for r in rows], dtype=np.int64),
        "length": np.array([float(r["length_m"]) for r in rows], dtype=np.float64),
        "speed": np.array(
            [max(3.0, float(r["speed_free_kmh"])) for r in rows], dtype=np.float64
        ),
        "oneway": np.array(
            [str(r["oneway"]).strip().lower() for r in rows], dtype=object
        ),
    }


def build_matrix(force: bool = False) -> dict:
    """يبني مصفوفة الرسم ويخزّنها. يعيد كل ما يحتاجه التوجيه.

    البنية: كل عقدة OSM تأخذ رقماً متسلسلاً 0..N-1. الحواف تُخزَّن
    في مصفوفة CSR موزونة بالزمن (ثوانٍ).
    """
    if MATRIX_CACHE.exists() and not force:
        return _load_matrix()

    raw = _load_raw()
    if len(raw["seg_id"]) == 0:
        raise RuntimeError("no segments — run load-network first")

    # ترقيم العقد
    node_ids = np.unique(np.concatenate([raw["u"], raw["v"]]))
    node_index = {int(n): i for i, n in enumerate(node_ids)}
    n_nodes = len(node_ids)

    u_idx = np.array([node_index[int(x)] for x in raw["u"]], dtype=np.int32)
    v_idx = np.array([node_index[int(x)] for x in raw["v"]], dtype=np.int32)

    # الحواف: الاتجاه الطبيعي دائماً، والمعاكس إن لم يكن الطريق أحادي الاتجاه
    oneway = raw["oneway"]
    is_reverse_only = np.isin(oneway, ["-1", "reverse"])
    is_two_way = ~np.isin(oneway, ["yes", "-1", "reverse"])

    src_parts = [u_idx]
    dst_parts = [v_idx]
    seg_parts = [raw["seg_id"]]
    len_parts = [raw["length"]]
    spd_parts = [raw["speed"]]

    if is_reverse_only.any():
        # اتجاه واحد لكن معاكس: v → u
        src_parts.append(v_idx[is_reverse_only])
        dst_parts.append(u_idx[is_reverse_only])
        seg_parts.append(raw["seg_id"][is_reverse_only])
        len_parts.append(raw["length"][is_reverse_only])
        spd_parts.append(raw["speed"][is_reverse_only])

    if is_two_way.any():
        src_parts.append(v_idx[is_two_way])
        dst_parts.append(u_idx[is_two_way])
        seg_parts.append(raw["seg_id"][is_two_way])
        len_parts.append(raw["length"][is_two_way])
        spd_parts.append(raw["speed"][is_two_way])

    src = np.concatenate(src_parts).astype(np.int32)
    dst = np.concatenate(dst_parts).astype(np.int32)
    seg = np.concatenate(seg_parts).astype(np.int64)
    length = np.concatenate(len_parts).astype(np.float64)
    speed = np.concatenate(spd_parts).astype(np.float64)

    # إزالة الاتجاهات المعاكسة فقط (لا يمكن أن يكون الطريق في الاتجاهين
    # بنفس المصدر والهدف بعد التوسيع، لكن نحمي أنفسنا)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        MATRIX_CACHE,
        node_ids=node_ids,
        src=src,
        dst=dst,
        seg_id=seg,
        length=length,
        speed=speed,
        n_nodes=np.array([n_nodes], dtype=np.int64),
    )

    _load_matrix.cache_clear()
    _routable_mask.cache_clear()
    _grid.cache_clear()
    return _load_matrix()


@lru_cache(maxsize=1)
def _load_matrix() -> dict:
    if not MATRIX_CACHE.exists():
        raise RuntimeError("router matrix missing — run build_matrix() first")
    z = np.load(MATRIX_CACHE, allow_pickle=False)
    return {
        "node_ids": z["node_ids"],
        "src": z["src"],
        "dst": z["dst"],
        "seg_id": z["seg_id"],
        "length": z["length"],
        "speed": z["speed"],
        "n_nodes": int(z["n_nodes"][0]),
    }


@lru_cache(maxsize=1)
def _node_pos() -> dict[int, int]:
    """معرّف OSM → رقم العقدة في المصفوفة."""
    m = _load_matrix()
    return {int(n): i for i, n in enumerate(m["node_ids"])}


@lru_cache(maxsize=1)
def _coords() -> np.ndarray:
    """إحداثيات العقد بترتيب أرقام المصفوفة — مصفوفة (N, 2)."""
    import pandas as pd

    m = _load_matrix()
    df = pd.read_parquet(DATA_PROCESSED / "osm_nodes.parquet", columns=["id", "lon", "lat"])
    lut = {int(i): (float(lo), float(la)) for i, lo, la in zip(df["id"], df["lon"], df["lat"], strict=False)}

    out = np.full((m["n_nodes"], 2), np.nan, dtype=np.float64)
    for osm_id, idx in _node_pos().items():
        c = lut.get(osm_id)
        if c is not None:
            out[idx, 0] = c[0]
            out[idx, 1] = c[1]
    return out


# ============================================================
# المكوّن القوي الأكبر (عقد التوجيه)
# ============================================================

def _compute_routable() -> np.ndarray:
    """أكبر مكوّن قوي — يُحسب مرة ويُخزَّن.

    نستخدم Kosaraju عبر scipy بدل networkx: حساب SCC على 272 ألف عقدة
    في networkx يكلّف ثواني طويلة، وفي scipy أجزاء من الثانية.
    """
    from scipy.sparse.csgraph import connected_components

    m = _load_matrix()
    graph = csr_matrix(
        (np.ones(len(m["src"]), dtype=np.float64), (m["src"], m["dst"])),
        shape=(m["n_nodes"], m["n_nodes"]),
    )
    # strongly_connected_components على الرسم كما هو
    n_comp, labels = connected_components(graph, directed=True, connection="strong")
    counts = np.bincount(labels)
    main = int(np.argmax(counts))
    return labels == main


@lru_cache(maxsize=1)
def _routable_mask() -> np.ndarray:
    if ROUTABLE_CACHE.exists():
        try:
            data = json.loads(ROUTABLE_CACHE.read_text(encoding="utf-8"))
            idx = np.array(data["indices"], dtype=np.int64)
            mask = np.zeros(_load_matrix()["n_nodes"], dtype=bool)
            mask[idx] = True
            return mask
        except Exception:  # noqa: BLE001
            pass

    mask = _compute_routable()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ROUTABLE_CACHE.write_text(
        json.dumps(
            {
                "computed_at": datetime.now(UTC).isoformat(),
                "indices": np.flatnonzero(mask).tolist(),
            }
        ),
        encoding="utf-8",
    )
    return mask


@lru_cache(maxsize=1)
def _grid() -> dict[tuple[int, int], np.ndarray]:
    """شبكة مكانية: خلية → أرقام العقد القابلة للتوجيه فيها.

    بلا هذه الشبكة، البحث عن أقرب عقدة يمسح 272 ألف عقدة لكل نقطة.
    """
    coords = _coords()
    mask = _routable_mask()

    ok = np.flatnonzero(mask & ~np.isnan(coords[:, 0]))
    gx = np.floor(coords[ok, 0] / GRID_DEG).astype(np.int32)
    gy = np.floor(coords[ok, 1] / GRID_DEG).astype(np.int32)

    grid: dict[tuple[int, int], list[int]] = {}
    for x, y, idx in zip(gx, gy, ok, strict=False):
        grid.setdefault((int(x), int(y)), []).append(int(idx))
    return {k: np.array(v, dtype=np.int64) for k, v in grid.items()}


def _nearest(lon: float, lat: float, k: int = MAX_SOURCES) -> list[int]:
    """أقرب عقد قابلة للتوجيه، بتوسيع حلقي حول الخلية.

    نجرّب عدة عقد لأن الأقرب قد يكون على حافة المكوّن. التوسيع الحلقي
    يضمن أننا نجد مرشحين حتى لو كانت الخلية فارغة.
    """
    return [i for _, i in _nearest_with_distance(lon, lat, k)]


def _nearest_with_distance(
    lon: float, lat: float, k: int = MAX_SOURCES
) -> list[tuple[float, int]]:
    """أقرب العقد **بمسافتها** بالأمتار — أساس رفض ما هو خارج التغطية.

    `_nearest` وحدها كانت تعيد أقرب عقدة بلا أي حدّ. النتيجة المقاسة:
    نقطة في بومرداس (11.3 كم خارج الشبكة) تُسحَب إلى حافة الشبكة وتُعطي
    مساراً يبدو معقولاً — أي **رقم خاطئ بصمت**. وهذا أسوأ من «لا أعرف»:
    المستخدم يبني قرار سفر على مسار لم يقصده.
    """
    grid = _grid()
    coords = _coords()
    gx = int(math.floor(lon / GRID_DEG))
    gy = int(math.floor(lat / GRID_DEG))

    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(36.75))

    found: list[tuple[float, int]] = []
    for ring in range(0, 10):
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                if ring > 0 and abs(dx) != ring and abs(dy) != ring:
                    continue
                arr = grid.get((gx + dx, gy + dy))
                if arr is None:
                    continue
                for idx in arr:
                    ddx = (coords[idx, 0] - lon) * lon_scale
                    ddy = (coords[idx, 1] - lat) * lat_scale
                    found.append((ddx * ddx + ddy * ddy, int(idx)))
        if len(found) >= k * 4:
            break

    found.sort(key=lambda x: x[0])
    return [(math.sqrt(d2), i) for d2, i in found[:k]]


# ============================================================
# التوجيه
# ============================================================

@lru_cache(maxsize=1)
def _seg_row() -> tuple[np.ndarray, np.ndarray]:
    """فهرس: seg_id → رقم الصف في مصفوفة الحواف.

    لماذا هذا موجود: التخصيص `spd[seg == sid] = v` لكل مقطع يعني
    293 ألف مسحاً كاملاً على 512 ألف حافة = 150 مليار مقارنة.
    القياس: 295 ثانية. بفهرس واحد: أجزاء من الثانية.

    `seg_unique` مرتّب تصاعدياً، فنستخدم `searchsorted` للبحث الثنائي.
    """
    m = _load_matrix()
    seg_unique, inverse = np.unique(m["seg_id"], return_inverse=True)
    return seg_unique, inverse


def _weights(speeds: dict[int, float] | None) -> np.ndarray:
    """وزن كل حافة بالثواني — متجهياً.

    `speeds` مفتاحه seg_id. نستخدم بحثاً ثنائياً على معرّفات المقاطع
    المرتّبة، لا مسحاً خطياً.
    """
    m = _load_matrix()
    if not speeds:
        spd = m["speed"]
        return m["length"] / (spd / 3.6)

    seg_unique, inverse = _seg_row()
    keys = np.fromiter(speeds.keys(), dtype=np.int64, count=len(speeds))
    vals = np.fromiter(speeds.values(), dtype=np.float64, count=len(speeds))

    # بحث ثنائي: موقع كل مقطع في القائمة المرتّبة
    pos = np.searchsorted(seg_unique, keys)
    pos = np.clip(pos, 0, len(seg_unique) - 1)
    hit = seg_unique[pos] == keys

    # سرعة لكل مقطع (الافتراضية = السرعة الحرة)
    speed_by_seg = m["speed"][inverse]  # سرعة كل حافة حسب مقطعها
    if hit.any():
        # خريطة seg_id → السرعة المخصصة
        custom = np.full(len(seg_unique), np.nan, dtype=np.float64)
        custom[pos[hit]] = vals[hit]
        assigned = custom[inverse]
        speed_by_seg = np.where(np.isnan(assigned), speed_by_seg, assigned)

    spd = np.maximum(3.0, speed_by_seg)
    return m["length"] / (spd / 3.6)


def _csr(w: np.ndarray) -> csr_matrix:
    m = _load_matrix()
    return csr_matrix(
        (w, (m["src"], m["dst"])),
        shape=(m["n_nodes"], m["n_nodes"]),
    )


def route(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    speeds: dict[int, float] | None = None,
) -> PathResult:
    """يحسب مساراً بين نقطتين ويعيد مقاطعه.

    Dijkstra واحد لكل عقدة بداية (حتى 6)، وكل واحدة تعطي مسافات لكل
    العقد — فنأخذ أفضل عقدة وصول. توقف مبكر بعد أول نجاح لأن عقد
    البداية متقاربة داخل 3 كم والفرق في الطول مهمل.
    """
    m = _load_matrix()
    src_pairs = _nearest_with_distance(from_lon, from_lat)
    dst_pairs = _nearest_with_distance(to_lon, to_lat)

    # **قائمة فارغة تعني «لا شيء قريب» — لا «المسافة صفر».**
    #
    # العيب: حين لا يجد البحث الحلقي أي عقدة، يعيد `[]`، فتبقى المسافة
    # صفراً ويقول التشخيص «داخل التغطية لكن لا مسار» — وهو كذب. النقطة
    # على 11 كم لم يُعثر لها على عقدة لأنها خارج مدى الحلقات أصلاً.
    # لذلك نُسجّل مسافة لا نهائية دلالياً (999) ليدخل فرع «خارج التغطية».
    if not src_pairs or not dst_pairs:
        return PathResult(
            seg_ids=[],
            length_m=0.0,
            found=False,
            snap_from_km=src_pairs[0][0] / 1000.0 if src_pairs else 999.0,
            snap_to_km=dst_pairs[0][0] / 1000.0 if dst_pairs else 999.0,
        )

    snap_from_km = src_pairs[0][0] / 1000.0
    snap_to_km = dst_pairs[0][0] / 1000.0

    # **رفض ما هو خارج التغطية — لا سحبه إلى الحافة.**
    #
    # بلا هذا الحد، نقطة في بومرداس (11.3 كم خارج الشبكة) تُسحَب إلى أقرب
    # حافة وتُعطي مساراً يبدو معقولاً. رقم خاطئ بصمت أخطر من «لا أعرف»:
    # المستخدم يقرأ 12 دقيقة لرحلة لم يقصدها.
    if snap_from_km > SNAP_MAX_KM or snap_to_km > SNAP_MAX_KM:
        return PathResult(
            seg_ids=[],
            length_m=0.0,
            found=False,
            snap_from_km=snap_from_km,
            snap_to_km=snap_to_km,
        )

    srcs = [i for _, i in src_pairs]
    dsts = [i for _, i in dst_pairs]

    graph = _csr(_weights(speeds))

    best: tuple[float, int, np.ndarray] | None = None
    for s in srcs:
        dist, pred = cs_dijkstra(
            graph, directed=True, indices=s, return_predecessors=True
        )
        for d in dsts:
            dv = dist[d]
            if not np.isfinite(dv):
                continue
            if best is None or dv < best[0]:
                best = (float(dv), d, pred)
        if best is not None:
            break

    if best is None:
        return PathResult(seg_ids=[], length_m=0.0, found=False)

    total_w, target, pred = best

    # إعادة بناء المسار من السلف
    path: list[int] = [target]
    cur = target
    guard = 0
    while True:
        p = int(pred[cur])
        if p < 0 or guard > m["n_nodes"]:
            break
        path.append(p)
        cur = p
        guard += 1
    path.reverse()

    if len(path) < 2:
        return PathResult(seg_ids=[], length_m=0.0, found=False)

    # إعادة بناء متجهية: مفتاح كل حافة على المسار، ثم بحث ثنائي واحد
    keys, segs_sorted, lens_sorted = _edge_index()
    pa = np.array(path[:-1], dtype=np.int64)
    pb = np.array(path[1:], dtype=np.int64)
    edge_keys = pa * m["n_nodes"] + pb
    pos = np.searchsorted(keys, edge_keys)
    pos_c = np.clip(pos, 0, len(keys) - 1)
    hit = (pos < len(keys)) & (keys[pos_c] == edge_keys)

    seg_ids = [int(x) for x in segs_sorted[pos_c[hit]]]
    length = float(lens_sorted[pos_c[hit]].sum())

    node_ids = m["node_ids"]
    return PathResult(
        seg_ids=seg_ids,
        length_m=round(length, 1),
        nodes=[int(node_ids[i]) for i in path],
        found=bool(seg_ids),
        duration_s=round(total_w, 1),
    )


@lru_cache(maxsize=1)
def _edge_index() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """فهرس الحواف للبحث الثنائي: مفتاح مرتّب → (seg_id, length).

    لماذا لا dict: قاموس بـ512 ألف مدخلاً يكلّف ~5 ثوانٍ في بايثون.
    المصفوفة المرتّبة + `searchsorted` تفعل نفس الشيء في ميلي ثوانٍ.

    المفتاح = src * n_nodes + dst (عدد صحيح واحد بدل زوج).
    """
    m = _load_matrix()
    n = m["n_nodes"]
    keys = m["src"].astype(np.int64) * n + m["dst"].astype(np.int64)
    order = np.argsort(keys)
    return keys[order], m["seg_id"][order], m["length"][order]


def _edge_seg(a: int, b: int) -> int | None:
    keys, segs, _ = _edge_index()
    n = _load_matrix()["n_nodes"]
    k = int(a) * n + int(b)
    pos = int(np.searchsorted(keys, k))
    if pos < len(keys) and keys[pos] == k:
        return int(segs[pos])
    return None


def _edge_len(a: int, b: int) -> float:
    keys, _, lens = _edge_index()
    n = _load_matrix()["n_nodes"]
    k = int(a) * n + int(b)
    pos = int(np.searchsorted(keys, k))
    if pos < len(keys) and keys[pos] == k:
        return float(lens[pos])
    return 0.0


# ============================================================
# سرعات وقت الانطلاق
# ============================================================

def speeds_at(
    when: datetime | None = None, now: datetime | None = None
) -> dict[int, float]:
    """سرعة كل مقطع في وقت معيّن — حي ← ملف تعريف ← حر.

    استعلامان فقط. الاستعلام الواحد لكل مقطع كان يعني 294 ألف استعلام.
    """
    from zahma.predict.engine import (
        bucket_15m,
        calendar_flags,
        day_type_of,
        fetch_live_speeds_bulk,
        fetch_profile_speeds_bulk,
    )

    now = now or datetime.now(UTC)
    when = when or now
    dtype = day_type_of(when)
    flags = calendar_flags(when)
    b = bucket_15m(when)

    live = fetch_live_speeds_bulk(now, max_age_min=10)
    prof = fetch_profile_speeds_bulk(b, dtype, flags)

    # نبدأ من السرعة الحرة (مصفوفة numpy)، ثم نطبّق التخصيصات متجهياً.
    m = _load_matrix()
    spd = m["speed"].copy()
    seg_unique, inverse = _seg_row()

    for mapping in (prof, live):
        if not mapping:
            continue
        keys = np.fromiter(mapping.keys(), dtype=np.int64, count=len(mapping))
        vals = np.fromiter(mapping.values(), dtype=np.float64, count=len(mapping))
        pos = np.clip(np.searchsorted(seg_unique, keys), 0, len(seg_unique) - 1)
        hit = seg_unique[pos] == keys
        if not hit.any():
            continue
        custom = np.full(len(seg_unique), np.nan, dtype=np.float64)
        custom[pos[hit]] = vals[hit]
        assigned = custom[inverse]
        spd = np.where(np.isnan(assigned), spd, assigned)

    return {
        int(sid): float(v)
        for sid, v in zip(m["seg_id"], spd, strict=False)
    }


def route_at(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    when: datetime | None = None,
    now: datetime | None = None,
) -> PathResult:
    """توجيه بسرعات وقت الانطلاق — الزحمة تؤثر على اختيار المسار نفسه."""
    return route(
        from_lat, from_lon, to_lat, to_lon, speeds=speeds_at(when=when, now=now)
    )


def build_graph(speeds: dict[int, float] | None = None):  # توافق للخلف
    """يحتفظ بالتوقيع القديم — يعيد المصفوفة الموزونة."""
    return _csr(_weights(speeds))


def clear_cache() -> None:
    _load_matrix.cache_clear()
    _node_pos.cache_clear()
    _coords.cache_clear()
    _routable_mask.cache_clear()
    _grid.cache_clear()
    _edge_index.cache_clear()
    _seg_row.cache_clear()


def stats() -> dict:
    """أرقام المصفوفة — للتحقق في CI."""
    m = _load_matrix()
    mask = _routable_mask()
    return {
        "nodes": m["n_nodes"],
        "edges": len(m["src"]),
        "segments": len(np.unique(m["seg_id"])),
        "routable_nodes": int(mask.sum()),
        "routable_share": round(float(mask.sum()) / m["n_nodes"] * 100, 1),
        "matrix_mb": round(MATRIX_CACHE.stat().st_size / 1e6, 1)
        if MATRIX_CACHE.exists()
        else 0.0,
    }
