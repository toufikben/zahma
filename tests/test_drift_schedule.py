"""حرّاس على الفحص المجدول — أن يقول الحقيقة لا أن يدّعي المراقبة.

**المشكلة التي يحلّها هذا الملف:** أسهل شيء في العالم أن نضيف
`.github/workflows/collect.yml` بـ`cron` كل 30 دقيقة ونقول «جمع مستمر
يعمل». لكن القياس يقول شيئاً آخر:

- الجدول **ثابت تماماً**: 11,570 مقطع-قياس، 100.000% مطابقة.
- النداء الحي يعيد الجدول حرفياً: نفس بصمة السرعات على 634 و328 حافة.
- `depart_at` لماضٍ يعيد نفس الرقم بعد سنة: 1575.8 ثانية في أربعة تواريخ.

أي أن الجمع الدوري **لا يجمع شيئاً**. وإضافته بلا سبب تدّعي قيمة غير
موجودة، وتستهلك حصة، وتُشغل انتباهاً بلا مقابل.

**والقيمة الوحيدة الباقية** هي كشف تغيّر الجدول عبر الزمن — وهذا يحتاج
قاعدة دائمة، وCI لا يملكها (service container يموت مع الوظيفة). لذلك
الـworkflow **يتخطّى نفسه بصدق** ويقول السبب، بدل أن يبدو ناجحاً وهو لا
يفحص شيئاً.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "drift.yml"


class TestWorkflowIsHonest:
    """الـworkflow لا يدّعي ما لا يفعله."""

    def test_workflow_exists(self):
        assert WORKFLOW.exists(), "لا فحص انحراف مجدول إطلاقاً"

    def test_it_is_not_a_collection_workflow(self):
        """لا يستدعي `collect-real` — الجمع لا يضيف شيئاً، والقياس يثبته."""
        src = WORKFLOW.read_text(encoding="utf-8")
        assert "collect-real" not in src.replace("#", "\n#"), (
            "الـworkflow يجمع — لكن الجدول ثابت 100%، فالجمع بلا قيمة"
        )

    def test_it_checks_prerequisites_and_skips(self):
        """يتحقّق من الأسرار ويتخطّى صراحة — لا فشل صامت ولا نجاح كاذب."""
        src = WORKFLOW.read_text(encoding="utf-8")
        assert "missing" in src, "لا تحقّق من الأسرار — سيفشل بغموض"
        assert "GITHUB_STEP_SUMMARY" in src, (
            "لا يشرح سبب التخطّي — سيبدو معطلاً بلا سبب"
        )
        assert "ready=false" in src, "لا بوابة تخطّي"

    def test_it_verifies_reference_rows_exist(self):
        """يتأكّد أن هناك صفوفاً مرجعية قبل المقارنة.

        بلا ذلك، قاعدة فارغة تعطي «صفر انحراف» — وهو نجاح كاذب: لم نقارن
        شيئاً. الفحص يجب أن يفشل صراحة حين لا يوجد ما يقارنه.
        """
        src = WORKFLOW.read_text(encoding="utf-8")
        assert "reference rows" in src
        assert "raise SystemExit" in src or "exit 1" in src, (
            "قاعدة فارغة ستعطي صفر انحراف — نجاح كاذب"
        )

    def test_it_uses_auto_slots_not_guessed_dates(self):
        """يستخدم `--auto` لا تواريخ مخمّنة.

        التخمين ينتج خانات غير مخزَّنة، فيفشل كل فحص بـ«لا صفوف» — فحص
        يعمل ولا يقيس شيئاً، وهو أسوأ من عدمه لأنه يوهم بالمراقبة.
        """
        src = WORKFLOW.read_text(encoding="utf-8")
        assert "--auto" in src, "لا اختيار تلقائي — سيقارن خانات غير موجودة"


class TestAutoSlotSelection:
    """الاختيار التلقائي يقترن (زوج، خانة) ولا يضربهما تقاطعياً."""

    def test_recent_slots_returns_pairs_not_cross_product(self):
        """الدالة تُرجع أزواجاً مقترنة — لأن خانة الزوج 3 ليست خانة الزوج 7.

        لو أخذنا قائمة أزواج وقائمة خانات وضربناهما، لقارنّا كل زوج بكل
        خانة — أي 5 من 6 مقارنات بلا صفوف مخزَّنة، تفشل بصمت.
        """
        from zahma.collect import drift

        import inspect

        src = inspect.getsource(drift.recent_slots)
        assert "pair_id" in src
        assert "GROUP BY 1, 2" in src, (
            "لا تجميع على (الزوج، الخانة) معاً — سيعطي تقاطعاً خاطئاً"
        )

    def test_recent_slots_requires_meaningful_sample(self):
        """لا يقبل خانة بعشرات الصفوف — المقارنة تحتاج عيّنة ذات معنى."""
        from zahma.collect import drift

        import inspect

        src = inspect.getsource(drift.recent_slots)
        assert "HAVING" in src, "لا حدّ أدنى للعينة — خانة بصفين تعطي رقماً بلا معنى"


class TestDriftComparisonIsPerPair:
    """المقارنة على قياس الزوج، لا على الصف المجمَّع."""

    def test_verify_slot_reads_the_detail_table(self):
        """يقرأ `segment_pair_samples` — لأن `samples` مجمَّع.

        هذا هو الإصلاح الذي غيّر الاستنتاج: المقارنة على صف مجمَّع أعطت
        «7.4% انحرافاً» كاذباً. المقارنة على قياس الزوج نفسه أعطت صفراً.
        """
        from zahma.collect import drift

        import inspect

        src = inspect.getsource(drift.verify_slot)
        assert "segment_pair_samples" in src, (
            "يقرأ `samples` المجمَّع — سيعطي انحرافاً كاذباً"
        )

    def test_tolerance_is_below_travel_significance(self):
        """العتبة 0.5 كم/س — أصغر من أي فرق يغيّر قرار سفر."""
        from zahma.collect import drift

        import inspect

        sig = inspect.signature(drift.verify_slot)
        tol = sig.parameters["tolerance_kmh"].default
        assert 0 < tol <= 1.0, f"العتبة {tol} — إمّا صامتة عن تغيّر حقيقي أو صاخبة"

    def test_verification_is_read_only_by_default(self):
        """التحقق لا يكتب — وإلا صار هو نفسه مصدر الانحراف الذي يقيسه."""
        from zahma.collect import drift

        import inspect

        sig = inspect.signature(drift.verify_slot)
        assert sig.parameters["store_rows"].default is False
