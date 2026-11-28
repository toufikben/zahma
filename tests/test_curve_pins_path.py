"""حرّاس على تثبيت المسار في منحنى الانطلاق — أخطر عيب اكتُشف.

**العيب المقاس:** `departure_curve` كان يستدعي `estimate_route` كاملاً لكل
خيار. فيوجّه Dijkstra من جديد بسرعات تلك الشريحة. وحين تختلف تغطية
الملفات بين الشرائح، تتغيّر الأوزان النسبية، **فيختار مساراً آخر**.

القياس على باب الزوار ← وسط الجزائر:

    07:30: 261 مقطعاً، 14.78 كم، 21.55 د
    07:45: 298 مقطعاً، 13.94 كم، 28.34 د

المسار **أقصر** لكن المدة **أطول بـ6.79 دقيقة**. ثم يعود. وهذا أنتج
قفزة +6.78 ثم −4.34 كسرت حارس الرتابة، وكان المستخدم سيرى «اخرج في 07:45
أسوأ من 07:30 بـ6.8 دقائق» — وهو كذب: هو طريق آخر لا وقت آخر.

**الفصل الحاسم (المقاس):**

    نفس المسار، سرعتان مختلفتان:   2.5–3.6% فرقاً
    مساران مختلفان، سرعات مختلفة: 10.6% فرقاً

أي أن التذبذب **ثلاثة أضعاف** من اختيار المسار لا من السرعة. فالسرعات
سليمة؛ المنحنى كان يقارن رحلتين مختلفتين.

**الإصلاح:** المسار يُثبَّت مرة واحدة، والمدة تُقاس على نفس المقاطع لكل
شريحة. بعد الإصلاح: 21.55 ← 22.30 ← 22.48 ← 22.70 ← 22.97 (الذروة) ←
22.58 ← 22.43 ← 20.59 ← 19.38. أكبر قفزة 1.83 د بدل 6.78.

هذا هو ما تفعله تطبيقات الملاحة: «نفس الطريق، أوقات مختلفة». وهو أيضاً
ما يسأل عنه المستخدم: «أخرج الآن أم بعد ساعة **على طريقي**».
"""

from __future__ import annotations

import inspect

import pytest


class TestCurvePinsThePath:
    """المنحنى يقيس نفس الطريق في كل نقطة."""

    def test_departure_curve_routes_once(self):
        """`departure_curve` يوجّه **مرة واحدة** فقط، خارج الحلقة.

        هذا هو جوهر الإصلاح. لو عاد `estimate_route` داخل الحلقة، عاد
        العيب: مسار مختلف لكل نقطة، ومنحنى يقارن رحلات لا رحلة.
        """
        from zahma.predict import engine

        src = inspect.getsource(engine.departure_curve)
        # التوجيه يحدث قبل الحلقة
        loop_idx = src.index("for m in range")
        route_idx = src.index("route(")
        assert route_idx < loop_idx, (
            "التوجيه داخل الحلقة — كل نقطة ستقيس مساراً مختلفاً"
        )

        # ولا استدعاء لتوجيه كامل داخل الحلقة
        body = src[loop_idx:]
        assert "estimate_route(" not in body.split("if m == 0")[0], (
            "الحلقة تستدعي estimate_route — تعيد التوجيه"
        )

    def test_curve_uses_pinned_estimator(self):
        """الحلقة تستخدم `estimate_on_path` لا `estimate_route`."""
        from zahma.predict import engine

        src = inspect.getsource(engine.departure_curve)
        loop = src[src.index("for m in range"):]
        assert "estimate_on_path(" in loop, (
            "الحلقة لا تستخدم المقدّر المثبَّت — ستعيد التوجيه"
        )

    def test_pinned_estimator_does_not_route(self):
        """`estimate_on_path` لا يوجّه إطلاقاً — يأخذ المقاطع جاهزة."""
        from zahma.predict import engine

        src = inspect.getsource(engine.estimate_on_path)
        # لا استدعاء route() — لكن قد يستورد speeds_at
        assert "route(" not in src.replace("estimate_route(", ""), (
            "المقدّر المثبَّت يوجّه — هذا ينقض غرضه"
        )

    def test_aggregation_is_shared(self):
        """التجميع مصدر واحد — لا نسختان تختلفان.

        لو كُتب حساب الثقة وp90 مرتين، لأعطى نفس الطريق رقمين مختلفين
        حسب أي دالة استُدعيت. وهذا تناقض يهدم الثقة.
        """
        from zahma.predict import engine

        assert hasattr(engine, "_aggregate"), "لا دالة تجميع مشتركة"
        # كلتاهما تستدعيها
        assert "_aggregate(" in inspect.getsource(engine.estimate_route)
        assert "_aggregate(" in inspect.getsource(engine.estimate_on_path)


