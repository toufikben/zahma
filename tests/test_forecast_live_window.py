"""نافذة «الآن» — يحتاج قاعدة بيانات حقيقية.

**لماذا ملف منفصل:** هذه الاختبارات الثلاثة تقرأ جدول `samples` فعلياً.
باقي حرّاس العيب نفسه (وجود `dropped`، الحد الأدنى، الجمعة) لا تحتاج
قاعدة بيانات، فتُشغَّل في وظيفة `unit` في CI.

كانت الثلاثة في نفس ملف الحرّاس، والملف كله مستبعد من CI لأن بعضه
يحتاج قاعدة — فالنتيجة أن **العيب الأهم (التنبؤ يُقرأ كقياس حي) لم
يكن محمياً في CI إطلاقاً**. الفصل يجعل الحماية تعمل حيث تعمل، ويُشغّل
هذه الثلاثة في وظيفة `integration` حيث توجد قاعدة فعلية.

**العيب الأصلي:** جمعنا يعمل بـ`depart_at`، فكل صفوفنا مستقبلية.
استعلام بلا حد أعلى (`ts_utc > now - 10min`) التقط 674,137 صفاً
مستقبلياً وسمّاها «قياساً حياً» بثقة 0.9.
"""

from __future__ import annotations

from datetime import UTC, datetime

from zahma.predict.engine import fetch_live_speeds_bulk


class TestForecastIsNeverLive:
    """التنبؤ لا يُقرأ أبداً كقياس آني."""

    def test_future_rows_are_not_returned_as_live(self):
        """`now` قبل كل صفوفنا ⇒ صفر. لا بيانات حيّة أصلاً، وهذا الصدق."""
        early = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
        live = fetch_live_speeds_bulk(early, max_age_min=10.0)
        assert live == {}, "التنبؤ المستقبلي تسرّب كقياس حي"

    def test_live_window_is_bounded_on_both_sides(self):
        """`now` في وسط البيانات المستقبلية: لا صف بعد النافذة."""
        mid = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)
        live = fetch_live_speeds_bulk(mid, max_age_min=10.0)
        assert all(isinstance(k, int) for k in live)

    def test_forecast_marker_is_excluded(self):
        """الوسم `forecast` مستبعد صراحةً، لا بالمصادفة الزمنية."""
        now = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)
        live = fetch_live_speeds_bulk(now, max_age_min=10.0)
        assert len(live) == 0, "صفوف forecast ظهرت كقياس حي — الوسم لم يُطبَّق"
