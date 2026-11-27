"""هل منحنى Mapbox معطوب، أم أن تحليلنا مضلَّل بتركيب المقاطع؟

**الشك:** كل التحليلات السابقة حسبت `avg(speed_kmh)` لكل ساعة فوق **كل**
القياسات. لكن لو اختلفت مجموعة المقاطع المقيسة بين ساعة وأخرى (نسبة
المطابقة تتراوح 87–89%)، فالمتوسط يقارن تفاحاً ببرتقال: الساعة التي فيها
مقاطع سريعة أكثر تبدو أسرع، لا لأن الحركة أفضل بل لأن العيّنة مختلفة.

**الحل:** نقيس فقط على **مجموعة ثابتة** من المقاطع المقيسة في **كل**
الساعات. حينها الفرق بين الساعات هو حركة فعلاً، لا تركيب عيّنة.

**ما نبحث عنه:** ذروة صباحية حقيقية (07:00–08:30) أبطأ من ساعات ما بعدها.
لو اختفت الذروة الصباحية حتى على المجموعة الثابتة، فالمنحنى نفسه معطوب —
وهذا يعني أن Mapbox لا يقيس الجزائر، بل يوزّع قالباً.

التشغيل: python scripts/curve_fixed_panel.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

TARGET_DAY = "2026-12-02"  # يوم عمل كامل التغطية


def main() -> int:
    with session_scope() as s:
        # الساعات المتوفرة
        hours = s.execute(
            text(
                """
                SELECT extract(hour FROM ts_bucket AT TIME ZONE 'Africa/Algiers')::int AS hr,
                       count(*) AS n
                FROM samples
                WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') = :d
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"d": TARGET_DAY},
        ).all()
        hrs = [h for h, _ in hours if _ and _ > 0]
        print(f"اليوم {TARGET_DAY} — الساعات: {hrs}")

        # المقاطع الموجودة في كل الساعات (لوحة ثابتة)
        panel = s.execute(
            text(
                """
                SELECT segment_id
                FROM samples
                WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') = :d
                  AND speed_kmh IS NOT NULL
                GROUP BY segment_id
                HAVING count(DISTINCT extract(hour FROM ts_bucket AT TIME ZONE 'Africa/Algiers')) = :nh
                """
            ),
            {"d": TARGET_DAY, "nh": len(hrs)},
        ).scalars().all()
        print(f"مقاطع موجودة في كل الساعات: {len(panel):,}")

        if not panel:
            print("لا لوحة ثابتة — تحقق من البيانات")
            return 1

        # منحنى على اللوحة الثابتة
        rows = s.execute(
            text(
                """
                SELECT extract(hour FROM ts_bucket AT TIME ZONE 'Africa/Algiers')::int AS hr,
                       count(*) AS n,
                       round(avg(speed_kmh)::numeric, 2) AS mean_kmh,
                       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY speed_kmh))::numeric, 2) AS med
                FROM samples
                WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') = :d
                  AND segment_id = ANY(:ids)
                  AND speed_kmh IS NOT NULL
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"d": TARGET_DAY, "ids": panel},
        ).all()

        print("\n── المنحنى على نفس المقاطع في كل الساعات")
        print("   ساعة   متوسط   وسيط   تغيّر%")
        base = None
        for hr, n, mean, med in rows:
            if base is None:
                base = float(mean)
            pct = (float(mean) - base) / base * 100
            bar = "█" * max(0, int((float(mean) - 38) * 1.2))
            print(f"   {hr:>2}h  {float(mean):>7.2f} {float(med):>7.2f} {pct:>+6.1f}%  {bar}")

    # الحكم على الشكل
    m = {hr: float(mean) for hr, _, mean, _ in rows}
    print("\n── هل توجد ذروة صباحية؟")
    morning = [h for h in (7, 8, 9) if h in m]
    midday = [h for h in (10, 12, 14) if h in m]
    if morning and midday:
        am = min(m[h] for h in morning)
        mid = max(m[h] for h in midday)
        print(f"   أبطأ ساعة صباحية: {am:.2f}   أسرع ساعة ظهراً: {mid:.2f}")
        if am < mid:
            print("   ✓ ذروة صباحية موجودة (الصباح أبطأ من الظهر)")
        else:
            print("   ✗ لا ذروة صباحية — الظهر أبطأ من الصباح")
            print("     هذا غير ممكن في مدينة حقيقية: 07:00–09:00 هي ذروة الخروج")
            print("     للعمل والمدارس، و10:00–14:00 هي أهدأ ساعات النهار.")
            print("     ⇒ المنحنى ليس قياساً لحركة الجزائر.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