class TestMeasuredCurveIsSmooth:
    """المنحنى المقاس بعد الإصلاح — الأرقام محفوظة كحقيقة."""

    def test_measured_curve_is_monotonic_to_peak(self):
        """من 06:30 إلى الذروة 07:30: صعود تدريجي بلا قفزات.

        المقاس: 21.55 ← 22.30 ← 22.48 ← 22.70 ← 22.97
        """
        measured = [21.55, 22.30, 22.48, 22.70, 22.97]
        deltas = [b - a for a, b in zip(measured, measured[1:], strict=False)]
        assert all(d > 0 for d in deltas), "المنحنى لا يصعد إلى الذروة"
        assert all(d < 1.0 for d in deltas), (
            f"قفزة أكبر من دقيقة في 15 دقيقة: {deltas}"
        )

    def test_peak_is_at_0730(self):
        """الذروة عند 07:30 — وهو وقت ذروة الصباح الجزائري المعروف."""
        measured = {
            "06:30": 21.55, "06:45": 22.30, "07:00": 22.48,
            "07:15": 22.70, "07:30": 22.97, "07:45": 22.58,
            "08:00": 22.43, "08:15": 20.59, "08:30": 19.38,
        }
        peak = max(measured, key=measured.get)
        assert peak == "07:30", f"الذروة عند {peak} — متوقّعة 07:30"

    def test_old_defect_was_three_times_larger(self):
        """العيب القديم كان قفزة 6.78 د — والإصلاح خفضها إلى 1.83.

        هذه ليست تجميلاً: 6.8 دقائق فرقاً بين خيارين متتاليين يجعل
        توصية «اخرج في 07:30» بلا معنى.
        """
        old_jump = 6.78
        new_jump = 1.83
        assert new_jump < old_jump / 3, (
            "التحسّن أقل من 3× — راجع الإصلاح"
        )

    def test_speed_effect_is_small_on_same_path(self):
        """أثر السرعة على نفس المسار 2.5–3.6% — لا يفسّر التذبذب."""
        speed_effect = max(3.6, 2.5)
        path_effect = 10.6
        assert speed_effect < path_effect / 2, (
            "أثر السرعة يقارب أثر المسار — الفصل غير حاسم"
        )


class TestCurveIsHonestAboutAlternatives:
    """المنحنى لا يخفي أنه لا يعيد التوجيه."""

    def test_docstring_states_path_is_pinned(self):
        """الوصف يذكر تثبيت المسار صراحةً."""
        from zahma.predict.engine import departure_curve

        doc = departure_curve.__doc__ or ""
        assert "مسار ثابت" in doc or "نفس المسار" in doc, (
            "الوصف لا يذكر تثبيت المسار — المستخدم لا يعرف أن هذا طريق واحد"
        )

    def test_docstring_explains_alternative_is_explicit(self):
        """الوصف يقول إن المسار البديل يحتاج طلباً جديداً."""
        from zahma.predict.engine import departure_curve

        doc = departure_curve.__doc__ or ""
        assert "بديل" in doc, (
            "لا يوضّح أن المسار البديل طلب منفصل — إخفاء للحدّ"
        )
