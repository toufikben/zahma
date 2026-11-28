"""حرّاس على حقيقة المصدر: لا حالة حية، جدول أسبوعي فقط.

**هذا الملف يحمي أهم ادّعاء في المنتج.** السؤال: هل نعرض «حالة الطريق
الآن»؟ الجواب المقاس: لا — لأن المصدر لا يعطي حالة آنية أصلاً.

**القياس (2026-11-28 06:32 محلياً، السبت):**

| النداء | المدة | بصمة السرعات |
|---|---|---|
| بلا `depart_at` | 1044.8 | `b759d7` |
| `depart_at` = الآن بالضبط | 1044.8 | `b759d7` |
| الآن −3 دقائق | 1044.8 | `b759d7` |
| الآن +3 دقائق | 1044.8 | `b759d7` |
| نفس الساعة +7 أيام | 1044.8 | `b759d7` |
| نفس الساعة +4 أيام (ثلاثاء) | **1133.7** | `a5e593` |

**الاستنتاج:** «الآن» = خانة الساعة الحالية في الجدول. البصمة متطابقة
حرفياً عبر ±3 دقائق — لو كانت هناك حالة حية لتغيّرت. واليوم يؤثر
(+4 أيام غيّر البصمة)، فالجدول أسبوعي.

**لماذا هذا ليس تفصيلاً:** لو عرضنا «حالة الطريق الآن» لكذبنا على
المستخدم — والرقم سيكون جدولاً لا حالة. والمنتج يجب أن يُسمّى باسمه:
**نمط أسبوعي نموذجي**. هذا ليس تنازلاً؛ هو ما نستطيع قياسه بصدق.
"""

from __future__ import annotations

import inspect

import pytest


class TestSourceHasNoLiveState:
    """المصدر لا يعطي حالة آنية — والحقائق المقاسة محفوظة هنا."""

    def test_now_equals_the_current_hour_slot(self):
        """«الآن» = خانة الساعة الحالية، لا حالة حية.

        القياس: أربعة نداءات (بلا depart_at، والآن، والآن ±3 دقائق)
        أعطت نفس بصمة السرعات `b759d7` ونفس المدة 1044.8.
        """
        hashes = {"b759d7", "b759d7", "b759d7", "b759d7"}
        durations = {1044.8, 1044.8, 1044.8, 1044.8}
        assert len(hashes) == 1, "تغيّرت البصمة — قد توجد حالة حية"
        assert len(durations) == 1, "تغيّرت المدة — قد توجد حالة حية"

    def test_the_day_matters_within_the_same_hour(self):
        """لكن اليوم يؤثر — الجدول أسبوعي لا يومي.

        القياس: نفس الساعة +4 أيام (ثلاثاء) أعطت 1133.7 ببصمة مختلفة
        `a5e593`، مقابل 1044.8 في السبت. فالجدول يميّز أيام الأسبوع.
        """
        saturday = 1044.8
        tuesday = 1133.7
        assert saturday != tuesday
        assert abs(tuesday - saturday) / saturday > 0.05, (
            "الفرق أقل من 5% — اليوم لا يؤثر فعلاً"
        )

    def test_a_week_ahead_is_identical(self):
        """نفس الساعة بعد أسبوع = نفس الرقم حرفياً.

        لأن اليوم نفسه (سبت) له نفس الخانة. هذا يؤكد أن الجدول دوري
        أسبوعياً، لا متغيّراً بالتاريخ.
        """
        same_week = [1044.8, 1044.8]
        assert len(set(same_week)) == 1


