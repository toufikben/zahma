"""هل الصف المخزَّن لـ2026-12-06 23:00 جمع مساراً مختلفاً؟

**ما نعرفه:** 143 مقطعاً من 191 انحرفت في تلك الخانة، بمتوسط 3.1 كم/س،
وأكبرها 23.9. والمخزَّن فيه 105 مقطعاً فوق 60 كم/س (متوسط 61.66).

**السؤال:** هل الرد الآن مختلف، أم أن الصف المخزَّن جُمع بمدخل مختلف
(مسار آخر أو وقت آخر)؟ الفرق حاسم: الأول يعني أن المصدر تغيّر، والثاني
يعني أن جمعنا كتب صفاً لا يطابق مدخله.
"""

from __future__ import annotations

import httpx

from zahma.collect.match import measure_pair
from zahma.config import get_settings
from zahma.db import session_scope
from sqlalchemy import text

SLOT = "2026-12-06T23:00"
PAIR = 15


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
        stored = ss.execute(
            text(
                """
                SELECT segment_id, speed_kmh
                FROM samples
                WHERE source::text = 'mapbox' AND speed_kmh IS NOT NULL
                  AND split_part(raw_ref, ';', 1) = :p
                  AND ts_bucket >= '2026-12-06 22:00:00+01'
                  AND ts_bucket <  '2026-12-07 01:00:00+01'
                """
            ),
            {"p": f"pair={PAIR}"},
        ).all()

    pair = {
        "pair_id": p["pair_id"],
        "from": (p["flat"], p["flon"]),
        "to": (p["tlat"], p["tlon"]),
    }
    with httpx.Client(timeout=30) as client:
        m = measure_pair(client, s.mapbox_token, pair, depart_at=SLOT)
    fresh = {e.seg_id: e.speed_kmh for e in m.edges}
    old = {int(r[0]): float(r[1]) for r in stored}

    def stats(d: dict[int, float], label: str) -> None:
        vals = list(d.values())
        if not vals:
            print(f"  {label}: لا قيم")
            return
        print(
            f"  {label}: n={len(vals)}  min={min(vals):.1f}  "
            f"avg={sum(vals)/len(vals):.1f}  max={max(vals):.1f}  "
            f"over60={sum(1 for v in vals if v > 60)}"
        )

    print(f"الخانة {SLOT} — الزوج {PAIR}")
    stats(old, "مخزَّن")
    stats(fresh, "الآن  ")

    common = set(old) & set(fresh)
    print(f"  مشترك: {len(common)}")
    print(f"  حواف الرد الآن: {len(m.edges)}، مطابق {m.matched}، غير مطابق {m.unmatched}")
    print(f"  مدة المسار الآن: {m.duration_s:.1f} ث")

    # هل المخزَّن يطابق رحلة أطول/أقصر؟
    with session_scope() as ss:
        rs = ss.execute(
            text(
                """
                SELECT duration_s, distance_m
                FROM route_samples
                WHERE source::text = 'mapbox' AND pair_id = :p
                  AND ts_bucket >= '2026-12-06 22:00:00+01'
                  AND ts_bucket <  '2026-12-07 01:00:00+01'
                """
            ),
            {"p": PAIR},
        ).first()
    if rs:
        print(f"  مخزَّن: مدة {rs[0]:.1f} ث، مسافة {rs[1]:.0f} م")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
