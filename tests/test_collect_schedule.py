"""حرّاس على جدول الجمع — لأن الخطأ في الجدول لا يُرى في أي تقرير.

**العيب الذي يحميه هذا الملف:** الجمع كان يقف عند 21:00. لا رسالة، لا
تحذير، لا فرق ظاهر — فقط منحنى يبدأ من 14.9 دقيقة بدل 12.6، ولا أحد
يعرف أن أسرع ساعات اليوم لم تُقس قط.

القياس المباشر من API أثبت الحجم: 04:00 = 68.2 كم/س مقابل 17:00 =
42.5 — **60% فرق**. أي أن الجدول القديم كان يجهل أغلب مدى اليوم.

**والخطأ المقابل يجب ألا نقع فيه:** «نجمع كل ساعة ليلاً» يعني 7× الحصة
مقابل صفر معلومة إضافية، لأن المنحنى مسطّح (64 → 68 → 66، مدى 4.2).
الحل ليس توقّفاً ولا إسرافاً بل **وتيرة تعترف بأن الليل مسطّح**.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from zahma.collect.runner import (
    NIGHT_END_HOUR,
    NIGHT_START_HOUR,
    is_night,
    is_peak,
)
from zahma.config import get_settings


class TestNightIsCollectedNotSkipped:
    """الليل يُجمع. التوقف عنده خطأ مختلف عن التبطيء."""

    def test_night_has_its_own_interval(self):
        """ليل ≠ نهار ≠ ذروة. ثلاث حالات، لا حالتان."""
        s = get_settings()
        assert s.scan_interval_night_min > s.scan_interval_offpeak_min
        assert s.scan_interval_night_min > s.scan_interval_peak_min

    def test_night_interval_is_not_infinite(self):
        """التبطيء ليس توقفاً: الوتيرة محدودة، فلا فجوة بلا نهاية."""
        s = get_settings()
        assert s.scan_interval_night_min <= 240, (
            "فاصل ليلي أطول من 4 ساعات يعني فجوة تُخفي تغيّراً حقيقياً "
            "(رمضان، مواسم، أعياد)"
        )

    def test_night_interval_covers_the_flat_curve(self):
        """المنحنى مسطّح 6 ساعات؛ فاصل 3 ساعات يمسكه مرتين."""
        s = get_settings()
        flat_span_min = (NIGHT_START_HOUR + (24 - NIGHT_END_HOUR)) * 60
        assert s.scan_interval_night_min * 2 <= flat_span_min


class TestIsNight:
    """حدود الليل — لأن خطأً بساعة يخلط الذروة بالليل."""

    @pytest.mark.parametrize("hour", [23, 0, 1, 2, 3, 4])
    def test_deep_night_hours(self, hour):
        """23:00–04:59 ليل."""
        # محلي = UTC+1، فالساعة المحلية H تعني UTC = H-1 (قد ترجع لليوم السابق).
        t = datetime(2026, 12, 2, (hour - 1) % 24, 30, tzinfo=UTC)
        assert is_night(t) is True

    @pytest.mark.parametrize("hour", [5, 6, 8, 12, 17, 20, 22])
    def test_day_hours_are_not_night(self, hour):
        """05:00–22:59 نهار. 22:00 قريب من الليل لكنه ليس مسطّحاً بعد."""
        t = datetime(2026, 12, 2, hour - 1, 30, tzinfo=UTC)
        assert is_night(t) is False

    def test_night_and_peak_never_overlap(self):
        """الذروة والليل لا يجتمعان — وإلا ضاع أحد الفاصلين."""
        for h in range(24):
            t = datetime(2026, 12, 2, (h - 1) % 24, 30, tzinfo=UTC)
            if is_night(t):
                assert not is_peak(t), f"الساعة {h} ليل وذروة معاً"


class TestPeakIsStillCorrect:
    """الذروة لم تتغير — نحميها من التعديل بالخطأ."""

    @pytest.mark.parametrize("hour", [7, 8, 17, 18])
    def test_peak_hours(self, hour):
        t = datetime(2026, 12, 2, hour - 1, 30, tzinfo=UTC)  # الأربعاء
        assert is_peak(t) is True

    @pytest.mark.parametrize("hour", [11, 13, 15, 21])
    def test_offpeak_hours(self, hour):
        t = datetime(2026, 12, 2, hour - 1, 30, tzinfo=UTC)
        assert is_peak(t) is False


class TestCollectHoursCoverFullDay:
    """قائمة الساعات الافتراضية يجب أن تغطي 24 ساعة."""

    def test_default_hours_include_night(self):
        """القائمة الافتراضية تحوي ساعات ليلية.

        قبل الإصلاح توقفت عند 21:00، فلم تُقس أسرع ساعات اليوم إطلاقاً.

        **نفحص المعنى لا النص:** كان الحارس يطلب `"23:59"` تحديداً. بعد
        إصلاح الشرائح (كل ساعة تُجمع على 00/15/30/45) صار التوقيت
        `"23:00"` — نفس الغرض (آخر ساعة قبل منتصف الليل) بصياغة تغطي
        الشريحة كاملة. تثبيت النص يجعل الحارس يعارض الإصلاح بلا سبب.
        """
        from zahma.cli import DEFAULT_COLLECT_HOURS

        hours = [int(h.split(":")[0]) for h in DEFAULT_COLLECT_HOURS]
        assert any(h >= 22 for h in hours), "لا ساعة ليلية متأخرة"
        assert any(h <= 4 for h in hours), "لا ساعة فجرية — أسرع ساعات اليوم"

    def test_default_hours_do_not_waste_quota_on_flat_night(self):
        """ساعتان ليلاً، لا سبع. المنحنى مسطّح فلا معلومة إضافية."""
        from zahma.cli import DEFAULT_COLLECT_HOURS

        night_hours = [
            h for h in DEFAULT_COLLECT_HOURS if int(h.split(":")[0]) >= 23
            or int(h.split(":")[0]) < 5
        ]
        assert len(night_hours) <= 3, (
            f"{len(night_hours)} ساعة ليلية — المنحنى مسطّح (مدى 4.2 كم/س)، "
            "فكل ساعة إضافية حصة بلا معلومة"
        )

    def test_collect_real_uses_the_shared_constant(self):
        """`collect-real` يقرأ الثابت، لا نسخة محلية منه.

        لو نسخ القائمة داخلياً لاختلفت عن قائمة الكشف، وكشفنا فجوات
        كاذبة — وهذا وقع فعلاً (95 «فجوة» معظمها ساعات غير مخطّطة).
        """
        import inspect

        from zahma import cli

        src = inspect.getsource(cli.collect_real)
        assert "DEFAULT_COLLECT_HOURS" in src, (
            "collect-real لا يستخدم القائمة المشتركة — ستنشأ نسخة ثانية"
        )
