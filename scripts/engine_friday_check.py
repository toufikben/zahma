"""هل المحرّك يعطي الجمعة رقماً مختلفاً بعد إصلاح الملفات؟

**ما نتحقق منه:** قبل الإصلاح كانت `speed_profiles` بلا صفوف للجمعة،
فكان المحرّك يرجع إلى أولوية الصنف (conf 0.35) ثم إلى السرعة الحرة
(conf 0.3). بعد الإصلاح يجب أن يجد ملف تعريف حقيقياً (conf 0.6).

**الاختبار:** نفس المسار، نفس الساعة، خمسة أيام مختلفة. نقارن:
- مدة الرحلة المتوقعة
- الثقة المعلنة
- أساس التقدير (profile / class / freeflow)

**ماذا نريد أن نرى:** الجمعة والسبت لهما `basis=profile` وconf 0.6،
لا `class`/`freeflow`. وأن المدة تختلف عن أيام العمل — ولو قليلاً.

**تحذير صادق:** الملفات مبنية على **يوم جمعة واحد** (n=1 لكل تركيبة).
الرقم دقيق بمعنى أنه مقيس، لكنه لا يمثّل تباين الجمعة عبر الأسابيع.
الثقة 0.6 تصف «نعرف هذا المقطع في مثل هذا الوقت» — وهذا صحيح لهذا
اليوم المحدد فقط.

التشغيل: python scripts/engine_friday_check.py
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from zahma.predict.engine import day_type_of, estimate_route

DZ = ZoneInfo("Africa/Algiers")

# نفس المسار في كل مرة: باب الزوار ← وسط العاصمة.
ORIGIN = (36.7167, 3.1833)
DEST = (36.7705, 3.0589)

DAYS = [
    ("الاثنين 11-30", datetime(2026, 11, 30, 8, 0, tzinfo=DZ)),
    ("الثلاثاء 12-01", datetime(2026, 12, 1, 8, 0, tzinfo=DZ)),
    ("الجمعة 12-04", datetime(2026, 12, 4, 8, 0, tzinfo=DZ)),
    ("السبت 12-05", datetime(2026, 12, 5, 8, 0, tzinfo=DZ)),
    ("الأحد 12-06", datetime(2026, 12, 6, 8, 0, tzinfo=DZ)),
]


def main() -> int:
    print("مسار: باب الزوار ← وسط العاصمة، الساعة 08:00\n")
    print(f"   {'اليوم':<16} {'نوع':<9} {'دقيقة':>7} {'ثقة':>6}  الأساس")

    results = []
    for label, when in DAYS:
        dtype = day_type_of(when)
        try:
            r = estimate_route(
                ORIGIN[0], ORIGIN[1], DEST[0], DEST[1], when=when
            )
        except Exception as e:  # noqa: BLE001
            print(f"   {label:<16} {dtype:<9} خطأ: {str(e)[:50]}")
            continue

        mins = r.duration_s / 60
        conf = r.confidence
        bases = dict(r.basis_counts or {})
        top = ", ".join(
            f"{k}:{v}" for k, v in sorted(bases.items(), key=lambda x: -x[1])[:2]
        )
        results.append((label, dtype, mins, conf, bases))
        print(f"   {label:<16} {dtype:<9} {mins:>7.2f} {conf:>6.3f}  {top}")

    print("\n── الحكم")
    friday = [r for r in results if r[1] == "FRIDAY"]
    workdays = [r for r in results if r[1] == "WORKDAY"]

    if not friday:
        print("   لا نتيجة للجمعة")
        return 1

    f = friday[0]
    f_bases = f[4]
    has_profile = f_bases.get("profile", 0) > 0 or f_bases.get("profile+stale", 0) > 0
    fallback = f_bases.get("freeflow", 0)

    print(f"   الجمعة: {f[2]:.2f} دقيقة، ثقة {f[3]:.3f}")
    print(f"   مقاطع بملف تعريف: {f_bases.get('profile', 0)}")
    print(f"   مقاطع بسرعة حرة فقط: {fallback}")

    if has_profile:
        print("   ✓ المحرّك يجد ملفات تعريف للجمعة — الإصلاح نجح.")
    else:
        print("   ✗ ما زال يرجع إلى الصنف/السرعة الحرة — الملفات غير مقروءة.")

    if workdays:
        w = workdays[0]
        d = f[2] - w[2]
        print(f"\n   الفرق عن أيام العمل: {d:+.2f} دقيقة ({d/w[2]*100:+.1f}%)")
        if abs(d) < 0.3:
            print("   ≈ لا فرق — متوقع، لأن بيانات Mapbox نفسها لا تميّز الجمعة.")
            print("     المكسب هنا ليس الدقة بل **الصدق**: الجمعة الآن لها")
            print("     ملف مقيس (n=1) بدل الرجوع الأعمى إلى سرعة حرة.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
