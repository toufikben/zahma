"""نسبة أمان الملء على نطاق أوسع: 3 أزواج × 4 ساعات.

**السؤال:** إذا فات تشغيل cron وملأناه لاحقاً بـ`depart_at` ماضٍ، هل نحصل
على ما كان المصدر سيعطيه وقتها؟

الاختبار: نأخذ صفوفاً خزّنّاها فعلاً، ونسحب نفس `depart_at` الآن، ونقارن
مقطعاً بمقطع. النسبة الناتجة هي الجواب العددي.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text

from zahma.collect.match import measure_pair
from zahma.config import get_settings
from zahma.db import session_scope

PAIRS = [15, 3, 7]
SLOTS = [
    "2026-12-02T03:00",
    "2026-12-02T08:00",
    "2026-12-04T17:00",
    "2026-12-06T23:00",
]


def pair_coords(pid: int) -> dict:
    with session_scope() as ss:
        p = ss.execute(
            text(
                """
                SELECT pair_id, ST_Y(from_pt) flat, ST_X(from_pt) flon,
                       ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                FROM od_pairs WHERE pair_id = :p
                """
            ),
            {"p": pid},
        ).mappings().one()
    return {
        "pair_id": p["pair_id"],
        "from": (p["flat"], p["flon"]),
        "to": (p["tlat"], p["tlon"]),
    }


def stored_for(pid: int, depart: str) -> dict[int, float]:
    local = depart.replace("T", " ")
    with session_scope() as ss:
        rows = ss.execute(
            text(
                """
                SELECT segment_id, speed_kmh
                FROM samples
                WHERE source::text = 'mapbox' AND speed_kmh IS NOT NULL
                  AND split_part(raw_ref, ';', 1) = :p
                  AND ts_bucket >= (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                  AND ts_bucket <  (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                                   + interval '5 minutes'
                """
            ),
            {"p": f"pair={pid}", "d": local},
        ).all()
    return {int(r[0]): float(r[1]) for r in rows}


def main() -> int:
    s = get_settings()
    print(f"{len(PAIRS)} أزواج × {len(SLOTS)} ساعات")
    print()

    grand = {"seg": 0, "exact": 0, "close": 0, "bad_slots": 0, "slots": 0}

    for pid in PAIRS:
        pair = pair_coords(pid)
        for slot in SLOTS:
            old = stored_for(pid, slot)
            if not old:
                print(f"  pair={pid} {slot}: لا صفوف، تخطٍّ")
                continue
            with httpx.Client(timeout=30) as client:
                m = measure_pair(client, s.mapbox_token, pair, depart_at=slot)
            if m is None:
                print(f"  pair={pid} {slot}: فشل السحب")
                continue
            new = {e.seg_id: e.speed_kmh for e in m.edges}
            common = set(old) & set(new)
            if not common:
                continue
            exact = sum(1 for k in common if abs(old[k] - new[k]) < 0.005)
            close = sum(1 for k in common if abs(old[k] - new[k]) < 0.5)
            pe = 100.0 * exact / len(common)

            grand["seg"] += len(common)
            grand["exact"] += exact
            grand["close"] += close
            grand["slots"] += 1
            if pe < 99.0:
                grand["bad_slots"] += 1

            flag = "" if pe > 99.0 else "  ← انحراف"
            print(
                f"  pair={pid} {slot}: {len(common):>4} مقطع | "
                f"مطابق {pe:>6.2f}%{flag}"
            )

    print()
    if grand["seg"]:
        print(
            f"الإجمالي: {grand['seg']:,} مقطع-قياس على {grand['slots']} خانة | "
            f"مطابق تماماً {100.0 * grand['exact'] / grand['seg']:.2f}% | "
            f"ضمن 0.5 كم/س {100.0 * grand['close'] / grand['seg']:.2f}%"
        )
        print(f"خانات منحرفة (>1%): {grand['bad_slots']} من {grand['slots']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
