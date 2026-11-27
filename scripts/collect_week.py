"""جمع بيانات حقيقية لعدة أيام وساعات — حتى تصلح ملفات التعريف.

**المشكلة التي يحلّها:** ملفات التعريف تحتاج 3 عينات على الأقل في نفس
الشريحة الزمنية (نفس المقطع، نفس النصف ساعة، نفس نوع اليوم). جمع يوم
واحد بالساعة يعطي عينة واحدة لكل شريحة — فتُبنى الملفات فارغة.

جمع 7 أيام × 17 ساعة يعطي 7 عينات لكل شريحة. هذا هو الحد الأدنى
الحقيقي لملف تعريف ذي معنى إحصائي.

**الحصة:** 7 أيام × 17 ساعة × 20 زوجاً = 2,380 طلباً. حصة Mapbox
100,000 شهرياً. أي 2.4%.

التشغيل: python scripts/collect_week.py --days 7 --pairs 20
"""

from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

from zahma.collect.match import collect

HOURS = [
    "05:30", "06:30", "07:00", "07:30", "08:00", "08:30",
    "09:00", "10:00", "12:00", "14:00", "16:30", "17:00",
    "17:30", "18:00", "18:30", "19:00", "21:00",
]


def next_monday(start: date) -> date:
    """أقرب يوم اثنين — يمثّل يوم عمل عادي في التقويم الجزائري."""
    d = start
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--pairs", type=int, default=20)
    ap.add_argument("--start", default="")
    ap.add_argument("--skip-weekend", action="store_true", default=True)
    args = ap.parse_args()

    start = (
        date.fromisoformat(args.start) if args.start else next_monday(date.today())
    )

    days: list[date] = []
    d = start
    while len(days) < args.days:
        # نتخطى الجمعة والسبت: سلوكهما مختلف جذرياً في الجزائر،
        # ويحتاجان ملفات تعريف منفصلة تُجمع لاحقاً.
        if not args.skip_weekend or d.weekday() not in (4, 5):
            days.append(d)
        d += timedelta(days=1)

    total_requests = len(days) * len(HOURS) * args.pairs
    print(
        f"days={len(days)} ({days[0]} .. {days[-1]}) hours={len(HOURS)} "
        f"pairs={args.pairs}"
    )
    print(f"estimated requests: {total_requests:,} (quota 100,000/month)")
    print()

    t0 = time.time()
    total_segs = 0
    total_routes = 0

    for day in days:
        for hh in HOURS:
            r = collect(
                limit_pairs=args.pairs, depart_at=f"{day}T{hh}"
            )
            segs = r.get("segments", 0)
            total_segs += segs
            total_routes += r.get("routes", 0)
        print(
            f"{day} {day.strftime('%a')}  done  "
            f"({time.time() - t0:.0f}s elapsed)"
        )

    print(
        f"\ntotal segments={total_segs:,} routes={total_routes:,} "
        f"in {time.time() - t0:.0f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
