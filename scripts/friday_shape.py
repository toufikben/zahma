"""الاختبار الأخير: هل شكل منحنى الجمعة مختلف، ولو ساعة بساعة؟

**لماذا هذا بعد `weekend_panel`:** أثبتنا أن **المستوى** العام متطابق
(±0.75 كم/س). لكن قد يختلف **الشكل**: الجمعة في الجزائر تبدأ هادئة
(لا ذهاب للعمل) وتذرو في منتصف النهار (صلاة + زيارات). المستوى نفسه
لكن التوزيع مختلف. هذا يهم المنتج أكثر من المتوسط.

**اللوحة الثابتة إلزامية هنا:** بدونها أي فرق بين الساعات قد يكون فرق
عيّنة. بهذه اللوحة نقارن نفس الشوارع في نفس الساعات.

**الحكم:** لو كان أقصى فرق ساعة-بساعة أقل من 2 كم/س، فالمنحنى نفسه
مُعاد استخدامه — لا وجود لجمعة جزائرية في المصدر.

التشغيل: python scripts/friday_shape.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

WORKDAYS = ["2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03",
            "2026-12-07", "2026-12-08"]
FRIDAY = "2026-12-04"
ALL = WORKDAYS + [FRIDAY]


def main() -> int:
    with session_scope() as s:
        panel = s.execute(
            text(
                """
                SELECT segment_id FROM samples
                WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') = ANY(:days)
                  AND speed_kmh IS NOT NULL
                GROUP BY segment_id
                HAVING count(DISTINCT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD')) = :n
                """
            ),
            {"days": ALL, "n": len(ALL)},
        ).scalars().all()

        print(f"اللوحة الثابتة: {len(panel):,} مقطعاً في كل الأيام الـ{len(ALL)}")

        rows = s.execute(
            text(
                """
                SELECT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') AS d,
                       extract(hour FROM ts_bucket AT TIME ZONE 'Africa/Algiers')::int AS hr,
                       avg(speed_kmh) AS v
                FROM samples
                WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') = ANY(:days)
                  AND segment_id = ANY(:ids)
                  AND speed_kmh IS NOT NULL
                GROUP BY 1, 2
                """
            ),
            {"days": ALL, "ids": panel},
        ).all()

    curve: dict[str, dict[int, float]] = {}
    for d, hr, v in rows:
        curve.setdefault(d, {})[hr] = float(v)

    base: dict[int, float] = {}
    for hr in range(24):
        vals = [curve[d][hr] for d in WORKDAYS if hr in curve.get(d, {})]
        if vals:
            base[hr] = sum(vals) / len(vals)

    fri = curve.get(FRIDAY, {})
    print("\n── الجمعة مقابل أساس أيام العمل، ساعة بساعة (لوحة ثابتة)")
    print("   ساعة   أيام عمل   الجمعة    الفرق")
    diffs: list[tuple[int, float]] = []
    for hr in sorted(fri):
        if hr not in base:
            continue
        d = fri[hr] - base[hr]
        diffs.append((hr, d))
        mark = "  ←" if abs(d) >= 2.0 else ""
        print(f"   {hr:>2}h   {base[hr]:>7.2f}  {fri[hr]:>7.2f}  {d:>+7.2f}{mark}")

    if not diffs:
        print("لا بيانات مشتركة")
        return 1

    max_abs = max(abs(d) for _, d in diffs)
    mean_abs = sum(abs(d) for _, d in diffs) / len(diffs)
    max_hr = max(diffs, key=lambda x: abs(x[1]))

    print(f"\n   متوسط الفرق المطلق: {mean_abs:.3f} كم/س")
    print(f"   أقصى فرق: {max_abs:.2f} كم/س عند {max_hr[0]:02d}:00")

    # اختبار الشكل: هل ذروة الجمعة في ساعة مختلفة؟
    def peak(c: dict[int, float]) -> int | None:
        day = {h: v for h, v in c.items() if 5 <= h <= 22}
        return min(day, key=lambda h: day[h]) if day else None

    pf, pb = peak(fri), peak(base)
    print(f"\n   ساعة الذروة — الجمعة: {pf:02d}:00   أيام العمل: {pb:02d}:00")

    print("\n── الحكم")
    if max_abs < 2.0:
        print("   ✗ لا اختلاف في الشكل ولا في المستوى.")
        print("     منحنى الجمعة = منحنى أيام العمل حرفياً.")
        print("     المصدر لا يعرف الجمعة الجزائرية إطلاقاً.")
        return 2
    if pf != pb:
        print(f"   ✓ ذروة الجمعة في ساعة مختلفة ({pf:02d}:00 مقابل {pb:02d}:00).")
        print("     المصدر يميّز شكل الجمعة، ولو لم يميّز مستواها.")
        return 0
    print("   ! فرق موجود لكن الشكل العام متشابه.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
