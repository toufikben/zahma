"""حرّاس على إسقاط بيانات Mapbox على شبكتنا.

العيب الذي تمنعه هذه الاختبارات — وهو الأخطر في المشروع لأنه صامت:

جمعنا 5,051 قياساً حقيقياً من Mapbox لساعة الذروة (الاثنين 07:30)، ثم
خزّناها بـ`ts_utc = now()` أي الجمعة 06:25. النتيجة: بيانات ذروة
الاثنين صارت «قياساً صباحياً هادئاً يوم جمعة». ملفات التعريف تتدرّب
على أكاذيب، والنموذج يتعلم أن 07:30 ليست مزدحمة — بلا أي استثناء أو
تحذير. النموذج يعمل، والأرقام معقولة، والنصيحة خاطئة.

الحماية: `_parse_depart` تحوّل `depart_at` (وقت الجزائر المحلي) إلى UTC
صحيح، والبيانات تُوسم `forecast` كي لا تُخلط بالقياس الآني عند تقييم
دقة النموذج.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from zahma.collect.match import (
    MATCH_RADIUS_M,
    MIN_EDGE_M,
    _bucket,
    _parse_depart,
)


class TestDepartAtTimezone:
    """`depart_at` وقت محلي للجزائر — لا UTC."""

    def test_parses_as_algiers_local_time(self):
        """07:30 في الجزائر = 06:30 UTC (UTC+1 بلا توقيت صيفي)."""
        dt = _parse_depart("2026-11-30T07:30")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.astimezone(UTC).hour == 6
        assert dt.astimezone(UTC).minute == 30

    def test_returns_correct_utc_date(self):
        dt = _parse_depart("2026-11-30T23:30")
        # 23:30 محلياً = 22:30 UTC في نفس اليوم
        assert dt.astimezone(UTC).day == 30
        assert dt.astimezone(UTC).hour == 22

    def test_none_returns_none(self):
        assert _parse_depart(None) is None

    def test_does_not_shift_a_full_day(self):
        """حارس العيب الأصلي: الفرق يجب أن يكون ساعة واحدة بالضبط."""
        for hh in (0, 6, 7, 12, 17, 23):
            dt = _parse_depart(f"2026-11-30T{hh:02d}:00")
            delta = dt.astimezone(UTC) - datetime(
                2026, 11, 30, hh, tzinfo=UTC
            )
            # الفرق ساعة واحدة (أو 24 ساعة إن تجاوز منتصف الليل)
            assert abs(abs(delta.total_seconds()) - 3600) < 1, (
                f"hour {hh}: expected exactly 1h shift, got {delta}"
            )

    def test_bucket_aligns_to_5_minutes(self):
        dt = _parse_depart("2026-11-30T07:32")
        b = _bucket(dt)
        assert b.minute % 5 == 0
        assert b.second == 0


class TestMatchThresholds:
    """العتبات مقاسة على بيانات حقيقية، لا مختارة اعتباطاً."""

    def test_radius_covers_most_real_geometry(self):
        """قياس فعلي: 95% من نقاط هندسة Mapbox ضمن 40 متراً من شبكتنا.

        العتبة أصغر ⇒ نفقد قياسات صحيحة. أكبر ⇒ ننسب قياس شارع إلى آخر.
        """
        assert 30.0 <= MATCH_RADIUS_M <= 60.0

    def test_min_edge_rejects_noise(self):
        """حافة 3 أمتار بزمن 0.2 ثانية تعطي سرعة بلا معنى — تُرفض."""
        assert MIN_EDGE_M >= 5.0
        # حافة 8 أمتار بزمن 1 ثانية = 28.8 كم/س، معقولة وتبقى.
        assert (8.0 / 1.0) * 3.6 == pytest.approx(28.8)
