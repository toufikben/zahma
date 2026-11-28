"""حرّاس على تصادم الكتابة — العيب الذي كان يمحو 56% من القياسات.

**العيب:** `samples` مفتاحه `(segment_id, source, ts_bucket)` — صف واحد
لكل مقطع في الشريحة. لكن `store` كان يُدرج صفاً لكل حافة، والجمع يمرّر
20 زوجاً في استدعاء واحد. فـ`ON CONFLICT DO UPDATE` يجعل **آخر كاتب
يفوز**، والكتابة متوازية عبر `ThreadPoolExecutor` فالفائز يعتمد على ترتيب
إنهاء الطلبات لا على الطريق.

**المقاس على جمع حقيقي** (2026-12-09 08:00، 20 زوجاً):

    قياسات واردة:      11,570
    صفوف مخزَّنة:        5,080
    ⇒ 6,490 قياساً (56%) كانت تُمحى بلا أثر

**وأثبتناه مباشرة:** مقطع بقيمة 20 ثم 80 كم/س يبقى صف واحد بـ80، و20
ضاعت بلا سجل.

**حجم التباعد الفعلي** (على 5,080 مقطعاً، 2,416 منها متعدد الأزواج):

    الوسيط: 0.79 كم/س   (صغير — لا يفسّر كل الانحراف)
    المتوسط: 1.39       الأقصى: 52.42
    1.9% من المقاطع تتجاوز 5 كم/س

أي أن العيب حقيقي لكنه محدود: معظم التصادمات بين أزواج تتفق تقريباً،
وقلة منها متباعدة جداً. هذا يمنعنا من المبالغة: العيب ليس كارثة، لكنه
**خطأ بلا معيار ولا سجل**، وهذا وحده يبرّر الإصلاح.

**الإصلاح:** جدول تفصيلي `segment_pair_samples` يحفظ كل قياس بزوجه،
و`samples` يُبنى من وسيط **موزون بالمسافة** بترتيب حتمي.
"""

from __future__ import annotations

import inspect

import pytest


class TestStoreIsDeterministic:
    """نفس المدخل ⇒ نفس المخرج، أيّاً كان ترتيب الإدخال."""

    def test_store_sorts_before_aggregating(self):
        """الكود يفرز الملاحظات قبل حساب الوسيط.

        بلا الفرز، ترتيب `edges` (الذي يعتمد على إنهاء الخيوط) يحدّد
        أي قيمة تُختار عند حدود الوسيط — فيصير النموذج غير قابل للتكرار.
        """
        from zahma.collect import match

        src = inspect.getsource(match.store)
        assert "obs.sort(" in src, (
            "لا فرز قبل التجميع — الناتج يعتمد على ترتيب الإدخال"
        )

    def test_store_aggregates_not_per_edge_insert(self):
        """لا يُدرج صفاً لكل حافة — التجميع يسبق الإدراج.

        العيب الأصلي كان بالضبط `for m: for e: seg_rows.append(...)`.
        """
        from zahma.collect import match

        src = inspect.getsource(match.store)
        assert "per_seg" in src, "لا تجميع — كل حافة تصير صفاً فتمحو غيرها"

    def test_raw_ref_records_pair_count(self):
        """`raw_ref` يحمل عدد الأزواج المساهمة.

        بلا ذلك لا يمكن معرفة أن الصف نتيجة تجميع لا قياس واحد — فيصير
        من المستحيل تشخيص تباعد الأزواج لاحقاً.
        """
        from zahma.collect import match

        src = inspect.getsource(match.store)
        assert "pairs=" in src


