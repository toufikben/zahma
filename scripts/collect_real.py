"""جمع قياسات حقيقية من Mapbox عبر ساعات اليوم.

يستخدم `depart_at` فنسأل المزوّد عن تنبؤه لكل ساعة — لا ننتظر اليوم
ليمرّ. البيانات تُوسم `forecast` في `raw_ref` لأنها تنبؤ لا قياس آني.

التشغيل: python scripts/collect_real.py [--pairs 20] [--day 2026-11-30]
"""

from __future__ import annotations

import argparse
import time

from zahma.collect.match import collect

HOURS = [
    "05:30", "06:30", "07:00", "07:30", "08:00", "08:30",
    "09:00", "10:00", "12:00", "14:00", "16:30", "17:00",
    "17:30", "18:00", "18:30", "19:00", "21:00",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=20)
    ap.add_argument("--day", default="2026-11-30")
    ap.add_argument("--hours", default="")
    args = ap.parse_args()

    hours = args.hours.split(",") if args.hours else HOURS

    total_segs = 0
    total_routes = 0
    t0 = time.time()

    print(f"day={args.day} pairs={args.pairs} hours={len(hours)}")
    print(f"{'hour':>6}  {'segs':>7}  {'match':>6}  {'routes':>6}  {'km/h':>6}")

    for hh in hours:
        r = collect(
            limit_pairs=args.pairs, depart_at=f"{args.day}T{hh}"
        )
        segs = r.get("segments", 0)
        routes = r.get("routes", 0)
        total_segs += segs
        total_routes += routes
        print(
            f"{hh:>6}  {segs:>7}  {r.get('match_rate_pct', 0):>5.1f}%"
            f"  {routes:>6}"
        )

    elapsed = time.time() - t0
    print(
        f"\ntotal segments={total_segs} routes={total_routes} "
        f"in {elapsed:.0f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
