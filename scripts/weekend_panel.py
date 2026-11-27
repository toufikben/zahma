"""هل فرق 5 كم/س بين نهاية الأسبوع وأيام العمل حقيقي، أم أثر تغطية؟

**الشك المشروع:** السبت جُمع على 5,092 مقطعاً والأحد على 5,513، بينما
أيام العمل على 6,316. لو كانت المقاطع الناقصة هي الأبطأ (طرق صغيرة،
أزقة)، لكان متوسط نهاية الأسبوع أسرع **لأن العيّنة مختلفة**، لا لأن
الحركة أخف. قياس مضلّل بصمت — نفس الفخ الذي أوقعنا في «لا ذروة صباحية».

**الحل:** لوحة ثابتة — فقط المقاطع المقيسة في **كل** الأيام التسعة.
حينها المقارنة عادلة بالكامل: نفس الشوارع، نفس الساعات، أيام مختلفة.

**السؤال:** هل يبقى فرق ~5 كم/س بعد تثبيت اللوحة؟ إن بقي فهو حركة.
إن اختفى فهو تغطية.

التشغيل: python scripts/weekend_panel.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

DAYS = [
    ("2026-11-30", "Mon", "عمل"),
    ("2026-12-01", "Tue", "عمل"),
    ("2026-12-02", "Wed", "عمل"),
    ("2026-12-03", "Thu", "عمل"),
    ("2026-12-04", "Fri", "جمعة"),
    ("2026-12-05", "Sat", "سبت"),
    ("2026-12-06", "Sun", "أحد"),
    ("2026-12-07", "Mon", "عمل"),
    ("2026-12-08", "Tue", "عمل"),
]


def main() -> int:
    names = [d for d, _, _ in DAYS]
    n_days = len(names)

    with session_scope() as s:
        panel = s.execute(
            text(
                """
                SELECT segment_id
                FROM samples
                WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD')
                      = ANY(:days)
                  AND speed_kmh IS NOT NULL
                GROUP BY segment_id
                HAVING count(DISTINCT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD'))
                       = :n
                """
            ),
            {"days": names, "n": n_days},
        ).scalars().all()

        print(f"اللوحة الثابتة: {len(panel):,} مقطعاً مقيساً في كل الأيام الـ{n_days}")
        if not panel:
            print("لا لوحة — تحقق من البيانات")
            return 1

        rows = s.execute(
            text(
                """
                SELECT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') AS d,
                       count(*) AS n,
                       round(avg(speed_kmh)::numeric, 3) AS mean_kmh
                FROM samples
                WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD')
                      = ANY(:days)
                  AND segment_id = ANY(:ids)
                  AND speed_kmh IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """
            ),
            {"days": names, "ids": panel},
        ).all()

    vals = {d: float(m) for d, _, m in rows}
    counts = {d: n for d, n, _ in rows}

    print("\n── المتوسط على اللوحة الثابتة")
    print("   اليوم        نوع     قياسات   متوسط")
    for d, dow, kind in DAYS:
        if d in vals:
            print(f"   {d} {dow:<3} {kind:<7} {counts[d]:>7,}  {vals[d]:>7.3f}")

    workdays = [d for d, _, k in DAYS if k == "عمل" and d in vals]
    base = sum(vals[d] for d in workdays) / len(workdays)
    print(f"\n   أساس أيام العمل ({len(workdays)} أيام): {base:.3f} كم/س")

    print("\n── الفرق عن أساس أيام العمل")
    for d, dow, kind in DAYS:
        if d not in vals or kind == "عمل":
            continue
        diff = vals[d] - base
        flag = " ★" if abs(diff) >= 2.0 else ""
        print(f"   {d} {dow:<3} {kind:<7} {diff:+7.3f} كم/س{flag}")

    # الحكم على بنية الأسبوع
    print("\n── الحكم: أي عطلة يصفها هذا النمط؟")
    fri = vals.get("2026-12-04")
    sat = vals.get("2026-12-05")
    sun = vals.get("2026-12-06")

    def is_rest(v: float | None) -> bool:
        return v is not None and (v - base) >= 2.0

    r_fri, r_sat, r_sun = is_rest(fri), is_rest(sat), is_rest(sun)
    print(f"   الجمعة عطلة؟  {'نعم' if r_fri else 'لا'}   ({fri - base:+.2f})" if fri else "   الجمعة: —")
    print(f"   السبت  عطلة؟  {'نعم' if r_sat else 'لا'}   ({sat - base:+.2f})" if sat else "   السبت: —")
    print(f"   الأحد  عطلة؟  {'نعم' if r_sun else 'لا'}   ({sun - base:+.2f})" if sun else "   الأحد: —")

    print()
    if r_sat and r_sun and not r_fri:
        print("   ✗ النمط يصف **أسبوعاً غربياً**: العطلة السبت + الأحد.")
        print("     عطلة الجزائر الجمعة + السبت.")
        print("     ⇒ الجمعة والأحد خطأ بنيوياً في هذا المصدر.")
        print("     ⇒ السبت صحيح بالمصادفة (عطلة في الحالتين).")
        print("     ⇒ الاثنين–الخميس صحيحة.")
        return 2

    if r_fri and r_sat and not r_sun:
        print("   ✓ النمط يصف **أسبوعاً جزائرياً**: العطلة الجمعة + السبت.")
        print("     المصدر يميّز أيام الجزائر بشكل صحيح.")
        return 0

    print("   ! النمط لا يطابق أي أسبوع معروف — يحتاج مراجعة.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
