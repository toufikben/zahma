"""الاختبار القاطع: هل الجمعة مطابقة **حرفياً** ليوم عمل، مقطعاً بمقطع؟

**لماذا هذا الاختبار وحده يحسم كل شيء:** المقارنة بالمتوسطات تخدع. لكن
لو أخذنا كل مقطع على حدة وسألنا «كم كانت سرعته الجمعة 12-04 وكم كانت
الأربعاء 12-02 في نفس الساعة؟» فإن أي فرق حقيقي سيظهر. وإن كانت النتيجة
أن **كل** المقاطع متطابقة بالكسور العشرية، فذلك ليس تشابهاً — بل نفس
الجدول مُعاد إرجاعه.

**العتبة:** فرق أقل من 0.05 كم/س = مطابقة تامة (دقة تخزين). أي أن
الاختلاف لا يتجاوز تقريب الفاصلة العشرية.

**الاختبار المقابل (المجموعة الضابطة):** نقارن الأربعاء 12-02 بالخميس
12-03. لو كانا مختلفين بينما الجمعة مطابقة، فالمشكلة في **الجمعة** لا في
القياس.

**ولماذا الجمعة بالذات:** الجمعة في الجزائر أهدأ يوم في الأسبوع — يخرج
الناس للصلاة ثم يبقون في البيوت. لو كان Mapbox يقيس الجزائر، لكانت
الجمعة مختلفة بشكل صارخ عن أي يوم عمل. تطابقها التام يعني أن النمط لا
يعرف الجمعة الجزائرية إطلاقاً.

التشغيل: python scripts/friday_identity.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

PAIRS = [
    ("الجمعة", "2026-12-04", "الأربعاء", "2026-12-02"),
    ("الجمعة", "2026-12-04", "الخميس", "2026-12-03"),
    ("الأربعاء", "2026-12-02", "الخميس", "2026-12-03"),  # ضابطة
    ("الاثنين", "2026-11-30", "الثلاثاء", "2026-12-01"),  # ضابطة
    ("الاثنين", "2026-11-30", "الاثنين", "2026-12-07"),  # نفس اليوم، أسبوعين
    ("السبت", "2026-12-05", "الأحد", "2026-12-06"),
]

SQL = """
WITH a AS (
    SELECT segment_id,
           extract(hour FROM ts_bucket AT TIME ZONE 'Africa/Algiers')::int AS hr,
           avg(speed_kmh) AS v
    FROM samples
    WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') = :d1
      AND speed_kmh IS NOT NULL
    GROUP BY 1, 2
), b AS (
    SELECT segment_id,
           extract(hour FROM ts_bucket AT TIME ZONE 'Africa/Algiers')::int AS hr,
           avg(speed_kmh) AS v
    FROM samples
    WHERE to_char(ts_bucket AT TIME ZONE 'Africa/Algiers','YYYY-MM-DD') = :d2
      AND speed_kmh IS NOT NULL
    GROUP BY 1, 2
)
SELECT count(*) AS n,
       round(avg(abs(a.v - b.v))::numeric, 4) AS mae,
       round(max(abs(a.v - b.v))::numeric, 3) AS max_diff,
       count(*) FILTER (WHERE abs(a.v - b.v) < 0.05) AS exact,
       count(*) FILTER (WHERE abs(a.v - b.v) >= 1.0) AS differs
FROM a JOIN b USING (segment_id, hr)
"""


def main() -> int:
    print("── مقارنة مقطع-بمقطع، ساعة-بساعة")
    print(f"   {'اليوم أ':<9} {'اليوم ب':<9} {'أزواج':>7} {'متوسط الفرق':>12} {'أقصى':>7} {'مطابق':>8} {'يختلف':>7}")

    verdicts = []
    with session_scope() as s:
        for name1, d1, name2, d2 in PAIRS:
            r = s.execute(text(SQL), {"d1": d1, "d2": d2}).one()
            n, mae, mx, exact, differs = r
            if not n:
                continue
            pct_exact = exact / n * 100
            verdicts.append((name1, name2, d1, d2, n, float(mae), float(mx or 0), pct_exact, differs))
            print(
                f"   {name1:<9} {name2:<9} {n:>7,} {float(mae):>12.4f} "
                f"{float(mx or 0):>7.2f} {pct_exact:>7.1f}% {differs:>7,}"
            )

    print("\n── الحكم")
    for name1, name2, d1, d2, n, mae, mx, pct, differs in verdicts:
        if mae < 0.05:
            tag = "★ متطابقان تماماً — نفس الجدول"
        elif mae < 0.5:
            tag = "متقاربان جداً"
        elif mae < 2.0:
            tag = "متقاربان"
        else:
            tag = "مختلفان"
        print(f"   {name1} ({d1}) مقابل {name2} ({d2}): {mae:.4f} كم/س  ⇒ {tag}")

    # الحكم النهائي على الجمعة
    fri = [v for v in verdicts if v[0] == "الجمعة" and v[1] != "الجمعة"]
    if fri:
        worst = max(v[5] for v in fri)
        print()
        if worst < 0.5:
            print("   ✗ الجمعة مطابقة لأيام العمل تقريباً. لا وجود لجمعة جزائرية")
            print("     في هذا النمط. أي منتج يعتمد عليه سيعطي تقديراً خاطئاً")
            print("     في أهدأ يوم من الأسبوع وأكثرها حركةً للزيارات.")
            return 2
        print("   ✓ الجمعة مختلفة عن أيام العمل — النمط يميّزها.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
