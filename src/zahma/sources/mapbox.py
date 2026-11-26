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

    def probe(self, origin: tuple[float, float], dest: tuple[float, float]) -> dict[str, Any]:
        """استدعاء واحد للتحقق: هل توجد بيانات حركة حقيقية؟

        يقارن driving (بلا زحمة) مع driving-traffic (بالزحمة).
        إن تساوت المدد ⇒ لا بيانات حركة لهذا البلد.
        """
        if not self.available():
            return {"ok": False, "error": "MAPBOX_TOKEN missing"}

        coords = f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
        out: dict[str, Any] = {}
        with httpx.Client(timeout=self.timeout) as client:
            for prof in ("driving", "driving-traffic"):
                r = client.get(
                    f"{BASE}/{prof}/{coords}",
                    params={
                        "access_token": self.settings.mapbox_token,
                        "overview": "false",
                        "annotations": "duration,congestion",
                    },
                )
                if r.status_code >= 400:
                    out[prof] = {"error": f"HTTP {r.status_code}", "body": r.text[:200]}
                    continue
                d = r.json()
                rt = (d.get("routes") or [{}])[0]
                out[prof] = {
                    "duration_s": rt.get("duration"),
                    "distance_m": rt.get("distance"),
                }

        a = out.get("driving", {}).get("duration_s")
        b = out.get("driving-traffic", {}).get("duration_s")
        if a and b:
            out["diff_pct"] = round((b - a) / a * 100, 2)
            out["has_live_traffic"] = abs(out["diff_pct"]) >= 5.0
        return out
