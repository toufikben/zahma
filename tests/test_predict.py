"""اختبارات محرك التنبؤ — المنطق الصرف بلا قاعدة بيانات.

نختبر ما يمكن الحكم عليه رياضياً:
- تحويل التوقيت إلى شرائح زمنية.
- منحنى الانطلاق: خصائصه المنطقية (لا يعيد خروجاً سالب التوفير كأفضل).
- قرار الموعد النهائي: لا يعيد خروجاً لا يضمن الوصول.
- الثقة: لا تتجاوز الحدود، وتنخفض مع عدم اليقين.

لماذا هذه الاختبارات لا تحتاج قاعدة بيانات: الدوال هنا صرفة،
والاختبار عليها يثبت صحة القرار قبل أن نربطه ببيانات حقيقية.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from zahma.predict.engine import (
    DepartureOption,
    RouteEstimate,
    SegmentEstimate,
    best_departure,
    bucket_15m,
    latest_departure_for_deadline,
)

TZ = ZoneInfo("Africa/Algiers")


# ============================================================
# الشرائح الزمنية
# ============================================================

def test_bucket_15m_boundaries() -> None:
    """الشريحة = 4 لكل ساعة، والحدود صحيحة."""
    cases = [
        ((0, 0), 0),
        ((0, 14), 0),
        ((0, 15), 1),
        ((0, 59), 3),
        ((7, 0), 28),
        ((7, 30), 30),
        ((23, 45), 95),
        ((23, 59), 95),
    ]
    for (h, m), want in cases:
        dt = datetime(2026, 11, 26, h, m, tzinfo=TZ)
        assert bucket_15m(dt) == want, f"{h}:{m} -> {bucket_15m(dt)}, want {want}"


def test_bucket_15m_covers_full_day() -> None:
    """96 شريحة لكل يوم — لا فجوة ولا تجاوز."""
    seen = set()
    for h in range(24):
        for m in range(0, 60, 5):
            seen.add(bucket_15m(datetime(2026, 11, 26, h, m, tzinfo=TZ)))
    assert min(seen) == 0
    assert max(seen) == 95
    assert len(seen) == 96


# ============================================================
# منحنى الانطلاق
# ============================================================

def _opt(depart_offset_min: int, dur_min: float, conf: float = 0.8) -> DepartureOption:
    base = datetime(2026, 11, 26, 7, 0, tzinfo=UTC)
    dep = base + timedelta(minutes=depart_offset_min)
    return DepartureOption(
        depart_at=dep,
        arrive_at=dep + timedelta(minutes=dur_min),
        duration_s=dur_min * 60,
        duration_p90_s=dur_min * 60 * 1.2,
        confidence=conf,
        saving_vs_now_s=0.0,
    )


def test_best_departure_picks_minimum() -> None:
    """أفضل خروج = أقل مدة بين الخيارات الموثوقة."""
    curve = [
        _opt(0, 40.0),
        _opt(15, 25.0),
        _opt(30, 30.0),
        _opt(45, 22.0),
    ]
    best = best_departure(curve)
    assert best is not None
    assert best.duration_s == 22.0 * 60


def test_best_departure_respects_confidence_floor() -> None:
    """الخيار الأسرع لكن غير موثوق لا يُختار."""
    curve = [
        _opt(0, 40.0, conf=0.8),
        _opt(15, 10.0, conf=0.2),   # أسرع لكن ثقة منخفضة
    ]
    best = best_departure(curve, min_confidence=0.4)
    assert best is not None
    assert best.duration_s == 40.0 * 60


def test_best_departure_none_when_all_unreliable() -> None:
    """إن لم يبلغ أي خيار حد الثقة، نعيد «لا أعرف» لا رقماً كاذباً."""
    curve = [_opt(0, 30.0, conf=0.1), _opt(15, 20.0, conf=0.2)]
    assert best_departure(curve, min_confidence=0.4) is None


# ============================================================
# الموعد النهائي
# ============================================================

def test_deadline_uses_p90_not_p50() -> None:
    """قرار الموعد النهائي يعتمد p90 — يفضّل الوصول مبكراً على التأخر.

    السيناريو الحاسم: خروج p50 يصل قبل الموعد، لكن p90 يتجاوزه.
    إن كان القرار على p50 لَقبِله؛ وعلى p90 يرفضه. الصحيح: يرفضه.
    """
    deadline = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)

    # 07:00 + 55 دقيقة = 07:55 (p50 ✓)
    # p90 = 55 × 1.2 = 66 دقيقة = 08:06 (✗ يتجاوز الموعد)
    risky = _opt(0, 55.0)
    assert risky.arrive_at < deadline, "p50 should arrive before deadline"
    assert risky.arrive_at + timedelta(
        seconds=risky.duration_p90_s - risky.duration_s
    ) > deadline, "p90 should miss deadline"

    assert latest_departure_for_deadline([risky], deadline) is None


def test_deadline_accepts_when_p90_fits() -> None:
    """نفس المنطق: خروج p90 يصل قبل الموعد ⇒ مقبول."""
    deadline = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
    # 07:00 + 40 = 07:40 p50، p90 = 48 = 07:48 ✓
    safe = _opt(0, 40.0)
    got = latest_departure_for_deadline([safe], deadline)
    assert got is not None
    assert got.depart_at == safe.depart_at


def test_deadline_returns_latest_that_still_arrives() -> None:
    """آخر خروج يضمن الوصول بـp90."""
    deadline = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

    # p90 = 1.2 × المدة
    a = _opt(0, 30.0)     # 07:00 + 36 = 07:36 ✓
    b = _opt(60, 30.0)    # 08:00 + 36 = 08:36 ✓
    c = _opt(120, 30.0)   # 09:00 + 36 = 09:36 ✗

    got = latest_departure_for_deadline([a, b, c], deadline)
    assert got is not None
    assert got.depart_at == b.depart_at


def test_deadline_none_when_impossible() -> None:
    """مستحيل ⇒ لا ندّعي إمكانية."""
    deadline = datetime(2026, 11, 26, 7, 1, tzinfo=UTC)
    assert latest_departure_for_deadline([_opt(0, 60.0)], deadline) is None


# ============================================================
# الثقة والهامش
# ============================================================

def test_confidence_bounds() -> None:
    """الثقة دائماً في [0, 1]."""
    for conf in (0.0, 0.25, 0.5, 0.95, 1.0):
        est = RouteEstimate(
            duration_s=1000.0, duration_p90_s=1200.0, confidence=conf
        )
        assert 0.0 <= est.confidence <= 1.0


def test_p90_always_greater_than_p50() -> None:
    """p90 يجب أن يتجاوز p50 دائماً — وإلا فالهامش بلا معنى."""
    est = RouteEstimate(duration_s=1800.0, duration_p90_s=2100.0, confidence=0.7)
    assert est.duration_p90_s > est.duration_s
    assert est.uncertainty_min > 0


def test_minutes_conversion() -> None:
    """التحويل للدقائق صحيح — هذا ما يراه المستخدم."""
    est = RouteEstimate(duration_s=1830.0, duration_p90_s=2196.0, confidence=0.8)
    assert est.minutes == 30.5
    assert est.minutes_p90 == 36.6
    assert est.uncertainty_min == 6.1


# ============================================================
# تقدير المقطع: سلوك الأساس
# ============================================================

def test_segment_estimate_speed_floor() -> None:
    """لا سرعة أقل من 3 كم/س — تجنّب قسمة قريبة من الصفر."""
    est = SegmentEstimate(
        segment_id=1, length_m=100.0, speed_kmh=3.0, duration_s=120.0, basis="freeflow"
    )
    assert est.speed_kmh >= 3.0
    assert est.duration_s > 0


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"✓ {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"✗ {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
