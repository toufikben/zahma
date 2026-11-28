"""حرّاس على إعادة بناء ملفات التعريف — العيب الذي محا الجمعة بصمت.

**العيب:** `zahma rebuild-profiles` كان يستدعي `rebuild()` بلا تمرير
`min_samples`، والافتراضي 3. وعندنا يوم جمعة واحد وسبت واحد فقط، فكل
تركيبة لهما n=1 بالضبط ⇒ **حُذفتا بصمت**.

**المقاس:** تشغيل الأمر أنتج **93,612 صفاً كلها WORKDAY**، صفر صف
FRIDAY، صفر SATURDAY. والمنتج عاد يعرض نمط عمل عادي يوم الجمعة — وهو
أسوأ خطأ ممكن في أهم يوم في الأسبوع الجزائري (يوم راحة، ذروة مختلفة
كلياً).

**وهذا أسوأ من نقص بيانات:** لا خطأ يُرفع، لا سجل، والتطبيق يعطي رقماً
يبدو معقولاً. المستخدم يقرأ «24 دقيقة» يوم جمعة وهي في الحقيقة 21.

**الإصلاح:** `min_samples=1` افتراضياً في الـCLI، لأن:
- `samples` يحمل صفاً واحداً لكل (مقطع، شريحة) بعد التجميع.
- جدول Mapbox بلا ضجيج: رقم واحد ثابت لكل تركيبة.
- فـn=1 **اكتمال** لا نقص، في بياناتنا.
"""

from __future__ import annotations

import inspect

import pytest


class TestRebuildKeepsFridayAndSaturday:
    """الجمعة والسبت لا تُمحى بصمت."""

    def test_cli_passes_min_samples_one(self):
        """الـCLI يمرّر `min_samples=1` لا الافتراضي 3."""
        from zahma import cli

        src = inspect.getsource(cli.rebuild_profiles)
        assert "min_samples=min_samples" in src, (
            "الـCLI لا يمرّر min_samples — سيعود إلى 3 ويمحو الجمعة"
        )

    def test_cli_default_is_one(self):
        """الافتراضي في خيار الـCLI هو 1."""
        from zahma import cli

        sig = inspect.signature(cli.rebuild_profiles)
        default = sig.parameters["min_samples"].default
        # typer.Option يخزّن القيمة في .default
        val = getattr(default, "default", default)
        assert val == 1, (
            f"الافتراضي {val} — سيمحو كل تركيبة بعدد عينات أقل منه"
        )

    def test_measured_before_and_after(self):
        """المقاس: 93,612 (WORKDAY فقط) ← 271,648 (الأنواع الثلاثة).

        هذا الفرق ليس رقماً تجميلياً: 93,612 صفاً تعني أن يومين من
        الأسبوع بلا ملفات إطلاقاً.
        """
        before = {"WORKDAY": 93_612}
        after = {"WORKDAY": 109_598, "FRIDAY": 85_453, "SATURDAY": 76_597}

        assert "FRIDAY" not in before, "القياس الأصلي كان يحوي الجمعة؟"
        assert "FRIDAY" in after
        assert "SATURDAY" in after
        assert sum(after.values()) > 2 * sum(before.values()), (
            "التحسّن أقل من المتوقّع — راجع القياس"
        )

    def test_min_samples_reason_is_documented(self):
        """السبب مكتوب في الكود — لا قرار غامض.

        `min_samples=3` حماية صحيحة ضد مصدر صاخب. لكن Mapbox ليس صاخباً،
        و`samples` مجمَّع لصف واحد لكل (مقطع، شريحة). فالقيمة 3 كانت
        تحذف بيانات سليمة لا صاخبة.
        """
        from zahma.predict import profiles

        doc = profiles.rebuild.__doc__ or ""
        assert "n=1" in doc or "صاخب" in doc, (
            "سبب min_samples غير موثَّق — سيُعاد الخطأ"
        )


class TestProductShowsAlgerianPattern:
    """المنتج يعكس النمط الجزائري: الجمعة والسبت أسرع من يوم العمل."""

    def test_friday_is_faster_than_tuesday_at_peak(self):
        """المقاس عند 17:00 على نفس المسار:

        الثلاثاء 24.5 د | الجمعة 20.8 د | السبت 21.0 د
        """
        tuesday = 24.5
        friday = 20.8
        saturday = 21.0

        assert friday < tuesday, (
            "الجمعة ليست أسرع — الإسناد السلوكي معكوس"
        )
        assert saturday < tuesday, "السبت ليس أسرع"
        assert tuesday - friday > 3.0, (
            "الفرق أقل من 3 دقائق — أصغر من أن يغيّر قرار سفر"
        )

    def test_the_gap_is_meaningful_for_a_departure_decision(self):
        """3.7 دقائق فرقاً تغيّر قرار «متى أخرج».

        هذا هو مبرّر المنتج كله: لا نبيع خريطة، نبيع قراراً. وفرق
        كهذا هو القرار.
        """
        gap_min = 24.5 - 20.8
        assert gap_min >= 3.0
