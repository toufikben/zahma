"""هل تذبذب المنحنى حقيقي أم أثر اختلاف المصدر بين الشرائح؟

**المشكلة المقاسة:** منحنى الانطلاق من 06:30 إلى 08:30:

    21.59 ← 24.00 ← 25.08 ← 24.29 ← 21.53 دقيقة

صعود ثم هبوط. والذروة عند 07:30 معقولة (ذروة صباحية حقيقية). لكن الهبوط
من 25.08 إلى 21.53 في نصف ساعة = **2.8 دقيقة**، بينما السرعة المطابقة
تتغيّر 2.7% فقط (42.15 ← 43.29 كم/س). فرق 11% في المدة مقابل 2.7% في
السرعة لا يتوافق.

**الفرضية:** المنحنى لا يُحسب على نفس المقاطع في كل شريحة. فحين تكون
الشريحة مقيسة بملف تعريف، تُستخدم سرعتها؛ وحين لا تكون، يُستخدم وسيط
الصنف. فالمدة تتغيّر لأن **مصدر البيانات** يتغيّر، لا لأن الطريق يتغيّر.

**كيف نتحقق:** نطبع لكل خيار في المنحنى عدد المقاطع بكل أساس
(profile/class/freeflow). إن اختلف التوزيع بين الشرائح، فالفرضية مؤكدة.
"""

from __future__ import annotations

from datetime import UTC, datetime

from zahma.predict.engine import departure_curve

ROUTE = (36.7167, 3.1833, 36.7705, 3.0589)
WHEN = datetime(2026, 11, 29, 6, 30, tzinfo=UTC)


def main() -> int:
    curve = departure_curve(
        *ROUTE, now=WHEN, horizon_min=120, step_min=15
    )
    print("المنحنى بدقة 15 دقيقة — الأساس لكل خيار:")
    print()
    print(f"{'الوقت':>6}  {'دقيقة':>7}  {'ثقة':>5}  الأساس")
    print("-" * 62)
    prev = None
    for o in curve:
        b = getattr(o, "basis_counts", {}) or {}
        src = " ".join(f"{k}={v}" for k, v in sorted(b.items())) or "—"
        delta = "" if prev is None else f"  ({o.duration_s / 60 - prev:+.2f})"
        print(
            f"{o.depart_at:%H:%M}  {o.duration_s / 60:>7.2f}  "
            f"{o.confidence:>5.2f}  {src}{delta}"
        )
        prev = o.duration_s / 60

    print()
    # هل توزيع الأساس ثابت؟
    dists = [
        tuple(sorted((getattr(o, "basis_counts", {}) or {}).items()))
        for o in curve
    ]
    uniq = set(dists)
    print(f"توزيعات أساس مختلفة: {len(uniq)}")
    if len(uniq) > 1:
        print("⇒ **الفرضية مؤكدة.** المنحنى يخلط مصادر مختلفة بين الشرائح.")
        print("   المدة تتغيّر لأن مصدر البيانات يتغيّر، لا لأن الطريق يتغيّر.")
        print("   وهذا يُنتج تذبذباً غير موجود في الواقع.")
    else:
        print("⇒ التوزيع ثابت — التذبذب من البيانات نفسها لا من اختلاف المصدر.")

    # الفرق الأقصى بين خيارين متتاليين
    durs = [o.duration_s / 60 for o in curve]
    if len(durs) > 1:
        jumps = [
            (durs[i + 1] - durs[i], curve[i].depart_at)
            for i in range(len(durs) - 1)
        ]
        jumps.sort(key=lambda x: abs(x[0]), reverse=True)
        print()
        print("أكبر القفزات:")
        for d, t in jumps[:3]:
            print(f"  {t:%H:%M}: {d:+.2f} دقيقة")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
