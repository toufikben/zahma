"""استنزاف الطابور — الجزء الناقص الذي كان يجعل الحماية وهمية.

**العيبان اللذان يصلحهما هذا الملف:**

1. `queue.push` كان يُنادى عند فشل الكتابة، لكن `claim`/`ack`/`nack`
   **لم تُنادَ من أي مكان في المشروع**. النتيجة: عند انقطاع الشبكة أو
   سقوط Postgres كانت النتيجة تُكتب في SQLite ثم **لا يقرأها أحد أبداً**.
   البيانات لم تُفقد، لكنها لم تُستعد إما — وهذا أسوأ من الفقدان لأنه
   يبدو كأن هناك حماية.

2. الحمولة المحفوظة كانت `{"error", "meta"}` — **بلا عينات**. لا يمكن
   إعادة بنائها إلى صفوف. فالطابور كان يحتفظ بإشعار فشل لا ببيانات.
   أُصلح في `runner._run_source`: تُحفظ العينات كاملة الآن.

**التصميم:** استنزاف دوري في نفس حلقة المجمّع قبل كل دورة جمع.
نجاح ⇒ `ack` (حذف). فشل ⇒ `nack` (backoff أسّي، ثم `dead` بعد 5).

**عناصر `dead` لا تُحذف.** تبقى للمراجعة — إسقاطها صامتاً يعني إخفاء
فشل بدل معالجته.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from zahma.collect import queue
from zahma.collect.writer import write_result
from zahma.sources.base import RouteSample, SegmentSample, SourceResult


def _rebuild(payload: dict) -> SourceResult | None:
    """يعيد بناء SourceResult من الحمولة المحفوظة.

    يعيد `None` إن كانت الحمولة بلا عينات — أي أنها من نسخة قديمة من
    الكود تحفظ الخطأ فقط. لا ندّعي معالجتها.
    """
    segs_raw = payload.get("segment_samples") or []
    routes_raw = payload.get("route_samples") or []
    if not segs_raw and not routes_raw:
        return None

    segs = [
        SegmentSample(
            segment_id=int(s["segment_id"]),
            source=s["source"],
            ts_utc=datetime.fromisoformat(s["ts_utc"]),
            speed_kmh=s.get("speed_kmh"),
            freeflow_kmh=s.get("freeflow_kmh"),
            travel_time_s=s.get("travel_time_s"),
            confidence=s.get("confidence"),
            raw_ref=s.get("raw_ref"),
        )
        for s in segs_raw
    ]
    routes = [
        RouteSample(
            pair_id=int(r["pair_id"]),
            source=r["source"],
            ts_utc=datetime.fromisoformat(r["ts_utc"]),
            duration_s=r.get("duration_s"),
            distance_m=r.get("distance_m"),
            confidence=r.get("confidence"),
            segment_samples=[],
        )
        for r in routes_raw
    ]
    return SourceResult(
        source=segs[0].source if segs else routes[0].source,
        ok=True,
        fetched_at=datetime.now(UTC),
        segment_samples=segs,
        route_samples=routes,
    )


def drain(limit: int = 500) -> dict:
    """يفرّغ الطابور إلى Postgres. يعيد إحصاء ما حدث."""
    items = queue.claim(limit=limit)
    if not items:
        return {"claimed": 0, "written": 0, "retried": 0, "dead": 0, "empty": 0}

    written = retried = dead = empty = 0
    acked: list[int] = []

    for item_id, source, kind, payload_json in items:
        try:
            payload = json.loads(payload_json)
        except Exception as e:  # noqa: BLE001
            if queue.nack(item_id, f"bad json: {e}") == "dead":
                dead += 1
            else:
                retried += 1
            continue

        result = _rebuild(payload)
        if result is None:
            # حمولة قديمة بلا عينات. لا شيء لكتابته، ولا فائدة من
            # إبقائها. ننقلها إلى dead فوراً بصراحة.
            queue.nack(item_id, "no samples in payload", max_attempts=1)
            empty += 1
            continue

        try:
            write_result(result)
            acked.append(item_id)
            written += 1
        except Exception as e:  # noqa: BLE001
            if queue.nack(item_id, f"{type(e).__name__}: {e}") == "dead":
                dead += 1
            else:
                retried += 1

    if acked:
        queue.ack(acked)

    return {
        "claimed": len(items),
        "written": written,
        "retried": retried,
        "dead": dead,
        "empty": empty,
    }


def status() -> dict:
    """حالة الطابور للمراقبة."""
    return queue.stats()
