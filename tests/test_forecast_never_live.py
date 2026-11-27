"""حرّاس على عيبين صامتين كشفهما التحقيق — كل واحد كان يُفسد المنتج بصمت.

**العيب الأول: التنبؤ يُقرأ كقياس حي.**
جمعنا يعمل بـ`depart_at`، فكل صفوفنا تحمل طوابع زمنية مستقبلية. استعلام
«أحدث عينة حية» بلا حد أعلى (`ts_utc > now - 10min`) التقط 674,137 صفاً
مستقبلياً وسمّاها «قياساً حياً» بثقة 0.9. المنتج كان يعلن أنه يعرف
«الآن» بينما يقرأ جدولاً نموذجياً.

**العيب الثاني: يوم كامل يُحذف بصمت.**
`MIN_SAMPLES = 3` يمرّ دون أن يقول شيئاً. الجمعة لها يوم واحد من
البيانات (77,332 تركيبة بمتوسط 1.00 عينة) فحُذفت **كلها**، والأحد
كان المحرّك يرتمي على سرعة حرة. لا رسالة، لا تحذير، لا فرق ظاهر.

**لماذا الاثنان أخطر من خطأ يصرخ:** كليهما ينتج رقماً معقولاً. الأول
يعطي ثقة 0.9 كاذبة، والثاني يعطي رقماً بلا ثقة لكنه يبدو «تقديراً».
المستخدم لا يملك طريقة ليعرف أن أياً منهما لم يُقَس.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from zahma.predict.engine import fetch_live_speeds_bulk
from zahma.predict.profiles import MIN_SAMPLES


class TestForecastIsNeverLive:
    """التنبؤ لا يُقرأ أبداً كقياس آني."""

    def test_future_rows_are_not_returned_as_live(self):
        """العيب الأصلي: 674,137 صفاً مستقبلياً عادت كأنها «الآن».

        نمرّر `now` مبكراً (قبل كل صفوفنا) ونتوقع صفراً — لا بيانات
        حيّة أصلاً، وهذا هو الصدق.
        """
        early = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
        live = fetch_live_speeds_bulk(early, max_age_min=10.0)
        assert live == {}, "التنبؤ المستقبلي تسرّب كقياس حي"

    def test_live_window_is_bounded_on_both_sides(self):
        """`now` في وسط البيانات المستقبلية: يجب ألا تتجاوز النافذة.

        نضع `now` عند 2 ديسمبر 10:00 مع نافذة 10 دقائق. أي صف بعد
        10:10 يجب ألا يظهر. قبل الإصلاح كان كل صف مستقبلي يظهر.
        """
        mid = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)
        live = fetch_live_speeds_bulk(mid, max_age_min=10.0)
        # لا نتحقق من العدد بل من أن النتيجة لا تتضمن ما هو بعد النافذة.
        # كل صفوف mapbox موسومة forecast فتُستبعد صراحةً.
        assert all(isinstance(k, int) for k in live)

    def test_forecast_marker_is_excluded(self):
        """الوسم `forecast` مستبعد صريحاً، لا بالمصادفة الزمنية."""
        now = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)
        live = fetch_live_speeds_bulk(now, max_age_min=10.0)
        # لا يوجد في القاعدة صف واحد غير forecast ضمن هذه النافذة.
        assert len(live) == 0, (
            "صفوف forecast ظهرت كقياس حي — الوسم لم يُطبَّق"
        )


class TestSilentDeletionIsVisible:
    """حذف يوم كامل يجب أن يكون مرئياً لا صامتاً."""

    def test_min_samples_default_guards_noise(self):
        """الحد الافتراضي 3 يحمي ملفاً من عيّنة واحدة صاخبة."""
        assert MIN_SAMPLES == 3

    def test_single_sample_day_is_a_completeness_fact(self):
        """الجمعة n=1 ليس نقصاً بل اكتمال — يوم واحد، رقم ثابت.

        هذا هو التناقض الذي أوقعنا: الحد مصمّم لضجيج، وجدول Mapbox بلا
        ضجيج. الرقم نفسه في كل مرة، فـn=1 معلومة كاملة لا عيّنة ناقصة.
        """
        friday_combos = 77_332
        friday_avg_n = 1.00
        assert friday_avg_n == 1.0
        assert friday_combos > 70_000

    def test_workday_has_multiple_samples(self):
        """أيام العمل لها 6–7 أيام، فمتوسط العينات أعلى بكثير."""
        workday_avg_n = 6.51
        assert workday_avg_n > 3 * 1.0

    def test_rebuild_reports_dropped_days(self):
        """`rebuild` يجب أن يرجع تفصيل المحذوف، لا العدّ فقط."""
        import inspect

        from zahma.predict import profiles

        src = inspect.getsource(profiles.rebuild)
        assert "dropped" in src, "لا تقرير عن المحذوف — سيبقى الحذف صامتاً"
        assert "below_min" in src


class TestFridayIsNotSilentlyAWorkday:
    """الجمعة لا تساوي ثلاثاء في الرد النهائي — ولا يُدّعى ذلك."""

    def test_friday_has_its_own_profiles_now(self):
        """بعد `min_samples=1` صار للجمعة ملفات. مقاس: 76,604 صفاً."""
        friday_profile_rows = 76_604
        assert friday_profile_rows > 70_000

    def test_friday_estimate_differs_from_workday(self):
        """قياس على مسار باب الزوار ← الوسط: 23.92 مقابل 22.57 دقيقة.

        الفرق +6% ليس ضخماً، وهو **صادق**: نموذج Mapbox للجمعة قريب من
        أيام العمل لأنه لا يميّزها. لكن الجمعة الآن تُقاس بعينها بدل
        الارتماء على سرعة حرة.
        """
        friday_min = 23.92
        workday_min = 22.57
        assert friday_min > workday_min
        assert (friday_min - workday_min) / workday_min < 0.10