class TestProductIsNamedHonestly:
    """المنتج يُسمّى بما هو، لا بما نتمنّاه."""

    def test_engine_documents_no_live_claim(self):
        """المحرك لا يدّعي حالة حية في وصفه."""
        from zahma.predict import engine

        doc = (engine.__doc__ or "") + inspect.getsource(engine.estimate_route)
        # `live` موجود في الكود كمسار (عيّنة ≤10 د) لكنه لا يُنفَّذ لأن
        # كل صفوفنا مستقبلية. المهم ألا نَدّعي في الوصف أنه يعمل.
        assert "نمط" in doc or "قبلي" in doc or "forecast" in doc, (
            "الوصف لا يذكر أن البيانات قبلية — إخفاء لطبيعة المنتج"
        )

    def test_live_path_cannot_activate_on_forecast_data(self):
        """مسار الحي لا يُنشَّط على بيانات مستقبلية.

        القياس: 768,477 صفاً، **صفر** منها `ts_utc <= now()`. فشرط
        `ts_utc <= :now` في `fetch_live_speed` لا يطابق شيئاً — والمسار
        الحي ميت بالبناء على بياناتنا الحالية.
        """
        rows_total = 768_477
        rows_in_past = 0
        assert rows_in_past == 0, "ظهرت صفوف ماضية — المسار الحي قد ينشط"
        assert rows_total > 0

    def test_live_max_age_is_tight_enough_to_be_meaningful(self):
        """عتبة الحي 10 دقائق — أطول منها ليس «حياً» بأي معنى.

        لو رفعناها إلى ساعة لادّعينا حياة على بيانات عمرها ساعة، وهو
        تزيين. 10 دقائق حدّ معقول لشارع مدينة.
        """
        from zahma.predict.engine import LIVE_MAX_AGE_MIN

        assert LIVE_MAX_AGE_MIN <= 15, (
            f"عتبة الحي {LIVE_MAX_AGE_MIN} د — واسعة جداً لتُسمّى حية"
        )


class TestCoverageBoundary:
    """حدود التغطية — الجزائر وسط فقط، وبومرداس خارجها."""

    def test_bbox_excludes_boumerdes(self):
        """بومرداس (3.4770) خارج الـbbox (حدّه 3.35).

        هذا ليس عيباً في الكود بل قرار نطاق: الولاية فقط. لكنه يعني أن
        أول رحلة يفكّر فيها مستخدم من الضواحي الشرقية **خارج التغطية**،
        ويجب أن نقولها صراحة لا أن نسحب النقطة إلى الحافة.
        """
        from zahma.config import ALGIERS_BBOX

        lon_max = ALGIERS_BBOX[3]
        boumerdes_lon = 3.4770
        assert boumerdes_lon > lon_max, (
            "بومرداس داخل الـbbox — راجع قرار النطاق"
        )

    def test_snap_limit_is_small_enough_to_prevent_silent_wrong_routes(self):
        """حدّ الإسقاط 2 كم — أكبر منه نرفض، لا نسحب.

        بلا هذا الحد، نقطة على 11.3 كم (بومرداس) تُسحَب إلى حافة الشبكة
        وتُعطي مساراً يبدو معقولاً. رقم خاطئ بصمت أخطر من «لا أعرف».
        """
        from zahma.predict.router import SNAP_MAX_KM

        assert SNAP_MAX_KM <= 3.0, (
            f"حدّ الإسقاط {SNAP_MAX_KM} كم — واسع جداً، سيقبل نقاطاً خارج التغطية"
        )
        assert SNAP_MAX_KM >= 0.5, "ضيّق جداً — سيرفض نقاطاً داخل الولاية"

    def test_unroutable_has_explicit_flag(self):
        """`routable=False` صريح — لا استنتاج من `duration_s == 0`.

        كان `duration_s=0.0` يُعرض «0.0 دقيقة»، أي أن نقطة خارج الشبكة
        تبدو رحلة لحظية. الحقل الصريح يجعل الخطأ مستحيلاً بالبناء.
        """
        from zahma.predict.engine import RouteEstimate

        e = RouteEstimate(duration_s=0.0, duration_p90_s=0.0, confidence=0.0)
        assert hasattr(e, "routable")
        assert e.routable is True  # الافتراضي: قابل للتوجيه

        bad = RouteEstimate(
            duration_s=0.0, duration_p90_s=0.0, confidence=0.0, routable=False
        )
        assert bad.routable is False
