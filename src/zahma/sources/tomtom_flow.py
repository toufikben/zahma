"""محوّل TomTom Flow — العمق والتحقق المستقل.

لماذا TomTom هنا:
- حصة 20,000 طلب/شهر على مستوى المقطع.
- يعطي `currentSpeed` و`freeFlowSpeed` و`confidence` و`roadClosure`
  في نفس الاستجابة — أي مقياساً وتحققه معاً.
- مصدر مستقل عن Mapbox: اتفاقهما يعني ثقة، وخلافهما يعني حدثاً.

الاستخدام: 6 محاور × كل 5 دقائق في الذروة.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from zahma.config import get_settings
from zahma.collect.http import RetryingClient
from zahma.sources.base import (
    SegmentSample,
    SourceError,
    SourceResult,
    TrafficSource,
    ts_bucket,
)

BASE = "https://api.tomtom.com/traffic/services/4/flowSegmentData"


class TomTomFlowSource(TrafficSource):
    name = "tomtom_flow"
    monthly_quota = 20_000

    def __init__(self, timeout: float = 15.0):
        self.settings = get_settings()
        self.timeout = timeout

    def available(self) -> bool:
        return self.settings.has_tomtom

    def fetch(
        self,
        points: list[dict],
        zoom: int = 12,
        style: str = "absolute",
        unit: str = "KMPH",
    ) -> SourceResult:
        """يجلب سرعة مقطع عند نقطة.

        `points`: [{"segment_id": 123, "lat": .., "lon": ..}, ...]
        الحصة: طلب واحد لكل نقطة — لذا نحدّ العدد.
        """
        now = datetime.now(UTC)
        bucket = ts_bucket(now, 5)
        samples: list[SegmentSample] = []
        errors: list[str] = []
        used = 0

        if not self.available():
            return SourceResult(
                source=self.name, ok=False, fetched_at=now, error="TOMTOM_KEY missing"
            )

        with httpx.Client(timeout=self.timeout) as _raw:
            client = RetryingClient(timeout=self.timeout, client=_raw, retry_on_429=False)
            for pt in points:
                url = f"{BASE}/{style}/{zoom}/json"
                params = {
                    "key": self.settings.tomtom_key,
                    "point": f"{pt['lat']},{pt['lon']}",
                    "unit": unit,
                }
                try:
                    r = client.get(url, params=params)
                    used += 1
                    if r.status_code == 429:
                        raise SourceError("quota exceeded", quota_exhausted=True)
                    if r.status_code >= 400:
                        errors.append(f"{pt['segment_id']}: HTTP {r.status_code}")
                        continue

                    d = r.json().get("flowSegmentData") or {}
                    cur = d.get("currentSpeed")
                    free = d.get("freeFlowSpeed")
                    if cur is None:
                        errors.append(f"{pt['segment_id']}: no data")
                        continue

                    # 0 = بيانات ضعيفة الثقة في TomTom
                    conf_raw = d.get("confidence", 1.0)
                    conf = 0.9 if conf_raw else 0.5

                    samples.append(
                        SegmentSample(
                            segment_id=int(pt["segment_id"]),
                            source=self.name,
                            ts_utc=now,
                            speed_kmh=float(cur),
                            freeflow_kmh=float(free) if free is not None else None,
                            travel_time_s=float(d.get("currentTravelTime", 0) or 0) or None,
                            confidence=conf,
                            raw_ref=f"fc={d.get('frc')};closure={d.get('roadClosure')}",
                        )
                    )
                except SourceError:
                    raise
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{pt['segment_id']}: {type(e).__name__}")

        return SourceResult(
            source=self.name,
            ok=len(samples) > 0,
            fetched_at=now,
            requests_used=used,
            segment_samples=samples,
            error="; ".join(errors[:5]) if errors else None,
            raw_meta={"bucket": bucket.isoformat(), "points": len(points)},
        )

    def probe(self, lat: float, lon: float, zoom: int = 12) -> dict[str, Any]:
        """استدعاء تحقق واحد: هل توجد بيانات حركة حقيقية؟

        إن كان currentSpeed قريباً من freeFlowSpeed دائماً ⇒ لا زحمة مرصودة.
        """
        if not self.available():
            return {"ok": False, "error": "TOMTOM_KEY missing"}
        try:
            with RetryingClient(timeout=self.timeout) as client:
                r = client.get(
                    f"{BASE}/absolute/{zoom}/json",
                    params={"key": self.settings.tomtom_key, "point": f"{lat},{lon}"},
                )
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        if r.status_code >= 400:
            return {"ok": False, "error": f"HTTP {r.status_code}", "body": r.text[:200]}

        d = r.json().get("flowSegmentData") or {}
        cur, free = d.get("currentSpeed"), d.get("freeFlowSpeed")
        out: dict[str, Any] = {
            "ok": True,
            "current": cur,
            "freeflow": free,
            "confidence": d.get("confidence"),
            "road_closure": d.get("roadClosure"),
            "frc": d.get("frc"),
        }
        if cur and free:
            out["ratio"] = round(cur / free, 3)
            out["has_congestion_data"] = out["ratio"] < 0.85
        return out
