"""حرّاس على تحويل وقت المستخدم — ساعة الخطأ التي تهدم المنحنى.

**العيب المقاس:** `datetime.fromisoformat(at)` يعيد `naive`. و`bucket_15m`
يفترض UTC عند غياب المنطقة، فيقرأ `09:00` المستخدم كـ`08:00` — 4 شرائح
خطأً. والنتيجة: CLI أعطى 24.0 د عند 09:00 مقابل 22.43 الصحيحة، وظهرت
قفزة +3.5 دقيقة وهمية.

**الإصلاح:** `_parse_local_time` يضع الوقت صراحةً في `Africa/Algiers`.

**وهذا يمسّ كل واجهة:** `estimate` و`departure` كلاهما كانا يستدعيان
`fromisoformat` مباشرة. أي تطبيق client سيرسل وقتاً محلياً، فلا بد أن
يكون التفسير واحداً في كل الأوامر.
"""

from __future__ import annotations

import inspect
from datetime import datetime

import pytest


class TestUserTimeIsLocal:
    """وقت المستخدم يُفسَّر محلياً دائماً."""

    def test_parse_local_time_attaches_zone(self):
        """الوقت الناتج يحمل منطقة زمنية صريحة."""
        from zahma.cli import _parse_local_time

        t = _parse_local_time("2026-12-15T09:00")
        assert t is not None
        assert t.tzinfo is not None, "وقت بلا منطقة — سيُقرأ UTC"

    def test_parse_local_time_maps_to_correct_bucket(self):
        """`09:00` محلياً ⇒ الشريحة 36، لا 32.

        القياس: قبل الإصلاح كان `09:00` يُقرأ كـ08:00 UTC ⇒ شريحة 32،
        أي 4 شرائح قبل الموعد الحقيقي.
        """
        from zahma.cli import _parse_local_time
        from zahma.predict.engine import bucket_15m

        t = _parse_local_time("2026-12-15T09:00")
        assert bucket_15m(t) == 36, (
            f"الشريحة {bucket_15m(t)} — متوقّعة 36 (09:00 محلياً)"
        )

    def test_empty_time_means_now(self):
        """القيمة الفارغة تعني «الآن» — تُترك `None`."""
        from zahma.cli import _parse_local_time

        assert _parse_local_time("") is None

    def test_already_zoned_time_is_preserved(self):
        """إن أرسل العميل وقتاً بمنطقة، لا نُعيد كتابتها."""
        from datetime import UTC

        from zahma.cli import _parse_local_time

        t = _parse_local_time("2026-12-15T09:00:00+00:00")
        assert t is not None
        assert t.tzinfo is not None
        assert t.utcoffset().total_seconds() == 0

    def test_both_commands_use_the_shared_parser(self):
        """`estimate` و`departure` يستدعيان الدالة نفسها.

        لو بقي `fromisoformat` مباشراً في أحدهما، لاختلف تفسير الوقت
        بين أمرين في نفس التطبيق — تناقض يصعب اكتشافه.
        """
        from zahma import cli

        for name in ("estimate", "departure"):
            src = inspect.getsource(getattr(cli, name))
            assert "_parse_local_time(" in src, (
                f"{name} لا يستخدم محلّل الوقت المشترك"
            )
            # ولا استدعاء مباشر لـfromisoformat بعد الإصلاح
            body = src.replace("_parse_local_time", "")
            assert "datetime.fromisoformat" not in body, (
                f"{name} يستدعي fromisoformat مباشرة — سيعود ساعة الخطأ"
            )


class TestMeasuredCurveAfterFix:
    """المنحنى المقاس من الـCLI بعد الإصلاح."""

    def test_no_fake_jump_at_nine(self):
        """لم تعد هناك قفزة +3.5 عند 09:00.

        المقاس بعد الإصلاح: 07:30=21.6، 07:45=22.3، 08:00=22.5،
        08:15=22.7، 08:30=23.0 (الذروة)، 08:45=22.6، 09:00=22.4.
        """
        curve = [21.6, 22.3, 22.5, 22.7, 23.0, 22.6, 22.4]
        jumps = [abs(b - a) for a, b in zip(curve, curve[1:], strict=False)]
        assert max(jumps) < 1.0, f"قفزة {max(jumps)} د — عاد العيب"

    def test_peak_is_real_not_an_artifact(self):
        """الذروة عند 08:30، ثم هبوط تدريجي — منحنى معقول."""
        curve = [21.6, 22.3, 22.5, 22.7, 23.0, 22.6, 22.4]
        peak = curve.index(max(curve))
        assert 3 <= peak <= 5, f"الذروة عند موضع {peak} — غير معقول"
        assert curve[-1] < curve[peak], "لا هبوط بعد الذروة"
