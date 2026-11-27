"""تحليل نظيف: أيام كاملة التغطية فقط.

**العيب الذي يمنعه:** الأيام الأولى (22–27 نوفمبر) جُمعت بـ363 مقطعاً
فقط، والأيام اللاحقة (30 نوفمبر–8 ديسمبر) بـ6,316. خلط الاثنين في متوسط
واحد يعني أن الأيام الفقيرة تُقاس على شبكة مختلفة — فأي فرق «بين أيام
الأسبوع» قد يكون فرق **تغطية** لا فرق **حركة**. قياس مضلّل بصمت.

**الحل:** نأخذ فقط الأيام التي غطّت العدد الكامل من المقاطع، ثم نقارن.

**والاختبار الحاسم لقرار المستخدم:** «الجمعة والسبت لا ينطبق عليهما نمط
أيام أخرى». نتحقق: هل منحنى الجمعة/السبت مختلف **شكلاً** لا فقط مستوى؟
أيام العمل لها ذروتان (07-09 و16-18) وفراغ في الوسط. الجمعة في الجزائر
لها ذروة واحدة قصيرة حول الظهر (الخروج للصلاة والزيارات) ثم هدوء تام.
لو ظهر منحنى الجمعة مطابقاً لأيام العمل شكلاً، فبيانات Mapbox لا تعرف
الجمعة الجزائرية أصلاً.

التشغيل: python scripts/week_clean.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

DZ_ORDER = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def main() -> int:
    with session_scope() as s:
        # 1. الأيام كاملة التغطية فقط
        full_days = s.execute(
            text(
                """
                SELECT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') AS d,
                       to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','Dy') AS dow,
                       count(DISTINCT segment_id) AS segs
                FROM samples
                GROUP BY 1, 2
                HAVING count(DISTINCT segment_id) > 5000
                ORDER BY 1
                """
            )
        ).all()

        print("── الأيام كاملة التغطية (>5000 مقطع)")
        for d, dow, segs in full_days:
            print(f"   {d} {dow.strip():<3} {segs:>5}")

        names = [d for d, _, _ in full_days]

        # 2. المنحنى لكل يوم على حدة — لا متوسطات
        rows = s.execute(
            text(
                """
                SELECT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') AS d,
                       extract(hour FROM ts_bucket AT TIME ZONE 'Africa/Algiers')::int AS hr,
                       count(*) AS n,
                       round(avg(speed_kmh)::numeric, 1) AS mean_kmh
                FROM samples
                WHERE speed_kmh IS NOT NULL
                  AND to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD')
                      = ANY(:days)
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            ),
            {"days": names},
        ).all()

    curves: dict[str, dict[int, float]] = {}
    for d, hr, n, mean in rows:
        curves.setdefault(d, {})[hr] = float(mean)

    print("\n── المنحنى لكل يوم (كم/س)")
    header = "    h  " + "".join(f"{d[5:]:>7}" for d in curves)
    print(header)
    for hr in range(24):
        line = f"   {hr:>2}h "
        any_val = False
        for d in curves:
            v = curves[d].get(hr)
            line += f"{v:>7.1f}" if v is not None else f"{'—':>7}"
            any_val = any_val or v is not None
        if any_val:
            print(line)

    # 3. تصنيف كل يوم: هل هو ذو ذروتين (عمل) أم ذروة واحدة؟
    print("\n── شكل المنحنى: ذروتان أم واحدة؟")
    for d in curves:
        c = curves[d]
        hr_vals = [(h, c[h]) for h in sorted(c) if 6 <= h <= 20]
        if len(hr_vals) < 8:
            continue
        slowest = min(v for _, v in hr_vals)
        thr = slowest + 3.0  # نطاق «الذروة»
        peak_hours = [h for h, v in hr_vals if v <= thr]
        # فجوة في المنتصف = ذروتان
        mid = [h for h in peak_hours if 10 <= h <= 15]
        early = [h for h in peak_hours if h < 10]
        late = [h for h in peak_hours if h > 15]
        shape = (
            "ذروتان"
            if early and late and not mid
            else "ذروة واحدة"
            if len(peak_hours) <= 4
            else "مستمر"
        )
        print(
            f"   {d} ({d[5:]})  أبطأ {slowest:.1f}  "
            f"ساعات الذروة {peak_hours}  ⇒ {shape}"
        )

    # 4. الجمعة والسبت مقابل متوسط أيام العمل — على نقاط الساعة المشتركة
    workdays = [
        d for d in curves
        if __import__("datetime").date.fromisoformat(d).weekday() < 4
    ]  # الأحد(6)→0 ... الخميس(3)→3 في بايثون: Sun=6, Mon=0, Tue=1, Wed=2, Thu=3
    if workdays:
        base: dict[int, float] = {}
        for hr in range(24):
            vals = [curves[d][hr] for d in workdays if hr in curves[d]]
            if vals:
                base[hr] = sum(vals) / len(vals)

        print(f"\n── الجمعة/السبت مقابل {len(workdays)} أيام عمل")
        for d in curves:
            import datetime as _dt
            wd = _dt.date.fromisoformat(d).weekday()
            if wd not in (4, 5):  # Fri=4, Sat=5
                continue
            diffs = [
                (hr, curves[d][hr] - base[hr])
                for hr in sorted(curves[d])
                if hr in base and 5 <= hr <= 22
            ]
            if not diffs:
                continue
            mean_d = sum(x for _, x in diffs) / len(diffs)
            label = "الجمعة" if wd == 4 else "السبت"
            print(f"\n   {label} {d}: متوسط الفرق {mean_d:+.2f} كم/س")
            for hr, dd in diffs:
                bar = "+" if dd >= 0 else "-"
                print(f"      {hr:02d}:00  {dd:+6.1f}  {bar * min(int(abs(dd)), 20)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
