"""هل الجمعة والسبت مختلفان فعلاً عن أيام العمل؟ قياس لا افتراض.

المستخدم قال: «الجمعة والسبت أيام راحة لا ينطبق عليها تقريباً نمط أيام
الأخرى». هذا ادعاء قابل للقياس. لو كان صحيحاً، فأي نموذج يخلطها بأيام
العمل يعطي تقديراً خاطئاً في أشدّ الأوقات حساسية (منتصف النهار الجمعة،
حيث الجزائر تتحرّك كلها في ساعتين ثم تعود للصمت).

**المنهج:** نفس المقاطع، نفس الشريحة الزمنية، مقارنة وسيط السرعة بين
الجمعة وأيام العمل. نقيس أيضاً **ارتفاع المنحنى**: ذروة الجمعة ليست
الساعة 07:00 بل منتصف النهار. أيام العمل لها ذروتان (صباح/مساء) وفراغ
في الوسط. الجمعة العكس.

التشغيل: python scripts/weekend_check.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope


def main() -> int:
    with session_scope() as s:
        # أيام متوفرة فعلاً في القاعدة
        days = s.execute(
            text(
                """
                SELECT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers', 'YYYY-MM-DD') AS d,
                       to_char(ts_bucket AT TIME ZONE 'Africa/Algiers', 'Dy') AS dow,
                       cd.day_type,
                       count(DISTINCT segment_id) AS segs
                FROM samples smp
                JOIN calendar_days cd
                  ON cd.day_local = (smp.ts_bucket AT TIME ZONE 'Africa/Algiers')::date
                GROUP BY 1, 2, 3
                ORDER BY 1
                """
            )
        ).all()

        print("── الأيام المتوفرة")
        for d, dow, dt, segs in days:
            print(f"   {d} {dow.strip():<3} {dt:<9} {segs:>5} مقطعاً")

        # منحنى الساعة لكل نوع يوم — هذا هو الاختبار الحقيقي
        rows = s.execute(
            text(
                """
                SELECT cd.day_type,
                       extract(hour FROM smp.ts_bucket AT TIME ZONE 'Africa/Algiers')::int AS hr,
                       count(*) AS n,
                       round(avg(smp.speed_kmh)::numeric, 1) AS mean_kmh
                FROM samples smp
                JOIN calendar_days cd
                  ON cd.day_local = (smp.ts_bucket AT TIME ZONE 'Africa/Algiers')::date
                WHERE smp.speed_kmh IS NOT NULL
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            )
        ).all()

    by_type: dict[str, dict[int, float]] = {}
    counts: dict[str, int] = {}
    for dt, hr, n, mean in rows:
        by_type.setdefault(dt, {})[hr] = float(mean)
        counts[dt] = counts.get(dt, 0) + n

    print("\n── منحنى السرعة المتوسطة حسب نوع اليوم (كم/س)")
    hours = sorted({h for d in by_type.values() for h in d})
    print("   ساعة " + "".join(f"{t[:4]:>8}" for t in by_type))
    for h in hours:
        line = f"   {h:>4}h "
        for dt in by_type:
            v = by_type[dt].get(h)
            line += f"{v:>8.1f}" if v is not None else f"{'—':>8}"
        print(line)

    # الاختبار الحاسم: أين تقع الذروة في كل نوع يوم؟
    print("\n── أين الذروة؟ (أبطأ ساعة)")
    for dt, curve in by_type.items():
        if not curve:
            continue
        worst_h = min(curve, key=lambda h: curve[h])
        best_h = max(curve, key=lambda h: curve[h])
        print(
            f"   {dt:<9} أبطأ {worst_h:02d}:00 ({curve[worst_h]:.1f} كم/س)  "
            f"أسرع {best_h:02d}:00 ({curve[best_h]:.1f} كم/س)  "
            f"قياسات {counts[dt]:,}"
        )

    # مقارنة مباشرة على ساعات مشتركة
    print("\n── الفرق عن أيام العمل (نفس الساعة)")
    base = by_type.get("WORKDAY", {})
    for dt in by_type:
        if dt == "WORKDAY" or not base:
            continue
        diffs = []
        for h in sorted(by_type[dt]):
            if h in base:
                diffs.append((h, by_type[dt][h] - base[h]))
        if not diffs:
            continue
        mean_diff = sum(d for _, d in diffs) / len(diffs)
        print(f"\n   {dt} مقابل WORKDAY: متوسط الفرق {mean_diff:+.1f} كم/س")
        for h, d in diffs:
            flag = "  ←" if abs(d) >= 3.0 else ""
            print(f"      {h:02d}:00  {d:+6.1f}{flag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
