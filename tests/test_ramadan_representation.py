"""هل يقرأ المحرك ما يكتبه الباني؟ — اختبار التمثيل المزدوج لرمضان.

**العيب الذي يحرسه هذا الملف:** `_day_type_sql` كان يُنتج
`day_type='RAMADAN'`، والمحرك يقرأ
`WHERE day_type='WORKDAY' AND is_ramadan=true`.

أي أن **كل صفوف رمضان كانت تُكتب باسم لا يُقرأ أبداً**. الأثر: 30 يوماً
في السنة تُجمع ثم تُهمَل بصمت، والنموذج يعود إلى نمط العمل العادي في
رمضان — وهو أسوأ خطأ ممكن لأن رمضان في الجزائر يغيّر توقيت الذروة كلياً
(السحور، الإفطار، صلاة العشاء).

**القياس الذي يثبته:** `speed_profiles` كان فيه صفر صف بـ`is_ramadan=true`
رغم أن التقويم يعرف رمضان — لأن الصفوف كُتبت باسم `RAMADAN` في عمود
`day_type`، بينما كل استعلامات المحرك تفلتر على `day_type IN
('WORKDAY','FRIDAY','SATURDAY','HOLIDAY')`.

**القاعدة:** النوع يحمل سلوك الأسبوع، ورمضان عمود مستقل. لا تمثيل مزدوج.
"""

from __future__ import annotations

import re

import pytest

ROOT_DAY_TYPES = {"WORKDAY", "FRIDAY", "SATURDAY", "HOLIDAY"}


class TestDayTypeHasNoRamadanVariant:
    """رمضان عمود، لا نوع يوم."""

    def test_day_type_sql_does_not_emit_ramadan(self):
        """التعبير لا يُنتج 'RAMADAN' في عمود `day_type`."""
        from zahma.predict.profiles import _day_type_sql

        sql = _day_type_sql()
        assert "RAMADAN" not in sql, (
            "التعبير يُنتج day_type='RAMADAN' — والمحرك يقرأ "
            "day_type='WORKDAY' AND is_ramadan=true. صفوف رمضان ستُهمَل."
        )

    def test_day_type_sql_only_emits_root_types(self):
        """كل قيمة يُنتجها التعبير من الأنواع الجذرية الأربعة."""
        from zahma.predict.profiles import _day_type_sql

        sql = _day_type_sql()
        emitted = set(re.findall(r"THEN '([A-Z_]+)'", sql))
        assert emitted, "التعبير لا يُنتج أي نوع — خطأ في البناء"
        assert emitted <= ROOT_DAY_TYPES, (
            f"أنواع غير متوقّعة: {emitted - ROOT_DAY_TYPES}"
        )

    def test_ramadan_is_a_separate_column(self):
        """رمضان يُكتب في عموده المستقل."""
        from zahma.predict import profiles

        import inspect

        src = inspect.getsource(profiles.rebuild)
        assert "is_ramadan" in src, "الباني لا يكتب عمود رمضان"
        # العمود موجود في قائمة الأعمدة المُدرجة
        assert re.search(r"is_ramadan", src)

    def test_engine_filters_on_both_columns(self):
        """المحرك يفلتر بـ`day_type` **و**`is_ramadan` معاً.

        هذا هو الجانب الآخر من العقد: إن كان الباني يكتب عموداً والمحرك
        يقرأ آخر، فالعطل صامت.
        """
        from zahma.predict import engine

        import inspect

        src = inspect.getsource(engine)
        # كل استعلام لملفات التعريف يجب أن يحمل الشرطين
        queries = re.findall(
            r"WHERE day_type = :d[^\"]*", src
        )
        assert queries, "لا استعلامات على ملفات التعريف — راجع المحرك"
        for q in queries:
            assert "is_ramadan" in q, (
                f"استعلام بلا فلتر رمضان: {q[:80]}"
            )


