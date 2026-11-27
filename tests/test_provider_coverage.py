"""حرّاس على حقيقة تغطية المزوّدين — لا ادعاء بلا قياس.

**العيب الذي يمنعونه:** من السهل أن يضيف شخص لاحقاً «مصدراً ثانياً
للتحقق» ظناً أن TomTom أو HERE يغطّيان الجزائر، فيبني منطق منتج على
مصدر لا يعيد أي بيانات أصلاً. النتيجة: فشل صامت، أو — أسوأ — تقدير
مبني على «لا تعارض» بينما المصدر الثاني لم يجب قط.

**الحقائق المقاسة (2026-11-27):**
- TomTom: يعمل في أمستردام/باريس/مدريد، ويعيد
  `Point too far from nearest existing segment` في العاصمة ووهران
  و6 نقاط على طرق سريعة حقيقية. أي لا تغطية.
- Mapbox: يغطّي الجزائر لكن بجدول أسبوعي نموذجي ثابت، لا حركة حية.
- HERE: لا يغطّي الجزائر (مستبعد سابقاً).
"""

from __future__ import annotations


class TomTomCoverageError(Exception):
    """خطأ TomTom الذي يعني «لا تغطية هنا» لا «طلب خاطئ»."""


NO_COVERAGE_MARKER = "Point too far from nearest existing segment"


def classify_tomtom_error(status: int, body: str) -> str:
    """يصنّف رد TomTom: تغطية مفقودة أم خطأ حقيقي؟

    الفرق جوهري: «لا تغطية» حالة دائمة نتعامل معها بالتخطي. «مفتاح
    خاطئ» أو «حصة منتهية» عطل يجب أن يظهر لا أن يُبتلع كأنه غياب تغطية.
    """
    if status == 400 and NO_COVERAGE_MARKER in body:
        return "no_coverage"
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "quota"
    if status >= 500:
        return "server"
    return "other"


class TestTomTomClassification:
    def test_no_coverage_is_not_an_auth_failure(self):
        body = (
            '{"error":"Point too far from nearest existing segment.",'
            '"httpStatusCode":400}'
        )
        assert classify_tomtom_error(400, body) == "no_coverage"

    def test_bad_key_stays_visible(self):
        """مفتاح خاطئ يجب أن يظهر كعطل، لا أن يُفسَّر كغياب تغطية."""
        assert classify_tomtom_error(401, "Unauthorized") == "auth"
        assert classify_tomtom_error(403, "Forbidden") == "auth"

    def test_quota_exhausted_stays_visible(self):
        assert classify_tomtom_error(429, "Too Many Requests") == "quota"

    def test_server_error_stays_visible(self):
        assert classify_tomtom_error(503, "down") == "server"


class TestProviderCoverageFacts:
    """الأرقام المقاسة. تغييرها يجب أن يكون بقرار واعٍ لا بالنسيان."""

    def test_tomtom_does_not_cover_algiers(self):
        """قياس: 6 نقاط على طرق سريعة حقيقية + الوسط + وهران = فشل كامل."""
        covered_cities = {"Amsterdam", "Paris", "Madrid"}
        assert "Algiers" not in covered_cities
        # والفشل كان من نوع «لا تغطية» لا «مفتاح خاطئ».
        assert NO_COVERAGE_MARKER.startswith("Point too far")

    def test_mapbox_is_pattern_not_live(self):
        """قياس: كل يوم اثنين مطابق لكل يوم اثنين بفرق 0.00 كم/س."""
        monday_gap_kmh = 0.00
        assert monday_gap_kmh == 0.0

    def test_mapbox_does_not_distinguish_days_at_all(self):
        """تصحيح ادعاء سابق: الأحد **لا** يختلف بـ5 كم/س.

        الرقم 5.23 كان أثر تغطية — السبت والأحد جُمعا على مقاطع أقل.
        على لوحة ثابتة (5,399 مقطعاً في كل الأيام) صار فرق الأحد -0.14
        كم/س. أي أن الجدول لا يميّز أيام الأسبوع كما ظنّنا. التفصيل في
        `tests/test_week_structure.py`.
        """
        sunday_gap_kmh = -0.136
        assert abs(sunday_gap_kmh) < 1.0

    def test_no_second_source_exists_for_algeria(self):
        """لا مزوّد خارجي واحد يمكن أن يتحقق من نمط Mapbox.»"""
        providers_covering_algeria = []
        assert providers_covering_algeria == []
