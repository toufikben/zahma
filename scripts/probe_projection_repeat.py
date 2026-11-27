"""هل كود الإسقاط الحالي يعيد نفس قيمة القاعدة؟

نشغّل `measure_pair` بنفس `depart_at` الذي جمعناه سابقاً، ونقارن ما
يعطيه الآن بما هو مخزَّن. الفرق يكشف: هل تغيّر الكود بين الجمعين، أم
أن الإسقاط نفسه غير حتمي؟
"""

from __future__ import annotations

import httpx

from zahma.collect.match import measure_pair
from zahma.config import get_settings
from zahma.db import session_scope
from sqlalchemy import text


def stored(seg_id: int, depart_at: str) -> list[tuple]:
    with session_scope() as ss:
        return ss.execute(
            text(
                """
                SELECT ts_bucket AT TIME ZONE 'Africa/Algiers', speed_kmh, raw_ref
                FROM samples
                WHERE segment_id = :s AND source::text = 'mapbox'
                  AND ts_bucket >= (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                  AND ts_bucket <  (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers') + interval '1 hour'
                ORDER BY ts_bucket
                """
            ),
            {"s": seg_id, "d": depart_at},
        ).all()


def main() -> int:
    s = get_settings()
    with session_scope() as ss:
        pair = ss.execute(
            text(
                """
                SELECT pair_id, ST_Y(from_pt) flat, ST_X(from_pt) flon,
                       ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                FROM od_pairs WHERE pair_id = 15
                """
            )
        ).mappings().one()
    p = {
        "pair_id": pair["pair_id"],
        "from": (pair["flat"], pair["flon"]),
        "to": (pair["tlat"], pair["tlon"]),
    }

    for depart in ("2026-11-29T23:00", "2026-12-06T23:00", "2026-11-29T03:00"):
        print(f"── depart_at = {depart}")
        old = stored(47490, depart)
        print(f"   مخزَّن: {[(str(r[0])[11:16], r[1]) for r in old]}")

        with httpx.Client(timeout=30) as client:
            m = measure_pair(client, s.mapbox_token, p, depart_at=depart)
        if m is None:
            print("   الآن: فشل القياس")
            continue
        now = {e.seg_id: e.speed_kmh for e in m.edges}
        print(f"   الآن  : {now.get(47490)}")
        print(f"   حواف: {len(m.edges)}، مطابق {m.matched}، غير مطابق {m.unmatched}")

        if old:
            diff = abs((old[0][1] or 0) - (now.get(47490) or 0))
            verdict = "مطابق" if diff < 0.05 else f"مختلف بـ{diff:.2f}"
            print(f"   ⇒ {verdict}")
        print()

    # هل الإسقاط حتمي؟ نكرّره 3 مرات.
    print("── حتمية الإسقاط (3 تكرارات، نفس المدخل)")
    vals = []
    for _ in range(3):
        with httpx.Client(timeout=30) as client:
            m = measure_pair(client, s.mapbox_token, p, depart_at="2026-11-29T23:00")
        vals.append({e.seg_id: e.speed_kmh for e in m.edges}.get(47490))
    print(f"   {vals}")
    print(f"   ⇒ {'حتمي' if len(set(vals)) == 1 else 'غير حتمي'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
