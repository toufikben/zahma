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
