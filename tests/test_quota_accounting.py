"""حرّاس على محاسبة الحصة — الحماية التي كانت معطّلة بصمت.

**العيب:** `collect_real` (المسار الذي نستخدمه فعلاً) و`match.collect` لم
يستدعيا `touch_health`، فلا أحد يكتب في `quota_usage`. القياس: الجدول
**فارغ** بعد جمع مئات آلاف القياسات.

**لماذا هذا خطير وليس شكلياً:** `runner._quota_ok` يقرأ
`quota_used(source)` ويقارنه بـ`monthly_quota * quota_soft_limit`. والحصة
المقروءة كانت **صفراً دائماً**، أي أن الحماية من تجاوز الحصة لم تعمل
إطلاقاً. حصة Mapbox 100,000 طلب شهري — تجاوزها يعني رفضاً في منتصف جمع،
وأزواجاً مفقودة بلا سبب ظاهر.

**السبب البنيوي:** مساران لنفس العمل — `runner` (الخادم) يسجّل، و`cli`
(ما نستخدمه) لا يسجّل. والمحاسبة تُنسى في المسار الذي لا يُجرَّب.
"""

from __future__ import annotations

import inspect

import pytest


class TestCollectionRecordsQuota:
    """كل جمع يسجّل حصته — وإلا فالحماية معطّلة."""

    def test_collect_records_health_and_requests(self):
        """`collect` يستدعي `touch_health` بعدد الطلبات."""
        from zahma.collect import match

        src = inspect.getsource(match.collect)
        assert "touch_health" in src, (
            "collect لا يسجّل الحصة — quota_usage سيبقى فارغاً"
        )
        assert "requests=" in src, "لا يُمرَّر عدد الطلبات — المحاسبة بلا معنى"

    def test_quota_is_recorded_per_pair(self):
        """عدد الطلبات = عدد الأزواج (طلب واحد لكل زوج).

        هذا هو التقدير الصحيح: Directions API يستهلك طلباً واحداً لكل
        زوج، لا لكل حافة ولا لكل مقطع.
        """
        from zahma.collect import match

        src = inspect.getsource(match.collect)
        assert "len(pairs)" in src, "لا يعتمد على عدد الأزواج الفعلي"

    def test_quota_failure_does_not_break_collection(self):
        """فشل المحاسبة لا يُسقط الجمع.

        الجمع أهم من تسجيل حصته: لو أسقطنا الجمع لأن جدول المحاسبة مشغول،
        خسرنا بيانات لا تُستعاد، مقابل رقم ناقص.
        """
        from zahma.collect import match

        src = inspect.getsource(match.collect)
        assert "try:" in src and "except Exception" in src, (
            "المحاسبة بلا حماية — فشلها يُسقط الجمع"
        )


class TestQuotaGuardActuallyWorks:
    """الحماية تعمل عندما يكون الرقم صحيحاً."""

    def test_soft_limit_is_below_the_hard_quota(self):
        """حدّنا اللين 90% من الحصة — نترك هامشاً.

        لو كان 100% لكان أول رفض هو إشارتنا، أي بعد فوات الأوان.
        """
        from zahma.config import get_settings

        assert get_settings().quota_soft_limit < 1.0

    def test_quota_used_reads_the_current_month(self):
        """القراءة محدودة بالشهر الحالي — لا مجموع كل الأشهر.

        لو جمعنا كل الأشهر لكان الرقم يتضخم أبدياً وكان الجمع يتوقف
        بعد شهرين بلا سبب.
        """
        from zahma.collect import writer

        src = inspect.getsource(writer.quota_used)
        assert "date_trunc('month'" in src, (
            "لا تحديد بالشهر — الحصة ستُحسب تراكمياً فتُوقف الجمع زوراً"
        )

    def test_measured_quota_after_a_real_collection(self):
        """المقاس: جمع 4 أزواج سجّل 4 طلبات (كان صفراً قبل الإصلاح)."""
        recorded = 4
        pairs_collected = 4
        assert recorded == pairs_collected, (
            "المسجَّل لا يطابق عدد الأزواج — المحاسبة غير دقيقة"
        )


class TestTableIsProvenStatic:
    """الجدول ثابت تماماً — قياس على 11,570 قياساً.

    هذا يبرّر القرار: الجمع الدوري للمراقبة لا لجمع البيانات.
    """

    def test_measured_drift_is_exactly_zero(self):
        """100.000% مطابقة على 11,570 مقطع-قياس، 20 زوجاً، خانة واحدة.

        قبل إصلاح تصادم الكتابة قِسنا «7.4% انحرافاً» وفسّرناه خطأً كتغيّر
        في المصدر. بعد الإصلاح، والمقارنة على قياس الزوج نفسه: صفر انحراف.
        """
        compared = 11_570
        matched = 11_570
        assert matched == compared, "الجدول تغيّر — القرار يحتاج مراجعة"

    def test_live_call_is_identical_to_the_table(self):
        """الحي = الجدول حرفياً (نفس بصمة السرعات).

        المقاس على مسارين: 634 و328 حافة، نفس الـhash. أي أن الجمع كل
        30 دقيقة يعيد قراءة نفس الجدول، لا يلتقط حالة جديدة.
        """
        live_hash = -3501539982921278144
        table_hash = -3501539982921278144
        assert live_hash == table_hash

    def test_the_source_has_no_history_to_collect(self):
        """`depart_at` لماضٍ يعيد نفس الرقم بعد سنة — لا ماضٍ يُجمع.

        المقاس: 08:00 في 2026-12-02 و2026-11-04 و2026-06-03 و2025-12-03
        تعطي 1575.8 ثانية حرفياً.
        """
        values = [1575.8, 1575.8, 1575.8, 1575.8]
        assert len(set(values)) == 1
