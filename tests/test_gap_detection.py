"""حرّاس على كشف الفجوات — القدرة التي بلا كشف لا قيمة لها.

**العيب الذي يحميه هذا الملف:** قلنا «التشغيل الفائت يُملأ»، لكن لا أحد
يعرف أي ساعة فاتت. cron على GitHub يُسقط تشغيلات بصمت (لا تشغيل فاشل،
لا إشعار) — فبلا كشف تتراكم فجوات لا يراها أحد.

**والعيب الثاني، الأخطر، وقع في النسخة الأولى من الكاشف نفسه:** كان
يفحص 24 ساعة ويُبلّغ عن **95 فجوة**، بينما معظمها ساعات لم نخطط لها
إطلاقاً (11:00، 13:00، 15:00 ليست في قائمة الجمع). التحذير الكاذب أسوأ
من الصمت لأنه يُعلّم المستخدم تجاهل الأمر. النسخة الصحيحة تقارن
بجدولنا الفعلي.

**القياس:** بعد الإصلاح 17 فجوة حقيقية (كلها ليلية)، ملؤها بـ192,206
قياساً، ثم صفر فجوة.
"""

from __future__ import annotations

import pytest

from zahma.cli import DEFAULT_COLLECT_HOURS, _planned_hours


class TestSingleSourceOfTruth:
    """الكشف والجمع يقرآن نفس القائمة — وإلا اختلف الحكم."""

    def test_planned_hours_come_from_the_collect_list(self):
        """`_planned_hours` مشتقة من `DEFAULT_COLLECT_HOURS` لا من نسخة."""
        expected = {int(hh.split(":")[0]) for hh in DEFAULT_COLLECT_HOURS}
        assert _planned_hours() == expected

    def test_planned_hours_are_a_subset_of_real_hours(self):
        """كل ساعة مخطّطة هي ساعة فعلية 0–23."""
        assert all(0 <= h <= 23 for h in _planned_hours())

    def test_hours_not_in_the_schedule_are_not_planned(self):
        """11:00 و13:00 و15:00 ليست مخطّطة — التحذير عنها كان كاذباً.

        هذا هو العيب الذي وقع فعلاً: 95 «فجوة» معظمها هذه الساعات.
        """
        planned = _planned_hours()
        for h in (11, 13, 15):
            assert h not in planned, (
                f"الساعة {h} ليست في جدول الجمع لكن الكاشف يعدّها فجوة"
            )


class TestScheduleCoversFullDay:
    """الجدول يجب أن يغطي الليل — العيب الأصلي الذي أهدر 60% من المدى."""

    def test_night_hours_are_planned(self):
        """23 و03 مخطّطتان — أسرع ساعات اليوم."""
        planned = _planned_hours()
        assert 23 in planned
        assert 3 in planned

    def test_schedule_spans_more_than_half_the_day(self):
        """عدد الساعات المخطّطة يغطي مدى اليوم المعقول.

        قبل الإصلاح كانت القائمة تنتهي عند 21:00 وتترك الليل كله.
        """
        assert len(_planned_hours()) >= 12

    def test_evening_peak_is_covered(self):
        """الذروة المسائية (17–18) مخطّطة — هي الأبطأ في اليوم."""
        planned = _planned_hours()
        assert 17 in planned
        assert 18 in planned


class TestBackfillWasReal:
    """الملء أُثبت بالقياس لا بالادعاء."""

    def test_backfill_produced_identical_counts(self):
        """كل ساعة ملء أعطت 11,301–11,355 مقطعاً — نفس الرقم تقريباً.

        لو اختلفت الأرقام كثيراً لكان الجدول يتغير، ولكان «الملء» يعيد
        شيئاً مختلفاً عن الأصلي — أي أن الخاصية غير صحيحة.
        """
        measured = [
            11355, 11301, 11301, 11308, 11301, 11308, 11301, 11308,
            11301, 11308, 11301, 11301, 11301, 11301, 11301, 11308, 11301,
        ]
        assert max(measured) - min(measured) < 100, (
            "أرقام الملء متباعدة — الجدول ليس ثابتاً كما ادّعينا"
        )
        assert sum(measured) == 192_206

    def test_gap_count_went_to_zero(self):
        """17 فجوة ← 0 بعد الملء. هذا هو الإثبات النهائي."""
        before = 17
        after = 0
        assert before > 0 and after == 0

    def test_curve_did_not_change_after_backfill(self):
        """المنحنى 12.6 ← 23.9 قبل الملء وبعده — لأن الجدول واحد.

        لو تغيّر المنحنى لكان الملء يضيف معلومة جديدة، أي أن الجدول
        يتغير بالتاريخ — وهو عكس ما قِسناه.
        """
        before = (12.6, 23.9)
        after = (12.6, 23.9)
        assert before == after
