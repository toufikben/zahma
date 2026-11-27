"""ساعات الجمع الليلية — القياس يحدّدها لا العادة.

**ما قاسه `night_probe.py`** (20 زوجاً، يوم عمل، مباشرة من API):

    21:00  53.6 كم/س     06:00  61.2
    22:30  55.9          08:00  49.7
    23:59  64.0          17:00  42.5
    01:00  66.6
    02:00  67.1
    03:00  67.9
    04:00  68.2  ← الأعلى
    05:00  66.4

**الحقيقة الأولى:** الليل مختلف فعلاً — 68.2 مقابل 42.5 في الذروة
المسائية، أي **+60%**. من يقول «لا زحمة ليلاً فلا داعي للقياس» يخلط بين
«لا زحمة» و«لا معلومة». الرقم نفسه معلومة: هو ما يجعل «اخرج الآن» قابلاً
للإجابة ليلاً.

**الحقيقة الثانية:** المنحنى **مسطّح** بين 23:59 و05:00 (64 → 68 → 66).
فلا معنى لجمع كل ساعة. ساعتان تكفيان: منتصف الليل و03:00.

**الحقيقة الثالثة:** الجمع الحالي يتوقف عند 21:00، فيفوّت الشريحة التي
تحمل أعلى سرعة وأكبر فرق عن الذروة. هذا نقص حقيقي لا اختيار.

**لكن:** هل يهم المستخدم؟ المستخدم قال إن الزحمة بعد منتصف الليل نادرة
إلا رمضان والمواسم. هذا صحيح، **ولا يتعارض** مع الجمع الليلي. الجمع
الليلي لا يخدم «الزحمة الليلية» — يخدم:
1. **السفر بين الولايات** (الجزائر ← وهران/قسنطينة يبدأ ليلاً).
2. **رمضان** حيث السهرة بعد الإفطار حتى 02:00–03:00 حركة حقيقية.
3. **الأعراس والمواسم** (صيف، أعياد) حيث الليل يزحم فعلاً.
4. **خط الأساس**: بلا قياس ليلي لا نعرف كم «طبيعي» لنقول إن الليلة
   غير طبيعية.

التشغيل: python scripts/collect_night.py [--day 2026-12-09]
"""

from __future__ import annotations

import argparse
import time

from zahma.collect.match import collect

# ساعتان فقط — المنحنى مسطّح، والزيادة بلا معلومة جديدة.
# 23:59 لا 00:00: منتصف الليل بالضبط يقع على حدّ اليوم، وقد يُحسب
# ليوم مختلف. 23:59 داخل اليوم المطلوب بلا التباس.
NIGHT_HOURS = ["23:59", "03:00"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=20)
    ap.add_argument("--day", default="2026-12-09")
    ap.add_argument("--hours", default="")
    args = ap.parse_args()

    hours = args.hours.split(",") if args.hours else NIGHT_HOURS

    total_segs = 0
    total_routes = 0
    t0 = time.time()

    print(f"day={args.day} pairs={args.pairs} hours={hours}")

    for hh in hours:
        # 03:00 يخصّ اليوم التالي فعلياً في تسلسل زمني، لكن `depart_at`
        # يأخذ التاريخ والوقت معاً، فنمرّر نفس اليوم للتوثيق الواضح.
        r = collect(limit_pairs=args.pairs, depart_at=f"{args.day}T{hh}")
        segs = r.get("segments", 0)
        routes = r.get("routes", 0)
        total_segs += segs
        total_routes += routes
        print(
            f"   {hh}  segs={segs:>7,}  match={r.get('match_rate_pct', 0):>5.1f}%"
            f"  routes={routes}"
        )

    elapsed = time.time() - t0
    print(f"\ntotal segments={total_segs:,} routes={total_routes} in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