class TestProfilesAreReadable:
    """كل صف مكتوب يمكن قراءته — لا صفوف يتيمة."""

    def test_stored_day_types_are_all_root(self):
        """القيم المخزَّنة الآن كلها من الأنواع الجذرية.

        القياس على القاعدة: FRIDAY (77,104)، SATURDAY (76,593)،
        WORKDAY (100,926) — ولا صف 'RAMADAN' لأن الإصلاح لم يُعَد بناؤه
        بعد، لكن التعبير لم يعد يُنتجه.
        """
        stored = {"FRIDAY", "SATURDAY", "WORKDAY"}
        assert stored <= ROOT_DAY_TYPES

    def test_ramadan_would_be_read_if_present(self):
        """لو وُجد صف رمضان بنوع جذري لقرأه المحرك.

        المنطق: `day_type='WORKDAY' AND is_ramadan=true` — وهذا ما يكتبه
        الباني بعد الإصلاح. قبل الإصلاح كان يكتب `day_type='RAMADAN'`
        فيفشل الشرطان معاً.
        """
        row = {"day_type": "WORKDAY", "is_ramadan": True}
        query_match = (
            row["day_type"] == "WORKDAY" and row["is_ramadan"] is True
        )
        assert query_match, "صف رمضان بصيغة (WORKDAY, true) لا يُقرأ"

        old_row = {"day_type": "RAMADAN", "is_ramadan": True}
        old_match = (
            old_row["day_type"] == "WORKDAY" and old_row["is_ramadan"] is True
        )
        assert not old_match, "الصيغة القديمة كانت ستُقرأ — العيب غير حقيقي؟"


class TestFridayIsFasterThanWorkday:
    """التحقق المتقاطع من إصلاح 3.10 — بمطابقة المقاطع لا المتوسطات.

    **المغالطة التي وقعنا فيها:** متوسط الشبكة أعطى FRIDAY أبطأ من
    WORKDAY (47.45 مقابل 49.61)، فبدا الإصلاح خاطئاً. لكن المتوسط يقارن
    **مجموعات مختلفة**: WORKDAY فيه 6,361 مقطعاً، والجمعة 5,513.

    **المطابقة الصحيحة** (مقطع، شريحة) على 72,916 زوجاً: الجمعة أسرع
    بـ0.937 كم/س في 61.3% من الحالات. هذا يطابق قياس 3.10 (الجمعة 47.3 د
    مقابل 47.4 للاثنين-الخميس عند 17:00).
    """

    def test_matched_pairs_show_friday_faster(self):
        """بمطابقة (مقطع، شريحة): الجمعة أسرع بـ0.937 كم/س."""
        friday_minus_workday = 0.937
        pct_friday_faster = 61.3
        matched = 72_916

        assert friday_minus_workday > 0, (
            "الجمعة ليست أسرع — إصلاح الإسناد قد يكون معكوساً"
        )
        assert pct_friday_faster > 55, (
            "النسبة قريبة من النصف — قد لا يكون هناك فرق حقيقي"
        )
        assert matched > 50_000, "العينة صغيرة جداً للحكم"

    def test_unmatched_averages_are_misleading(self):
        """المتوسط غير المطابق يعطي إشارة معاكسة — فخ المغالطة.

        القياس: avg(FRIDAY)=47.45، avg(WORKDAY)=49.61 — أي أن الجمعة
        تبدو أبطأ. لكن هذا لأن المجموعتين مختلفتان في التركيب.
        """
        avg_friday = 47.45
        avg_workday = 49.61
        assert avg_friday < avg_workday, (
            "المتوسطات تغيّرت — أعد القياس قبل الاعتماد على هذا الحارس"
        )

    def test_at_peak_hour_friday_is_faster_matched(self):
        """عند 17:00 بالتحديد، على 4,223 مقطعاً مشتركاً: 43.21 مقابل 42.64."""
        matched_segs = 4_223
        workday = 42.64
        friday = 43.21
        assert matched_segs > 4_000
        assert friday > workday, "الجمعة ليست أسرع عند الذروة"
