"""واجهة المصادر — العقد الوحيد بين النظام والعالم الخارجي.

كل مصدر يعيد نفس الشكل، مهما اختلف API-ه. هذا يسمح بتبديل المصادر
وأضافتها بلا تغيير في المجمّع أو النموذج.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from zahma.config import ALGIERS_BBOX


def utcnow() -> datetime:
    return datetime.now(UTC)


def ts_bucket(ts: datetime, minutes: int = 5) -> datetime:
    """يقرّب الطابع الزمني إلى حاوية — مفتاح idempotency."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    else:
        ts = ts.astimezone(UTC)
    total = int(ts.timestamp())
    size = minutes * 60
    return datetime.fromtimestamp(total - (total % size), tz=UTC)


def in_algiers(lat: float, lon: float) -> bool:
    s, w, n, e = ALGIERS_BBOX
    return s <= lat <= n and w <= lon <= e


@dataclass(slots=True)
class SegmentSample:
    """قياس مقطع واحد."""

    segment_id: int
    source: str
    ts_utc: datetime
    speed_kmh: float | None = None
    freeflow_kmh: float | None = None
    travel_time_s: float | None = None
    confidence: float | None = None
    raw_ref: str | None = None

    def __post_init__(self) -> None:
        if self.speed_kmh is not None and self.freeflow_kmh:
            self.confidence = self.confidence if self.confidence is not None else 0.8


@dataclass(slots=True)
class RouteSample:
    """قياس رحلة كاملة بين زوج انطلاق/وصول."""

    pair_id: int
    source: str
    ts_utc: datetime
    duration_s: float
    duration_free_s: float | None = None
    distance_m: float | None = None
    confidence: float | None = None
    geometry_wkt: str | None = None
    segment_samples: list[SegmentSample] = field(default_factory=list)

    @property
    def delay_ratio(self) -> float | None:
        if not self.duration_free_s or self.duration_free_s <= 0:
            return None
        return self.duration_s / self.duration_free_s


@dataclass(slots=True)
class Incident:
    """عطل أو حادث."""

    source: str
    external_id: str
    ts_utc: datetime
    category: int | None = None
    category_name: str | None = None
    severity: int | None = None
    magnitude: int | None = None
    delay_s: int | None = None
    length_m: int | None = None
    description: str | None = None
    from_desc: str | None = None
    to_desc: str | None = None
    road_name: str | None = None
    lat: float | None = None
    lon: float | None = None
    geometry_wkt: str | None = None


@dataclass(slots=True)
class SourceResult:
    """نتيجة استدعاء مصدر واحد."""

    source: str
    ok: bool
    fetched_at: datetime
    requests_used: int = 0
    segment_samples: list[SegmentSample] = field(default_factory=list)
    route_samples: list[RouteSample] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    error: str | None = None
    raw_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def total_records(self) -> int:
        return (
            len(self.segment_samples)
            + len(self.route_samples)
            + len(self.incidents)
        )


class SourceError(Exception):
    """خطأ مصدر قابل لإعادة المحاولة أو لا."""

    def __init__(self, msg: str, *, retryable: bool = True, quota_exhausted: bool = False):
        super().__init__(msg)
        self.retryable = retryable
        self.quota_exhausted = quota_exhausted


class TrafficSource(ABC):
    """العقد الأساسي لكل مصدر.

    كل مصدر يعلن:
    - name: معرّف فريد يطابق source_kind في قاعدة البيانات
    - monthly_quota: الحصة المجانية الشهرية (لمراقبة الاستهلاك)
    - fetch(): تنفيذ الطلب
    """

    name: str = "base"
    monthly_quota: int = 0

    @abstractmethod
    def available(self) -> bool:
        """هل المفاتيح/الشروط متوفرة؟"""

    @abstractmethod
    def fetch(self, **kwargs: Any) -> SourceResult:
        """تنفيذ الطلب وإرجاع نتيجة موحّدة."""

    # مساعدات مشتركة
    @staticmethod
    def stable_id(*parts: Any) -> str:
        """معرّف ثابت من أجزاء — لإزالة التكرار في الأعطال."""
        h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
        return h[:16]

    @staticmethod
    def bucket(minutes: int = 5) -> datetime:
        return ts_bucket(utcnow(), minutes)
