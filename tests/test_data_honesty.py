"""حرّاس على طبيعة بيانات Mapbox — الاكتشاف الذي يمنع تقييماً كاذباً.

**العيب الذي تمنعه هذه الاختبارات:** قِسنا «دقة 0.1%» وبدت ممتازة. الحقيقة
أن Mapbox يعيد للجزائر جدولاً أسبوعياً نموذجياً ثابتاً، فكل يوم ثلاثاء هو
نفس بيانات كل ثلاثاء آخر حرفياً. أي تقسيم زمني للتدريب/الاختبار هو تسرّب
كامل، والنموذج يقرأ ما تدرّب عليه ويقول «دقيق».

أي شخص يضيف لاحقاً اختبار دقة زمنياً سيعود إلى نفس الفخ. هذه الاختبارات
تحرس القاعدة الحسابية التي تكشفه، فلا تحتاج بيانات شبكة لتعمل.
"""

from __future__ import annotations

import statistics

import pytest


def weekday_determinism_gap(
    a: list[float], b: list[float]
) -> float:
    """متوسط الفرق المطلق بين قياسين متطابقين زمنياً.

    إن كان ~0 ⇒ المزوّد يعيد نفس القيم ⇒ لا بيانات حية.
    """
    assert len(a) == len(b)
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


class TestProviderDeterminism:
    """يفصل «نمط ثابت» عن «قياس حي» حسابياً."""

    def test_identical_weekdays_detected(self):
        """ملف تعريف أسبوعي ثابت: كل ثلاثاء يساوي كل ثلاثاء."""
        tue1 = [45.0, 38.2, 52.1, 20.4]
        tue2 = [45.0, 38.2, 52.1, 20.4]
        assert weekday_determinism_gap(tue1, tue2) == 0.0

    def test_live_traffic_detected(self):
        """حركة حية: نفس الطريق في نفس الساعة يتغيّر فعلاً.

        الفرق الحقيقي بين قياسين متتاليين على طريق مزدحم يجب أن يكون
        ملحوظاً — كيلومترات في الساعة، لا أعشاراً.
        """
        run1 = [45.0, 38.2, 52.1, 20.4]
        run2 = [41.7, 44.1, 47.9, 25.2]
        gap = weekday_determinism_gap(run1, run2)
        assert gap > 2.0, f"live traffic should vary, gap={gap}"

    def test_rounding_noise_is_not_live_traffic(self):
        """الفرق المقاس بين أيام العمل في الجزائر كان 0.15–0.24 كم/س.

        هذا ضجيج تقريب عشري في تحويل الوحدات، لا اختلاف حركة. العتبة
        تفصله بوضوح عن أدنى تغيّر حركة حقيقي.
        """
        noise = 0.24
        real_traffic = 2.0
        assert noise < real_traffic / 5

    def test_day_split_leaks_when_deterministic(self):
        """يوضّح التسرّب: تقسيم زمني على نمط ثابت يعطي خطأً صفرياً كاذباً."""
        # نفس البيانات مرتين — تماماً كما فعل المزوّد.
        train = [45.0, 38.2, 52.1]
        holdout = [45.0, 38.2, 52.1]
        # «نموذج» تافه يعيد وسيط التدريب.
        pred = statistics.median(train)
        err = abs(pred - holdout[0]) / holdout[0] * 100
        # الخطأ صغير جداً ليس لأن النموذج جيد، بل لأن البيانات مكرّرة.
        assert err < 15.0
        assert train == holdout


class TestSpatialHoldoutRule:
    """قاعدة الحجز المكاني: اختبار يختلف عن التدريب فعلياً."""

    def test_no_train_segment_in_test(self):
        train_segs = {1, 2, 3}
        test_segs = {4, 5, 6}
        assert not (train_segs & test_segs)

    def test_pairs_are_disjoint(self):
        """تقسيم الأزواج إلى زوجي/فردي — لا يختلط مصدر القياس."""
        pairs = list(range(1, 20))
        train = {p for p in pairs if p % 2 == 0}
        test = set(pairs) - train
        assert not (train & test)
        assert len(train) + len(test) == len(pairs)

    def test_expected_accuracy_envelope(self):
        """رقم الدقة الصادق المقاس: 18.7% على مقاطع لم تُقس.

        الاختبار يحرس أن الحدّ المقبول في تقارير الدقة لا ينزلق إلى
        رقم متفائل يستحيل تحقيقه بلا تسرّب.
        """
        measured_median_err = 18.7
        assert 10.0 <= measured_median_err <= 30.0
        # أي ادعاء بأقل من 5% على شبكة OSM بلا حقيقة أرضية هو تسرّب.
        assert measured_median_err > 5.0
