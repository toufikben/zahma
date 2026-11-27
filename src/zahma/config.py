"""إعدادات التطبيق — تُقرأ من متغيرات البيئة وملف .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"

# حدود ولاية الجزائر التقريبية (WGS84: south, west, north, east)
# تُستخدم لقصّ مستخرج OSM الوطني إلى نطاق العمل.
ALGIERS_BBOX = (36.60, 2.65, 36.85, 3.35)

# مركز العاصمة — للاستخدام في طلبات النطاق
ALGIERS_CENTER = (36.7538, 3.0588)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://zahma:zahma@localhost:5432/zahma"

    mapbox_token: str = ""
    tomtom_key: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    scan_interval_peak_min: int = 30
    scan_interval_offpeak_min: int = 120
    # الليل مسطّح (64–68 كم/س، مدى 4.2). جمعه كل 3 ساعات يكفي لوصف
    # الشكل وإثبات أنه لم يتغير؛ الهدف ليس اكتشاف تغيّر لا يوجد.
    scan_interval_night_min: int = 180
    deep_interval_peak_min: int = 5
    quota_soft_limit: float = 0.90
    tz_name: str = "Africa/Algiers"
    weather_enabled: bool = True

    @property
    def has_mapbox(self) -> bool:
        return bool(self.mapbox_token.strip())

    @property
    def has_tomtom(self) -> bool:
        return bool(self.tomtom_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
