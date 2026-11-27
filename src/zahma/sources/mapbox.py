"""محوّل Mapbox — المسح الواسع.

لماذا Mapbox هنا:
- الحصة المجانية 100,000 طلب/شهر (5× TomTom).
- طلب واحد يعطي مساراً كاملاً مع سرعة وزحمة **لكل مقطع** عبر
  `annotations=speed,congestion`.
- يدعم profile `driving-traffic` الذي يفرق بين الحالة الحالية والتاريخية.

هذا يجعل منه أداة الاكتشاف: نكشف أين الزحمة في كل المدينة،
ثم نعمّق على المكتشف بمصادر أخرى.

تنبيه قانوني: البيانات تُخزَّن للتحليل الداخلي. راجع شروط Mapbox
قبل أي إعادة توزيع للبيانات الخام.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from zahma.config import get_settings
from zahma.sources.base import (
    RouteSample,
    SegmentSample,
    SourceError,
    SourceResult,
    TrafficSource,
    ts_bucket,
)

BASE = "https://api.mapbox.com/directions/v5/mapbox"


class MapboxSource(TrafficSource):
    name = "mapbox"
    monthly_quota = 100_000

    def __init__(self, timeout: float = 20.0):
        self.settings = get_settings()
        self.timeout = timeout

    def available(self) -> bool:
        return self.settings.has_mapbox

    def fetch(
        self,
        pairs: list[dict],
        profile: str = "driving-traffic",
        annotations: str = "duration,speed,congestion,distance",
        overview: str = "full",
        geometry: str = "geojson",
    ) -> SourceResult:
        """يجلب مسارات لأزواج انطلاق/وصول.

        كل طلب = زوج واحد. الاستجابة تحتوي مساراً مع تعليقات لكل مقطع.
        """
        now = datetime.now(UTC)
        bucket = ts_bucket(now, 5)
        seg_samples: list[SegmentSample] = []
        route_samples: list[RouteSample] = []
        errors: list[str] = []
        used = 0

        if not self.available():
            return SourceResult(
                source=self.name, ok=False, fetched_at=now,
                error="MAPBOX_TOKEN missing",
            )

        with httpx.Client(timeout=self.timeout) as client:
            for p in pairs:
                coords = (
                    f"{p['from'][1]},{p['from'][0]};{p['to'][1]},{p['to'][0]}"
                )
                url = f"{BASE}/{profile}/{coords}"
                params = {
                    "access_token": self.settings.mapbox_token,
                    "annotations": annotations,
                    "overview": overview,
                    "geometries": geometry,
                    "steps": "false",
                }
                try:
                    r = client.get(url, params=params)
                    used += 1
                    if r.status_code == 429:
                        raise SourceError("rate limited", quota_exhausted=True)
                    if r.status_code >= 400:
                        errors.append(f"{p['pair_id']}: HTTP {r.status_code}")
                        continue

                    data = r.json()
                    routes = data.get("routes") or []
                    if not routes:
                        errors.append(f"{p['pair_id']}: no route")
                        continue

                    route = routes[0]
                    legs = route.get("legs") or []
                    if not legs:
                        continue

                    leg = legs[0]
                    ann = leg.get("annotation") or {}
                    durations = ann.get("duration") or []
                    speeds = ann.get("speed") or []
                    distances = ann.get("distance") or []

                    duration_s = float(route.get("duration", 0.0))
                    distance_m = float(route.get("distance", 0.0))

                    # كل عنصر في annotation = مقطع
                    for i, dur in enumerate(durations):
                        spd = speeds[i] if i < len(speeds) else None
                        dist = distances[i] if i < len(distances) else None
                        seg_samples.append(
                            SegmentSample(
                                segment_id=-1,  # يُربَط لاحقاً بالشبكة
                                source=self.name,
                                ts_utc=now,
                                speed_kmh=float(spd) * 3.6 if spd is not None else None,
                                travel_time_s=float(dur),
                                confidence=0.75,
                                raw_ref=f"pair={p['pair_id']};idx={i};dist={dist}",
                            )
                        )

                    route_samples.append(
                        RouteSample(
                            pair_id=int(p["pair_id"]),
                            source=self.name,
                            ts_utc=now,
                            duration_s=duration_s,
                            distance_m=distance_m,
                            confidence=0.75,
                            segment_samples=[],
                        )
                    )

                except SourceError:
                    raise
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{p['pair_id']}: {type(e).__name__}")

        return SourceResult(
            source=self.name,
            ok=len(route_samples) > 0,
            fetched_at=now,
            requests_used=used,
            segment_samples=seg_samples,
            route_samples=route_samples,
            error="; ".join(errors[:5]) if errors else None,
            raw_meta={"bucket": bucket.isoformat(), "pairs": len(pairs)},
        )

    def probe(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        probe_day: str = "2026-11-30",
    ) -> dict[str, Any]:
        """هل يملك Mapbox إشارة حركة حقيقية للجزائر؟ — الاختبار الحقيقي.

        **لماذا لا يكفي مقارنة `driving` بـ`driving-traffic` الآن:**

        جرّبنا ذلك فعلياً الساعة 04:00 محلياً فكان الفرق 1% فقط. السبب أن
        الشوارع فارغة في ذلك الوقت، فلا حركة ليقيسها المزوّد. المقارنة
        «الآن» تقيس الساعة لا جودة التغطية — وقد تعطي حكماً كاذباً بأن
        المشروع بلا بيانات.

        **ما نقيسه بدلاً من ذلك:**

        1. `duration` مقابل `duration_typical` عبر `depart_at` في ساعات
           مختلفة. إن كانت النسبة تتغيّر مع الساعة ⇒ المزوّد يعرف نمط
           الازدحام الزمني، وهذا كل ما نحتاجه للتنبؤ.
        2. `driving` (بلا حركة) مقابل `driving-traffic` عند **نفس** ساعة
           الذروة. الفرق هنا يعزل أثر الحركة عن أثر الطريق.
        3. تغطية `congestion` لكل مقطع. مقيس فعلياً: في الجزائر العاصمة
           كل المقاطع تُرجع `"unknown"` — لا أصناف ازدحام على مستوى
           المقطع. هذه حقيقة يجب أن تُسجَّل لا أن تُخفى.

        الحكم النهائي مبني على **مدى تغيّر المدة مع الساعة**، لأنه هو
        ما يحدد إن كان المنتج ممكناً أم لا.
        """
        if not self.available():
            return {"ok": False, "error": "MAPBOX_TOKEN missing"}

        coords = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
        out: dict[str, Any] = {"ok": True}

        # ساعات الاختبار: ذروة صباحية، منتصف النهار، ذروة مسائية.
        hours = ("07:30", "12:00", "17:30")

        with httpx.Client(timeout=self.timeout) as client:
            token = self.settings.mapbox_token

            # ── 1) المدة عبر ساعات اليوم (driving-traffic + depart_at)
            by_hour: dict[str, Any] = {}
            for hh in hours:
                r = client.get(
                    f"{BASE}/driving-traffic/{coords}",
                    params={
                        "access_token": token,
                        "overview": "false",
                        "depart_at": f"{probe_day}T{hh}",
                    },
                )
                if r.status_code >= 400:
                    by_hour[hh] = {
                        "error": f"HTTP {r.status_code}",
                        "body": r.text[:200],
                    }
                    continue
                rt = (r.json().get("routes") or [{}])[0]
                dur = rt.get("duration")
                typ = rt.get("duration_typical")
                by_hour[hh] = {
                    "duration_s": dur,
                    "duration_typical_s": typ,
                    # النسبة > 1 تعني أبطأ من المعتاد = ازدحام مقيس.
                    "ratio": (round(dur / typ, 3) if dur and typ else None),
                }
            out["by_hour"] = by_hour

            # ── 2) بلا حركة مقابل بالحركة عند ذروة صباحية
            peak = hours[0]
            r = client.get(
                f"{BASE}/driving/{coords}",
                params={
                    "access_token": token,
                    "overview": "false",
                    "depart_at": f"{probe_day}T{peak}",
                },
            )
            if r.status_code < 400:
                rt = (r.json().get("routes") or [{}])[0]
                freeflow: dict[str, Any] = {
                    "duration_s": rt.get("duration"),
                    "distance_m": rt.get("distance"),
                }
            else:
                freeflow = {
                    "error": f"HTTP {r.status_code}",
                    "body": r.text[:200],
                }
            out["freeflow_at_peak"] = freeflow

            traffic_dur = by_hour.get(peak, {}).get("duration_s")
            ff_dur = freeflow.get("duration_s")
            if traffic_dur and ff_dur:
                # كم تبطئ الحركة الطريق مقارنة بالسرعة الحرة؟
                out["traffic_penalty_pct"] = round(
                    (traffic_dur - ff_dur) / ff_dur * 100, 2
                )

            # ── 3) تغطية congestion على مستوى المقطع
            # ملاحظة مقاسة: congestion يتطلب overview=full، وإلا 422.
            r = client.get(
                f"{BASE}/driving-traffic/{coords}",
                params={
                    "access_token": token,
                    "overview": "full",
                    "annotations": "congestion,speed,duration",
                },
            )
            if r.status_code < 400:
                rt = (r.json().get("routes") or [{}])[0]
                legs = rt.get("legs") or [{}]
                ann = legs[0].get("annotation") or {}
                cong = ann.get("congestion") or []
                speeds = ann.get("speed") or []
                if cong:
                    known = [c for c in cong if c and c != "unknown"]
                    out["congestion"] = {
                        "segments": len(cong),
                        "known": len(known),
                        "unknown": len(cong) - len(known),
                        "coverage_pct": round(len(known) / len(cong) * 100, 1),
                        "classes": sorted({c for c in cong if c}),
                    }
                else:
                    out["congestion"] = {"segments": 0, "error": "no annotation"}
                if speeds:
                    out["speed_mps_range"] = [
                        round(min(speeds), 2),
                        round(max(speeds), 2),
                    ]
            else:
                out["congestion"] = {
                    "error": f"HTTP {r.status_code}",
                    "body": r.text[:200],
                }

        # ── الحكم: هل تتغيّر المدة مع الساعة؟
        durs = [
            v["duration_s"]
            for v in out["by_hour"].values()
            if isinstance(v, dict) and v.get("duration_s")
        ]
        if len(durs) >= 2:
            lo, hi = min(durs), max(durs)
            spread_pct = (hi - lo) / lo * 100
            out["spread_pct"] = round(spread_pct, 2)
            # 8% فرق بين الذروة والهادئ = إشارة حقيقية قابلة للبيع.
            out["has_time_varying_traffic"] = spread_pct >= 8.0
        else:
            out["has_time_varying_traffic"] = False

        return out
