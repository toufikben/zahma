"""الاختبار الحاسم: هل نمط Mapbox للجزائر هو **أسبوع غربي**؟

**الفرضية:** لو كان Mapbox يقيس الجزائر فعلاً، لكانت الجمعة والسبت أهدأ
أيام الأسبوع (عطلة الجزائر) والأحد يوم عمل عادي. ولو كان يطبّق قالباً
غربياً، لكان الأحد أهدأ يوم (عطلة الغرب) والجمعة يوم عمل عادي.

`weekend_check.py` أظهر أن الجمعة تساوي أيام العمل تقريباً. هذا يرجّح
القالب الغربي لكن لا يثبته. هنا نقيس **كل يوم أسبوع على حدة** ونرتبه
من الأهدأ إلى الأنشط. الترتيب وحده يحسم الأمر:

- جزائري حقيقي  ⇒ الجمعة/السبت في القاع، الأحد في الوسط.
- قالب غربي     ⇒ الأحد في القاع، الجمعة في الوسط/الأعلى.

**لماذا هذا أهم قياس في المشروع:** إن ثبت القالب الغربي، فكل رقم نخرجه
للجمعة والسبت خاطئ بنيوياً، ولا يمكن إصلاحه بأي معايرة — لأن الأساس نفسه
ليس قياساً للجزائر.

التشغيل: python scripts/week_structure.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

# ترتيب أيام الأسبوع في الجزائر: الأحد أول الأسبوع
DZ_ORDER = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def main() -> int:
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT to_char(ts_bucket AT TIME ZONE 'Africa/Algiers', 'Dy') AS dow,
                       to_char(ts_bucket AT TIME ZONE 'Africa/Algiers', 'YYYY-MM-DD') AS d,
                       count(*) AS n,
                       avg(speed_kmh) AS mean_kmh
                FROM samples
                WHERE speed_kmh IS NOT NULL
                GROUP BY 1, 2
                ORDER BY 2
                """
            )
        ).all()

    # نجمع بحسب اليوم ثم نأخذ وسيط الأيام — حتى لا يطغى يوم بقياسات أكثر
    per_day: dict[str, list[tuple[str, float, int]]] = {}
    for dow, d, n, mean in rows:
        per_day.setdefault(dow.strip(), []).append((d, float(mean), n))

    print("── متوسط السرعة لكل يوم أسبوع (وسيط الأيام المتوفرة)")
    summary: list[tuple[str, float, int]] = []
    for dow in DZ_ORDER:
        if dow not in per_day:
            continue
        vals = sorted(v for _, v, _ in per_day[dow])
        mid = vals[len(vals) // 2] if len(vals) % 2 else (
            vals[len(vals) // 2 - 1] + vals[len(vals) // 2]
        ) / 2
        total_n = sum(n for _, _, n in per_day[dow])
        summary.append((dow, mid, total_n))
        days = ", ".join(d for d, _, _ in per_day[dow])
        print(f"   {dow}  {mid:>6.2f} كم/س   ({total_n:>7,} قياس)   [{days}]")

    print("\n── الترتيب من الأهدأ إلى الأنشط (أبطأ = أهدأ)")
    ranked = sorted(summary, key=lambda x: x[1])
    for i, (dow, mid, _) in enumerate(ranked, 1):
        print(f"   {i}. {dow}  {mid:.2f}")

    if len(ranked) >= 2:
        quietest = ranked[0][0]
        busiest = ranked[-1][0]
        print(f"\n   الأهدأ: {quietest}   الأنشط: {busiest}")

    # الحكم
    print("\n── الحكم")
    dz_weekend = {"Fri", "Sat"}
    western_weekend = {"Sun", "Sat"}

    quietest = ranked[0][0]
    second_quietest = ranked[1][0] if len(ranked) > 1 else None

    if quietest in dz_weekend and second_quietest in dz_weekend:
        print("   ✓ يطابق العطلة الجزائرية (الجمعة/السبت أهدأ).")
        print("     النمط قد يكون جزائرياً فعلاً.")
        return 0

    if quietest == "Sun":
        print("   ✗ الأحد هو الأهدأ — هذا **هيكل أسبوع غربي**، لا جزائري.")
        print("     عطلة الجزائر الجمعة/السبت، وليست الأحد.")
        print("     الخلاصة: Mapbox يطبّق قالباً غربياً على الجزائر.")
        return 2

    print(f"   ! الأهدأ {quietest} — لا يطابق العطلة الجزائرية ولا الغربية بوضوح.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
