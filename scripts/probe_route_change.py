"""هل يتغيّر المسار نفسه بين شرائح الانطلاق؟ — مصدر القفزات الحقيقي.

**الفرضية:** `departure_curve` يستدعي `estimate_route` لكل شريحة، والراوتر
(Dijkstra) يختار المسار الأسرع حسب السرعات المتوقعة. فحين تكون شريحة ما
مبنية على استيفاء ووسيط صنف، قد يُختار مسار مختلف — فتقفز المدة لأن
**المسار تغيّر**، لا لأن الطريق ازدحم.

**كيف نتحقق:** نطبع لكل شريحة: المدة، عدد المقاطع، مجموع الأطوال، وعدد
المقاطع بكل أساس. لو تغيّر عدد المقاطع أو الطول، فالمسار يتغيّر.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from zahma.predict.engine import estimate_route

FROM = (36.7167, 3.1833)  # باب الزوار
TO = (36.7705, 3.0589)    # وسط الجزائر
BASE = datetime(2026, 12, 15, 6, 30, tzinfo=UTC)


def main() -> int:
    print(f"{'الوقت':>6}  {'دقيقة':>7}  {'p90':>6}  {'ثقة':>5}  الأساس")
    print("-" * 74)

    prev_dur = None
    prev_basis = None
    rows = []
    for m in range(0, 106, 15):
        t = BASE + timedelta(minutes=m)
        est = estimate_route(*FROM, *TO, when=t, now=BASE)
        d = est.duration_s / 60
        basis = dict(est.basis_counts or {})
        total_segs = sum(basis.values())
        delta = "" if prev_dur is None else f"  ({d - prev_dur:+.2f})"
        changed = ""
        if prev_basis is not None and basis != prev_basis:
            changed = "  ← الأساس تغيّر"
        print(
            f"{t:%H:%M}  {d:>7.2f}  {est.duration_p90_s / 60:>6.2f}  "
            f"{est.confidence:>5.2f}  {basis}{delta}{changed}"
        )
        rows.append((t, d, total_segs, basis))
        prev_dur = d
        prev_basis = basis

    print()
    print("── هل تغيّر عدد المقاطع؟")
    counts = {r[2] for r in rows}
    print(f"  أعداد مختلفة: {sorted(counts)}")
    if len(counts) > 1:
        print("  ⇒ **المسار يتغيّر بين الشرائح.** القفزات من اختيار مسار")
        print("     مختلف، لا من ازدحام. وهذا يجعل المنحنى غير قابل للمقارنة:")
        print("     كل نقطة تقيس رحلة مختلفة.")
    else:
        print("  ⇒ المسار ثابت — القفزات من السرعات وحدها.")

    print()
    print("── هل توزيع الأساس ثابت؟")
    dists = {tuple(sorted(r[3].items())) for r in rows}
    print(f"  توزيعات مختلفة: {len(dists)}")
    for d in sorted(dists):
        print(f"    {dict(d)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