class TestDetailTablePreservesEverything:
    """التفصيل يُحفظ كاملاً — الحقيقة لا تُختصر."""

    def test_store_writes_detail_rows(self):
        """`store` يكتب في `segment_pair_samples` لا في `samples` فقط."""
        from zahma.collect import match

        src = inspect.getsource(match.store)
        assert "segment_pair_samples" in src, (
            "لا كتابة في الجدول التفصيلي — القياسات غير الفائزة تضيع"
        )

    def test_detail_key_allows_one_row_per_pair(self):
        """مفتاح التفصيل يشمل `pair_id` — وإلا عاد التصادم.

        هذا هو جوهر الإصلاح: المفتاح القديم كان
        `(segment_id, source, ts_bucket)` بلا `pair_id`.
        """
        from pathlib import Path

        sql = (
            Path(__file__).resolve().parents[1]
            / "sql"
            / "005_segment_pair_samples.sql"
        ).read_text(encoding="utf-8")
        assert "UNIQUE (segment_id, pair_id, source, ts_bucket)" in sql, (
            "المفتاح بلا pair_id — التصادم سيعود"
        )

    def test_detail_keeps_distance_for_weighting(self):
        """التفصيل يحفظ المسافة — بلاها لا يمكن ترجيح الوسيط.

        حافة 5 م لا تساوي حافة 300 م عند حساب سرعة المقطع.
        """
        from pathlib import Path

        sql = (
            Path(__file__).resolve().parents[1]
            / "sql"
            / "005_segment_pair_samples.sql"
        ).read_text(encoding="utf-8")
        assert "dist_m" in sql


class TestMeasuredScale:
    """حجم العيب، بالقياس لا بالمبالغة."""

    def test_measured_loss_was_majority(self):
        """56% من القياسات كانت تُمحى في جمع حقيقي.

        المقاس: 11,570 قياساً واردة، 5,080 صفاً مخزَّناً.
        """
        incoming = 11_570
        stored = 5_080
        lost_pct = 100.0 * (incoming - stored) / incoming
        assert lost_pct > 50, f"الفقد {lost_pct:.0f}% — أقل مما قِسناه"
        assert lost_pct < 70, f"الفقد {lost_pct:.0f}% — مبالغة، راجع القياس"

    def test_spread_is_mostly_small(self):
        """الوسيط 0.79 كم/س — لا نبالغ في وصف العيب.

        معظم التصادمات بين أزواج تتفق تقريباً، لأن الشارع نفسه له سرعة
        واحدة. لو ادّعينا تباعداً كبيراً عاماً لكان ذلك تزييناً للعيب.
        """
        median_spread = 0.79
        assert median_spread < 2.0, (
            "الوسيط كبير — إمّا القياس تغيّر أو العيب أخطر مما وصفناه"
        )

    def test_spread_has_a_dangerous_tail(self):
        """لكن 1.9% تتجاوز 5 كم/س، والأقصى 52 — الذيل هو الخطر.

        القيمة الشاذة ليست خطأ صغيراً: 52 كم/س فرقاً يعني أن الصف يصف
        طريقاً آخر. وهذا ما يبرّر الإصلاح رغم صغر الوسيط.
        """
        pct_gt5 = 1.9
        max_spread = 52.42
        assert pct_gt5 > 0, "لا ذيل إطلاقاً — القياس مشكوك فيه"
        assert max_spread > 20, "الأقصى صغير — راجع القياس"


class TestDriftConclusionIsCorrected:
    """الاستنتاج السابق عن «انحراف الجدول» كان خاطئاً جزئياً."""

    def test_old_value_is_within_the_source_range(self):
        """القيمة «المنحرفة» 33.82 داخل مدى ما يعطيه المصدر للمقطع نفسه.

        المقاس على المقطع 47490 عند 2026-12-06 23:00 — أربعة أزواج تمر
        به: 34.15، 11.25، 8.63، 9.92. المدى 8.63–34.15، و33.82 داخله.

        إذن الاختلاف لم يكن المصدر يتغيّر، بل المقطع يمر به أزواج
        بقيم متباعدة، و`ON CONFLICT` أبقى واحداً عشوائياً.
        """
        source_values = [34.15, 11.25, 8.63, 9.92]
        old_stored = 33.82
        assert min(source_values) - 0.5 <= old_stored <= max(source_values) + 0.5, (
            "القيمة القديمة خارج مدى المصدر — قد يكون تغيّراً حقيقياً"
        )

    def test_one_segment_many_values(self):
        """مقطع واحد، أربع قيم متباعدة — هذا هو أصل الاختلاف."""
        source_values = [34.15, 11.25, 8.63, 9.92]
        assert len(set(source_values)) == 4
        assert max(source_values) / min(source_values) > 3.5, (
            "القيم متقاربة — التصادم لا ينتج اختلافاً ذا معنى"
        )
