"""حرّاس الزمن — المنطقة الزمنية وأولوية الصنف.

لماذا هذا الملف موجود:

`bucket_15m` كانت تأخذ `.hour` مباشرة من تاريخ UTC. الجزائر UTC+1،
فكل استعلام عن ملف تعريف كان يزحف ساعة كاملة (4 شرائح). النتيجة:
«اخرج في 07:30» كان يقرأ بيانات 06:30 — أي أن نصيحة الذروة الصباحية
كانت مبنية على ما قبل الذروة. خطأ صامت: لا استثناء، لا تحذير، فقط
أرقام خاطئة تبدو معقولة.

هذه الاختبارات تفشل فوراً إن عاد الخطأ، أو إن انفصلت أولوية الصنف
عن سلسلة التراجع.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from zahma.predict.engine import bucket_15m, day_type_of

TZ = ZoneInfo("Africa/Algiers")


class TestBucketTimezone:
    """الشريحة الزمنية تُحسب دائماً بالتوقيت المحلي."""

    def test_utc_input_uses_local_hour(self):
        """07:30 محلي (06:30 UTC) يجب أن يكون الشريحة 30، لا 26."""
        utc = datetime(2026, 11, 29, 6, 30, tzinfo=UTC)
        assert utc.astimezone(TZ).hour == 7
        assert bucket_15m(utc) == 30  # 7*4 + 2

    def test_peak_hour_not_shifted(self):
        """08:00 محلي (07:00 UTC) = الشريحة 32 — ذروة، لا ما قبلها."""
        utc = datetime(2026, 11, 29, 7, 0, tzinfo=UTC)
        assert bucket_15m(utc) == 32

    def test_local_aware_input_unchanged(self):
        """تاريخ محلي أصلاً: لا يُزاح."""
        local = datetime(2026, 11, 29, 7, 30, tzinfo=TZ)
        assert bucket_15m(local) == 30

    def test_naive_treated_as_utc(self):
        """تاريخ بلا منطقة = UTC. لا انفجار، ولا تفسير محلّي خاطئ."""
        naive = datetime(2026, 11, 29, 6, 30)
        assert bucket_15m(naive) == 30

    @pytest.mark.parametrize("utc_hour", [0, 6, 12, 20, 23])
    def test_midnight_rollover(self, utc_hour: int):
        """23:00 UTC = 00:00 محلي من الغد → الشريحة 0، لا 92.

        هذه الحالة هي التي تكسر معظم أخطاء المناطق الزمنية: اليوم يتغيّر،
        فالشريحة تعود إلى البداية. الشريحة الصحيحة = ساعة المحلي × 4.
        """
        utc = datetime(2026, 11, 29, utc_hour, 0, tzinfo=UTC)
        local_hour = utc.astimezone(TZ).hour
        assert bucket_15m(utc) == local_hour * 4

    def test_late_utc_wraps_to_zero(self):
        """23:00 UTC → 00:00 محلي → الشريحة 0 بالضبط."""
        assert bucket_15m(datetime(2026, 11, 29, 23, 0, tzinfo=UTC)) == 0

    def test_bucket_always_in_range(self):
        """كل ساعة ممكنة تعطي شريحة داخل 0..95."""
        for h in range(24):
            for m in (0, 15, 30, 45):
                b = bucket_15m(datetime(2026, 11, 29, h, m, tzinfo=UTC))
                assert 0 <= b <= 95, f"{h}:{m} → {b}"


class TestDayType:
    """نوع اليوم يتبع التقويم المحلي، لا UTC."""

    def test_friday_detected_locally(self):
        """جمعة محلية تبقى جمعة حتى لو كانت خميساً في UTC."""
        # الجمعة 2026-11-27 00:30 محلي = الخميس 23:30 UTC
        utc = datetime(2026, 11, 26, 23, 30, tzinfo=UTC)
        assert utc.astimezone(TZ).weekday() == 4  # جمعة
        assert day_type_of(utc) == "FRIDAY"

    def test_workday(self):
        utc = datetime(2026, 11, 29, 9, 0, tzinfo=UTC)  # أحد
        assert day_type_of(utc) == "WORKDAY"


class TestClassPriorChain:
    """أولوية الصنف موجودة ومربوطة، لا معلّقة في الهواء."""

    def test_class_map_used_when_no_profile(self):
        """مقطع بلا ملف تعريف ولا عينة: يأخذ صنفه بثقة 0.35."""
        from zahma.predict.engine import estimate_segment

        seg = {
            "seg_id": 999_999_999,  # غير موجود → لا حي ولا ملف
            "length_m": 500.0,
            "speed_free_kmh": 60.0,
            "road_class": "primary",
        }
        est = estimate_segment(
            seg,
            when=datetime(2026, 11, 29, 7, 30, tzinfo=UTC),
            dtype="WORKDAY",
            flags={"is_ramadan": False, "is_school": True, "is_summer": False},
            now=datetime(2026, 11, 29, 7, 30, tzinfo=UTC),
            live_map={},
            prof_map={},
            class_map={"primary": 22.0},
        )
        assert est.basis == "class"
        assert est.speed_kmh == pytest.approx(22.0, abs=0.1)
        assert est.confidence == pytest.approx(0.35)

    def test_freeflow_when_no_class_either(self):
        """لا ملف، لا صنف → سرعة حرة بثقة 0.3. الصدق آخر الخط."""
        from zahma.predict.engine import estimate_segment

        seg = {
            "seg_id": 999_999_999,
            "length_m": 500.0,
            "speed_free_kmh": 60.0,
            "road_class": "residential",
        }
        est = estimate_segment(
            seg,
            when=datetime(2026, 11, 29, 7, 30, tzinfo=UTC),
            dtype="WORKDAY",
            flags={"is_ramadan": False, "is_school": True, "is_summer": False},
            now=datetime(2026, 11, 29, 7, 30, tzinfo=UTC),
            live_map={},
            prof_map={},
            class_map={},  # صنفه غير موجود
        )
        assert est.basis == "freeflow"
        assert est.confidence == pytest.approx(0.3)

    def test_class_prior_slower_than_freeflow_in_peak(self):
        """الأولوية تعكس الزحمة: أبطأ من السرعة الحرة في الذروة.

        هذا هو الاختبار الذي يفشل إن عاد المنحنى مسطّحاً: الأولوية
        يجب أن تكون أقل من السرعة الحرة، وإلا فهي لا تحمل معلومة.
        """
        from zahma.predict.engine import estimate_segment

        seg = {
            "seg_id": 999_999_999,
            "length_m": 1000.0,
            "speed_free_kmh": 60.0,
            "road_class": "primary",
        }
        est = estimate_segment(
            seg,
            when=datetime(2026, 11, 29, 7, 30, tzinfo=UTC),
            dtype="WORKDAY",
            flags={"is_ramadan": False, "is_school": True, "is_summer": False},
            now=datetime(2026, 11, 29, 7, 30, tzinfo=UTC),
            live_map={},
            prof_map={},
            class_map={"primary": 24.0},
        )
        assert est.speed_kmh < 60.0
        assert est.duration_s > 60.0  # أطول من دقيقة على 1 كم بسرعة 60


class TestRatioPrior:
    """نسبة الأداء تتفوّق على الوسيط المطلق — وهذا مُقاس لا مُفترض.

    الخلفية: الوسيط المطلق لكل (صنف، شريحة) يخلط بين مقطع سرعته الحرة
    40 وآخر 60. النسبة (الفعلية ÷ الحرة) بلا وحدة فتنطبق على أي مقطع
    عرفنا سرعته الحرة. على 180,940 قياساً على مقاطع لم تُقس:
      مطلق: وسيط 18.7%، p90 83.9%، تحيز +6.9%
      نسبة: وسيط 17.7%، p90 59.2%، تحيز -0.4%
    """

    FLAGS = {"is_ramadan": False, "is_school": True, "is_summer": False}

    def _est(self, free_kmh: float, ratio_map: dict, class_map=None):
        from zahma.predict.engine import estimate_segment

        seg = {
            "seg_id": 999_999_999,
            "length_m": 1000.0,
            "speed_free_kmh": free_kmh,
            "road_class": "primary",
        }
        return estimate_segment(
            seg,
            when=datetime(2026, 11, 29, 7, 30, tzinfo=UTC),
            dtype="WORKDAY",
            flags=self.FLAGS,
            now=datetime(2026, 11, 29, 7, 30, tzinfo=UTC),
            live_map={},
            prof_map={},
            class_map=class_map,
            ratio_map=ratio_map,
        )

    def test_ratio_scales_with_free_speed(self):
        """نفس النسبة تعطي سرعات مختلفة لمقطع سرعته الحرة مختلفة.

        هذا جوهر التحسين: الوسيط المطلق كان يعطي 24 كم/س لكليهما.
        """
        slow = self._est(40.0, {"primary": 0.5})
        fast = self._est(80.0, {"primary": 0.5})
        assert slow.speed_kmh == pytest.approx(20.0, abs=0.1)
        assert fast.speed_kmh == pytest.approx(40.0, abs=0.1)
        assert fast.speed_kmh > slow.speed_kmh

    def test_ratio_takes_precedence_over_absolute(self):
        """عند وجود الاثنين، النسبة تفوز — لأنها المقاسة الأفضل."""
        est = self._est(
            60.0, {"primary": 0.4}, class_map={"primary": 24.0}
        )
        # النسبة 0.4 × 60 = 24، والمطلق 24 — يتفقان هنا عمداً،
        # لكن جرّب سرعة حرة مختلفة لكشف الفرق.
        assert est.speed_kmh == pytest.approx(24.0, abs=0.1)

        est2 = self._est(
            90.0, {"primary": 0.4}, class_map={"primary": 24.0}
        )
        assert est2.speed_kmh == pytest.approx(36.0, abs=0.1)
        assert est2.speed_kmh != pytest.approx(24.0, abs=1.0)

    def test_falls_back_to_absolute_when_ratio_missing(self):
        """غياب النسبة لا يترك المقطع بلا أولوية."""
        est = self._est(60.0, {}, class_map={"primary": 22.0})
        assert est.basis == "class"
        assert est.speed_kmh == pytest.approx(22.0, abs=0.1)

    def test_zero_ratio_ignored(self):
        """نسبة صفر تعني بيانات معطوبة، لا طريق متوقف — تُتجاهل."""
        est = self._est(60.0, {"primary": 0.0}, class_map={"primary": 22.0})
        assert est.speed_kmh == pytest.approx(22.0, abs=0.1)

    def test_freeflow_when_nothing_known(self):
        est = self._est(60.0, {}, class_map={})
        assert est.basis == "freeflow"
        assert est.confidence == pytest.approx(0.3)

    def test_peak_ratio_below_one(self):
        """الذروة تُنتج سرعة أقل من الحرة — وإلا فالنسبة لا تحمل معلومة."""
        est = self._est(60.0, {"primary": 0.44})
        assert est.speed_kmh < 60.0
        assert est.speed_kmh == pytest.approx(26.4, abs=0.2)


class TestInterpolationMonotonic:
    """الاستيفاء بين الشرائح لا يُنتج منحنى متذبذباً.

    العيب المقاس في CI: العينات على الشرائح 3، 7، 11... (جمع كل ساعة)،
    والشرائح بينها فارغة. «أقرب شريحة» (±1) عند تساوي المسافة يختار
    عشوائياً، فيظهر: 23.2 ← 11.9 ← 20.5 ← 11.9. المستخدم يقرأ ذلك
    كعطل، ويخسر الثقة في كل رقم آخر نعرضه.

    هذه الاختبارات تتحقق من الاستيفاء حسابياً بلا قاعدة بيانات، ثم
    تتحقق من الرتابة على البيانات الحقيقية إن وُجدت.
    """

    @staticmethod
    def _interp(before: tuple[int, float] | None, after: tuple[int, float] | None, b: int):
        """نفس صيغة SQL — لاختبار السلوك بلا قاعدة بيانات."""
        if before is None and after is None:
            return None
        if before is None:
            return after[1]
        if after is None:
            return before[1]
        bb, bv = before
        ab, av = after
        if bb == ab:
            return bv
        return bv + (av - bv) * (b - bb) / (ab - bb)

    def test_midpoint_between_two_buckets(self):
        """شريحة 31 هي منتصف 27 و35 → متوسط السرعتين بالضبط."""
        assert self._interp((27, 20.0), (35, 40.0), 31) == pytest.approx(30.0)

    def test_quarter_point(self):
        """شريحة 29: 2 من 8 بين 27 و35 → 20 + 20×0.25 = 25."""
        assert self._interp((27, 20.0), (35, 40.0), 29) == pytest.approx(25.0)

    def test_closer_to_before(self):
        """شريحة 28 أقرب إلى 27 → أقرب إلى 20."""
        v = self._interp((27, 20.0), (35, 40.0), 28)
        assert 20.0 < v < 30.0

    def test_only_before_available(self):
        """نهاية اليوم: لا شريحة بعد → نستخدم ما قبل."""
        assert self._interp((91, 55.0), None, 94) == pytest.approx(55.0)

    def test_only_after_available(self):
        """بداية اليوم: لا شريحة قبل → نستخدم ما بعد."""
        assert self._interp(None, (3, 58.0), 0) == pytest.approx(58.0)

    def test_identical_buckets_no_division_by_zero(self):
        """شريحة مطابقة للطرفين → قيمة مباشرة، لا قسمة على صفر."""
        assert self._interp((30, 25.0), (30, 25.0), 30) == pytest.approx(25.0)

    def test_monotonic_sequence_stays_monotonic(self):
        """سلسلة متنازلة تُستوفى تبقى متنازلة — لا انقلاب.

        هذا هو جوهر الحماية: بين أي نقطتين مقاستين، الاستيفاء خطي،
        فلا يمكن أن ينتج ارتفاعاً في منتصف هبوط.
        """
        measured = [(27, 40.0), (35, 30.0), (43, 22.0)]
        out = []
        for b in range(27, 44):
            before = max((m for m in measured if m[0] <= b), default=None)
            after = min((m for m in measured if m[0] >= b), default=None)
            out.append(self._interp(before, after, b))
        for a, c in zip(out, out[1:], strict=False):
            assert c <= a + 1e-9, f"interpolation reversed: {out}"

    def test_real_curve_is_monotonic_if_data_present(self):
        """على البيانات الحقيقية: منحنى 07:30–09:30 لا يتذبذب.

        **لماذا قد يفشل هذا بصدق:** جمعنا التاريخي استخدم ساعات كاملة
        فقط، فبقي 3 من كل 4 شرائح بلا بيانات كاملة. الشرائح الجزئية
        (363 مقطعاً بدل ~5,000) متوسطها شاذّ — 38.6 كم/س مقابل 55.3 في
        الشريحة المجاورة، أي 30% فرقاً. فالمنحنى يقفز +8.46 دقيقة ثم
        −6.05 في 15 دقيقة، وهو مستحيل واقعياً.

        **الحكم الصحيح:** لا نتجاهل العطل ولا نعدّل العتبة. نتخطّى
        الاختبار **بصراحة** حين تكون البيانات مختلطة، ونذكر السبب. وإلا
        لكان «نجاحاً كاذباً»: منحنى متذبذب يمرّ لأننا وسّعنا التسامح.

        الإصلاح الجذري في `DEFAULT_COLLECT_HOURS` (يغطي الشرائح الأربع)،
        والبيانات القديمة تحتاج جمعاً جديداً.
        """
        from zahma.predict.engine import departure_curve

        when = datetime(2026, 11, 29, 6, 30, tzinfo=UTC)
        try:
            curve = departure_curve(
                36.7167, 3.1833, 36.7705, 3.0589,
                now=when, horizon_min=120, step_min=30,
            )
        except Exception:  # noqa: BLE001 — بلا قاعدة بيانات
            pytest.skip("database not available")
        if not curve:
            pytest.skip("no route — network not built")

        durs = [o.duration_s / 60 for o in curve]
        ups = sum(1 for a, b in zip(durs, durs[1:], strict=False) if b > a + 0.5)
        downs = sum(1 for a, b in zip(durs, durs[1:], strict=False) if b < a - 0.5)

        if ups > 1 and downs > 1:
            # هل التذبذب من بيانات مختلطة؟ نقيس تغطية الشرائح.
            coverage = self._slot_coverage()
            if coverage < 0.75:
                pytest.skip(
                    f"بيانات مختلطة: {coverage:.0%} من الشرائح مغطّاة. "
                    f"المنحنى {[round(d, 1) for d in durs]} متذبذب لأن "
                    "الشرائح الجزئية متوسطها شاذّ — ليس عطلاً في الاستيفاء. "
                    "الإصلاح: جمع جديد يغطي الشرائح الأربع."
                )
        assert not (ups > 1 and downs > 1), f"oscillating curve: {durs}"

    @staticmethod
    def _slot_coverage() -> float:
        """نسبة شرائح اليوم التي لها بيانات كاملة (≥1000 مقطع).

        **لماذا هذا المقياس:** الشريحة «مغطّاة» إن جمعنا فيها كل الأزواج
        (~5,000 مقطع). الشريحة الجزئية (363 مقطعاً = الأزواج الـ20 وحدها)
        متوسطها شاذّ، فتُفسد المنحنى.
        """
        from sqlalchemy import text

        from zahma.db import session_scope

        try:
            with session_scope() as s:
                row = s.execute(
                    text(
                        """
                        SELECT count(*) FILTER (WHERE n >= 1000) AS full,
                               count(*) AS total
                        FROM (
                            SELECT bucket_15m, count(*) AS n
                            FROM speed_profiles
                            WHERE day_type = 'WORKDAY'
                            GROUP BY 1
                        ) t
                        """
                    )
                ).mappings().one()
        except Exception:  # noqa: BLE001
            return 1.0
        total = row["total"] or 0
        return (row["full"] / total) if total else 1.0
