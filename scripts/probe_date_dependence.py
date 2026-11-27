"""الاختبار الحاسم: هل قيمة المقطع تعتمد على تاريخ `depart_at`؟

القاعدة تُظهر نمطاً لا يمكن أن يكون ضجيجاً على المقطع 47490 عند 03:00:

    2026-11-30  38.16      2026-12-04  20.68
    2026-12-01  38.16      2026-12-05  13.04
    2026-12-02  38.16      2026-12-06  11.57
    2026-12-03  22.00      2026-12-07  38.16
                           2026-12-08  38.16

تدرّج 22 → 20.68 → 13.04 → 11.57 ثم عودة حادة إلى 38.16. هذا توقيع
مكوّن حي: القيمة تتبع حالة الطريق وقت **الجمع**، لا وقت `depart_at`.

**لماذا فشل استدلالي السابق:** قارنت تواريخ في نفس الثانية، فحصلت على
تطابق. لكن إن كان المصدر يخلط الجدول النموذجي بحالة حية، فالمقارنة
الفورية لا تكشفه — تحتاج مقارنة عبر أيام حقيقية مختلفة، وهو ما تفعله
هذه الأداة: تستدعي نفس `depart_at` الآن، وتقارنه بما خُزِّن سابقاً.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text

from zahma.collect.match import measure_pair
from zahma.config import get_settings
from zahma.db import session_scope

SEG = 47490
PAIR = 15


def stored_by_day(hour: int) -> dict[str, float]:
    with session_scope() as ss:
        rows = ss.execute(
            text(
                """
                SELECT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers', 'YYYY-MM-DD'),
                       speed_kmh
                FROM samples
                WHERE segment_id = :s AND source::text = 'mapbox'
                  AND extract(hour FROM ts_bucket AT TIME ZONE 'Africa/Algiers')::int = :h
                ORDER BY ts_bucket
                """
            ),
            {"s": SEG, "h": hour},
        ).all()
    return {r[0]: r[1] for r in rows}


def main() -> int:
    s = get_settings()
    with session_scope() as ss:
        p = ss.execute(
            text(
                """
                SELECT pair_id, ST_Y(from_pt) flat, ST_X(from_pt) flon,
                       ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                FROM od_pairs WHERE pair_id = :p
                """
            ),
            {"p": PAIR},
        ).mappings().one()
    pair = {
        "pair_id": p["pair_id"],
        "from": (p["flat"], p["flon"]),
        "to": (p["tlat"], p["tlon"]),
    }

    for hour in (3, 23):
        print(f"══ الساعة {hour:02d}:00 — المقطع {SEG}")
        db = stored_by_day(hour)
        print("  المخزَّن (وقت الجمع الأصلي):")
        for d, v in db.items():
            print(f"    {d}  {v}")

        print("  الآن، بنفس depart_at لكل تاريخ:")
        fresh = {}
        for d in db:
            with httpx.Client(timeout=30) as client:
                m = measure_pair(
                    client, s.mapbox_token, pair, depart_at=f"{d}T{hour:02d}:00"
                )
            v = {e.seg_id: e.speed_kmh for e in m.edges}.get(SEG) if m else None
            fresh[d] = v
            mark = "=" if v is not None and abs(v - db[d]) < 0.05 else "≠"
            print(f"    {d}  {v}   {mark}")

        distinct_fresh = len({round(v, 2) for v in fresh.values() if v is not None})
        distinct_db = len({round(v, 2) for v in db.values()})
        print()
        print(f"  قيم الآن: {distinct_fresh} قيمة مختلفة")
        print(f"  قيم مخزَّنة: {distinct_db} قيمة مختلفة")
        if distinct_fresh == 1 and distinct_db > 1:
            print("  ⇒ المصدر يعيد رقماً واحداً الآن، لكنه أعطى أرقاماً")
            print("     مختلفة وقت الجمع ⇒ مكوّن حي. الملء يعيد حالة")
            print("     اللحظة الحالية لا حالة الساعة الفائتة.")
        elif distinct_fresh > 1:
            print("  ⇒ التاريخ نفسه يغيّر الرقم ⇒ الجدول يعتمد على التاريخ.")
        else:
            print("  ⇒ متطابق. لا مكوّن حي في هذا المقطع.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
