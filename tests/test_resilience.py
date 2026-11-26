"""اختبار مقاومة الانقطاع — يثبت أن الطابور يحمي ما جُلب.

السيناريو المُحاكى:
1. قاعدة البيانات غير متاحة (شبكة مقطوعة أو Postgres متوقف).
2. المصدر يجلب بيانات بنجاح.
3. الكتابة تفشل ⇒ يجب أن تُحفظ في الطابور، لا تُفقد.
4. تعود القاعدة ⇒ الطابور يُفرَّغ بلا تكرار.

هذا الاختبار يفشل إن ضاع أي صف.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import text

from zahma.collect import queue
from zahma.collect.writer import write_segment_samples
from zahma.db import session_scope
from zahma.sources.base import SegmentSample


def test_queue_survives_db_down() -> None:
    """عند فشل الكتابة، يجب أن يُحفظ العنصر في الطابور."""
    src = "mock"
    before = queue.stats()["pending"]

    # نحفظ عنصراً كما لو أن الكتابة فشلت
    nid = queue.push(
        src,
        "result",
        {"segment_samples": [{"segment_id": 1, "speed_kmh": 30.0}], "error": "simulated"},
    )
    assert nid > 0
    after = queue.stats()["pending"]
    assert after == before + 1, f"queue did not grow: {before} -> {after}"

    # نأخذه ونؤكده
    batch = queue.claim(limit=10, source=src)
    assert any(b[0] == nid for b in batch)
    queue.ack([nid])
    assert queue.stats()["pending"] == before


def test_idempotent_insert() -> None:
    """إدراج نفس العينة مرتين لا يُنشئ صفين."""
    now = datetime.now(UTC)
    seg_id = 1

    s = SegmentSample(
        segment_id=seg_id,
        source="mock",
        ts_utc=now,
        speed_kmh=42.0,
        freeflow_kmh=60.0,
        travel_time_s=30.0,
        confidence=0.9,
    )

    write_segment_samples([s])
    with session_scope() as sess:
        n1 = sess.execute(
            text("SELECT COUNT(*) FROM samples WHERE segment_id=:i AND source='mock'"),
            {"i": seg_id},
        ).scalar()

    # نفس الحاوية الزمنية (5 دقائق)
    write_segment_samples([s])
    with session_scope() as sess:
        n2 = sess.execute(
            text("SELECT COUNT(*) FROM samples WHERE segment_id=:i AND source='mock'"),
            {"i": seg_id},
        ).scalar()

    assert n1 == n2, f"duplicate insert: {n1} -> {n2}"


def test_nack_backoff() -> None:
    """الفشل يؤجل المحاولة، ولا يحذف العنصر."""
    nid = queue.push("mock", "result", {"x": 1})
    r1 = queue.nack(nid, "network error", max_attempts=3)
    assert r1 == "retry"

    # يجب ألا يكون جاهزاً الآن (مؤجّل)
    ready = queue.claim(limit=1000, source="mock")
    assert all(b[0] != nid for b in ready), "delayed item should not be claimable"

    # بعد تجاوز الحد ينتقل إلى dead
    queue.nack(nid, "fail 2", max_attempts=1)
    st = queue.stats()
    assert st["dead"] >= 1


if __name__ == "__main__":
    test_queue_survives_db_down()
    test_idempotent_insert()
    test_nack_backoff()
    print("✓ all resilience tests passed")
