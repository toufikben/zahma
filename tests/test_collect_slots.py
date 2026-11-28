"""هل يغطي جدول الجمع الشرائح الأربع؟ — العيب الذي أفسد منحنى الانطلاق.

**العيب المقاس:** `DEFAULT_COLLECT_HOURS` كانت ساعات كاملة (07:00،
08:00...). وكل ساعة كاملة تعطي `bucket_15m` بقيمة `mod4=0` فقط.
النتيجة على `speed_profiles`:

    mod4=0: 15 شريحة | mod4=1: صفر | mod4=2: 10 | mod4=3: 24 (363 مقطعاً)

أي أن **3 من كل 4 شرائح لم تُجمع**. والأثر ليس تجميلياً: منحنى الانطلاق
تذبذب — 21.6 ← 24.0 ← 25.1 ← 24.3 ← 21.5 دقيقة. صعود ثم هبوط حادّ في
نصف ساعة، وهو مستحيل في واقع مروري. السبب أن كل شريحة من جمع مختلف.

هذا الملف يمنع عودة العيب: يتحقّق أن الجدول يغطي الشرائح الأربع في
ساعات الذروة، وأن التكلفة تبقى داخل الحصة.
"""

from __future__ import annotations

import pytest

from zahma.cli import DEFAULT_COLLECT_HOURS


def _bucket_of(hh: str) -> int:
    h, m = (int(x) for x in hh.split(":"))
    return h * 4 + m // 15


class TestScheduleCoversAllFourSlots:
    """الجدول يغطي 00/15/30/45 — لا ساعة كاملة فقط."""

    def test_all_four_mod_slots_present(self):
        """الشرائح الأربع (mod4=0,1,2,3) كلها ممثَّلة."""
        mods = {_bucket_of(hh) % 4 for hh in DEFAULT_COLLECT_HOURS}
        assert mods == {0, 1, 2, 3}, (
            f"الشرائح المغطاة {sorted(mods)} — ناقص. "
            "الساعات الكاملة وحدها تعطي mod4=0 فقط، فتُترك 3 من 4 شرائح فارغة."
        )

    def test_morning_peak_has_four_consecutive_slots(self):
        """ذروة الصباح: أربع شرائح متتالية (07:00–07:45).

        الذروة هي أهم جزء في المنتج — قرار «متى أخرج» يقع هنا. جمع شريحة
        واحدة منها يجعل المنحنى يعتمد على تخمين في أهم لحظة.
        """
        peak = [hh for hh in DEFAULT_COLLECT_HOURS if hh.startswith("07:")]
        buckets = sorted(_bucket_of(hh) for hh in peak)
        assert len(buckets) == 4, f"ذروة الصباح {len(buckets)} شريحة بدل 4"
        assert buckets == list(range(buckets[0], buckets[0] + 4)), (
            f"الشرائح غير متتالية: {buckets}"
        )

    def test_evening_peak_has_four_consecutive_slots(self):
        """ذروة المساء: أربع شرائح متتالية على الأقل.

        ذروة المساء (17:00) هي أسوأ ساعة في اليوم مقاساً (42.5 كم/س مقابل
        68.2 عند 04:00). هي جوهر المنتج.
        """
        evening = [
            hh for hh in DEFAULT_COLLECT_HOURS
            if hh.startswith("17:") or hh.startswith("18:")
        ]
        buckets = sorted(_bucket_of(hh) for hh in evening)
        assert len(buckets) >= 8, (
            f"ذروة المساء {len(buckets)} شريحة — تحتاج 8 (17:00–18:45)"
        )
        # متتالية بلا فراغ
        assert buckets == list(range(buckets[0], buckets[0] + len(buckets))), (
            f"فجوة في ذروة المساء: {buckets}"
        )

    def test_no_hour_is_only_a_full_hour(self):
        """لا ساعة كاملة تُجمع وحدها — كل ساعة ذروة لها رفاق.

        لو بقي `"09:00"` وحده بلا 09:15، فشريحة mod4=1 مفقودة لذلك
        الساعة، والمنحنى يعود يتذبذب.
        """
        by_hour: dict[int, list[int]] = {}
        for hh in DEFAULT_COLLECT_HOURS:
            by_hour.setdefault(int(hh.split(":")[0]), []).append(_bucket_of(hh) % 4)
        lonely = [
            h for h, mods in by_hour.items()
            if len(mods) == 1 and mods == [0] and 5 <= h <= 19
        ]
        assert not lonely, (
            f"ساعات ذروة بساعة كاملة وحدها: {lonely} — شرائحها ناقصة"
        )


class TestScheduleCostStaysInBudget:
    """التكلفة تبقى داخل الحصة — وإلا صار الإصلاح مشكلة."""

    def test_monthly_cost_under_quota(self):
        """20 زوجاً × الخانات × 30 يوماً < 90% من 100,000.

        القياس: 28 خانة × 20 زوجاً × 30 = 16,800 طلباً شهرياً.
        """
        slots = len(DEFAULT_COLLECT_HOURS)
        pairs = 20
        monthly = slots * pairs * 30
        quota = 100_000
        assert monthly < quota * 0.90, (
            f"{monthly:,} طلباً شهرياً — يتجاوز 90% من {quota:,}"
        )

    def test_slots_count_is_reasonable(self):
        """عدد الخانات معقول — لا 96 (كل ربع ساعة) ولا 19 (ساعات كاملة).

        96 خانة × 20 زوجاً × 30 = 57,600 — نصف الحصة لجمع يومي كامل.
        ممكن لكنه يمنع أي جمع إضافي. 28 خانة تركّز على الذروة.
        """
        n = len(DEFAULT_COLLECT_HOURS)
        assert 20 <= n <= 40, f"{n} خانة — خارج المدى المعقول"


class TestNightIsSampledSparsely:
    """الليل يُجمع بوتيرة أبطأ — القياس يبرّره."""

    def test_night_has_fewer_slots_than_peak(self):
        """الليل شريحة كل ساعتين، لا كل ربع ساعة.

        القياس: منحنى الليل مسطّح (23:59–05:00 مدى 4.2 كم/س فقط)، فالشرائح
        الإضافية لا تضيف معلومة. الذروة تتغيّر 90% في نفس المدة.
        """
        night = [
            hh for hh in DEFAULT_COLLECT_HOURS
            if int(hh.split(":")[0]) in (21, 22, 23, 0, 1, 2, 3, 4)
        ]
        peak = [
            hh for hh in DEFAULT_COLLECT_HOURS
            if 6 <= int(hh.split(":")[0]) <= 8
        ]
        assert len(night) < len(peak), (
            f"الليل {len(night)} خانة والذروة {len(peak)} — "
            "الليل يحتاج أقل، منحناه مسطّح"
        )
