"""محوّل وهمي — يغذي التطوير بلا مفاتيح ولا استهلاك حصة.

يولّد بيانات «واقعية» تعكس أنماط العاصمة:
- ذروة صباحية 07:00–09:00
- ذروة مسائية 16:30–19:00
- هدوء الجمعة صباحاً
- ذروة رمضانية 16:00–19:00

الغرض: بناء واختبار كل النظام قبل وصول أي مفتاح، ثم استبداله
بمحوّل حقيقي بلا تغيير في أي طبقة أخرى.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from zahma.sources.base import (
    Incident,
    RouteSample,
    SegmentSample,
    SourceResult,
    TrafficSource,
    ts_bucket,
)

TZ = ZoneInfo("Africa/Algiers")


class MockSource(TrafficSource):
    name = "mock"
    monthly_quota = 0

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def available(self) -> bool:
        return True

    @staticmethod
    def _day_type(dt_local: datetime) -> str:
        wd = dt_local.weekday()  # 0=الإثنين .. 6=الأحد
        if wd == 4:  # الجمعة
            return "FRIDAY"
        if wd == 5:  # السبت
            return "SATURDAY"
        return "WORKDAY"

    @staticmethod
    def congestion_curve(hour: float, day_type: str) -> float:
        """نسبة الزحمة 0..1 كدالة للساعة.

        مبني على أنماط معروفة للعاصمة، لا على بيانات مقاسة بعد.
        سيُستبدل بملف تعريف مقاس في المرحلة 4.
        """
        if day_type == "FRIDAY":
            peaks = [(13.0, 1.4, 0.85), (18.5, 1.6, 0.70)]
        elif day_type == "SATURDAY":
            peaks = [(11.0, 1.8, 0.55), (18.0, 1.8, 0.60)]
        else:
            peaks = [(7.8, 1.3, 1.00), (17.5, 1.6, 0.95)]

        total = 0.0
        for center, width, amp in peaks:
            total += amp * math.exp(-((hour - center) ** 2) / (2 * width**2))
        # أرضية ضيقة: الشوارع لا تفرغ تماماً
        return min(1.0, total + 0.05)

    def fetch(
        self,
        segments: list[dict] | None = None,
        pairs: list[dict] | None = None,
        now: datetime | None = None,
        n_segments: int = 40,
        n_pairs: int = 10,
    ) -> SourceResult:
        now = now or datetime.now(UTC)
        bucket = ts_bucket(now, 5)
        local = now.astimezone(TZ)
        day = self._day_type(local)
        hour = local.hour + local.minute / 60.0
        cong = self.congestion_curve(hour, day)

        seg_samples: list[SegmentSample] = []
        if segments:
            # نقيس **كل** المقاطع الممرَّرة، لا عينة عشوائية منها.
            # العينة العشوائية تعني أن كل مقطع يُقاس في ~27% من الخطوات،
            # فتقلّ عيناته تحت حد الملف (n>=3) ويبقى النموذج أعمى.
            # القائمة نفسها محدودة أصلاً عند التحميل (n_segments).
            chosen = segments if len(segments) <= n_segments else self.rng.sample(segments, n_segments)
        else:
            chosen = [{"seg_id": i, "speed_free_kmh": 50, "length_m": 200} for i in range(1, n_segments + 1)]

        for s in chosen:
            free = float(s.get("speed_free_kmh", 50))
            # الزحمة تخفض السرعة، مع تشويش لكل مقطع
            jitter = self.rng.gauss(0, 0.06)
            ratio = max(0.15, 1.0 - cong * (0.55 + jitter))
            speed = max(5.0, free * ratio)
            seg_samples.append(
                SegmentSample(
                    segment_id=int(s["seg_id"]),
                    source=self.name,
                    ts_utc=now,
                    speed_kmh=round(speed, 1),
                    freeflow_kmh=free,
                    travel_time_s=round(float(s.get("length_m", 200)) / (speed / 3.6), 1),
                    confidence=0.9,
                    raw_ref=f"mock;cong={cong:.3f}",
                )
            )

        route_samples: list[RouteSample] = []
        if pairs:
            chosen_pairs = self.rng.sample(pairs, min(n_pairs, len(pairs)))
        else:
            chosen_pairs = [{"pair_id": i, "crow_km": 15} for i in range(1, n_pairs + 1)]

        for p in chosen_pairs:
            km = float(p.get("crow_km", 15))
            # مسار فعلي أطول من المسافة الهوائية بـ~35%
            road_km = km * 1.35
            free_s = road_km / 55 * 3600  # 55 كم/س متوسط حر
            delay = 1.0 + cong * self.rng.uniform(0.6, 1.1)
            route_samples.append(
                RouteSample(
                    pair_id=int(p["pair_id"]),
                    source=self.name,
                    ts_utc=now,
                    duration_s=round(free_s * delay, 1),
                    duration_free_s=round(free_s, 1),
                    distance_m=round(road_km * 1000, 1),
                    confidence=0.85,
                )
            )

        incidents: list[Incident] = []
        if cong > 0.5 and self.rng.random() < 0.5:
            incidents.append(
                Incident(
                    source=self.name,
                    external_id=self.stable_id("mock", bucket.isoformat()),
                    ts_utc=now,
                    category=6,
                    category_name="jam",
                    severity=2,
                    magnitude=3,
                    description="ازدحام مروري (بيانات وهمية)",
                    road_name="Rocade Sud",
                    lat=36.72,
                    lon=3.14,
                    geometry_wkt="POINT(3.14 36.72)",
                )
            )

        return SourceResult(
            source=self.name,
            ok=True,
            fetched_at=now,
            requests_used=0,
            segment_samples=seg_samples,
            route_samples=route_samples,
            incidents=incidents,
            raw_meta={
                "day_type": day,
                "hour_local": round(hour, 2),
                "congestion": round(cong, 3),
                "bucket": bucket.isoformat(),
            },
        )

    def series(self, days: int = 14, step_min: int = 30) -> list[SourceResult]:
        """يولّد سلسلة زمنية — لاختبار النموذج قبل وصول البيانات الحقيقية."""
        out = []
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        t = start
        while t <= end:
            out.append(self.fetch(now=t))
            t += timedelta(minutes=step_min)
        return out
