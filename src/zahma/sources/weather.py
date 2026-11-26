"""محوّل الطقس — عامل تصحيح في النموذج.

المطر في الجزائر يسبب اختناقاً غير متناسب مع كميته:
شبكة تصريف محدودة + سلوك قيادة حذر + حوادث أكثر.
لذلك الطقس ليس ترفاً، بل متغير تفسيري مهم.

المصدر: Open-Meteo — مجاني بلا مفتاح ولا حد فعلي للاستخدام غير التجاري.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from zahma.config import ALGIERS_CENTER
from zahma.sources.base import SourceResult, TrafficSource

BASE = "https://api.open-meteo.com/v1/forecast"


class WeatherSource(TrafficSource):
    name = "weather"
    monthly_quota = 0  # بلا حد فعلي

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def available(self) -> bool:
        return True

    def fetch(self, lat: float | None = None, lon: float | None = None) -> SourceResult:
        now = datetime.now(UTC)
        lat = lat or ALGIERS_CENTER[0]
        lon = lon or ALGIERS_CENTER[1]

        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,precipitation,rain,weather_code,"
                "wind_speed_10m,visibility,cloud_cover"
            ),
            "hourly": "precipitation,weather_code",
            "forecast_days": 1,
            "timezone": "Africa/Algiers",
        }
        try:
            r = httpx.get(BASE, params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            return SourceResult(source=self.name, ok=False, fetched_at=now, error=str(e))

        cur = data.get("current") or {}
        return SourceResult(
            source=self.name,
            ok=True,
            fetched_at=now,
            raw_meta={
                "temp_c": cur.get("temperature_2m"),
                "precip_mm": cur.get("precipitation"),
                "rain_mm": cur.get("rain"),
                "weather_code": cur.get("weather_code"),
                "wind_kmh": cur.get("wind_speed_10m"),
                "visibility_m": cur.get("visibility"),
                "factor": self.weather_factor(cur.get("precipitation") or 0.0),
            },
        )

    @staticmethod
    def weather_factor(precip_mm: float) -> float:
        """معامل تصحيح المدة حسب المطر.

        مبني على فرضية تحتاج معايرة من البيانات:
        مطر خفيف في الجزائر يسبب تأخيراً أكبر نسبياً من مدن بشبكة تصريف جيدة.
        """
        if precip_mm <= 0.0:
            return 1.0
        if precip_mm < 1.0:
            return 1.08
        if precip_mm < 3.0:
            return 1.18
        if precip_mm < 8.0:
            return 1.30
        return 1.45

    def forecast_hourly(self) -> dict[int, float]:
        """توقّع المطر بالساعة — يُستخدم في التنبؤ المستقبلي."""
        now = datetime.now(UTC)
        params = {
            "latitude": ALGIERS_CENTER[0],
            "longitude": ALGIERS_CENTER[1],
            "hourly": "precipitation",
            "forecast_days": 2,
            "timezone": "Africa/Algiers",
        }
        try:
            r = httpx.get(BASE, params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception:  # noqa: BLE001
            return {}
        times = (data.get("hourly") or {}).get("time") or []
        precs = (data.get("hourly") or {}).get("precipitation") or []
        out: dict[int, float] = {}
        for t, p in zip(times, precs, strict=False):
            try:
                h = datetime.fromisoformat(t).hour
                out[h] = max(out.get(h, 0.0), float(p or 0.0))
            except Exception:  # noqa: BLE001
                continue
        return out
