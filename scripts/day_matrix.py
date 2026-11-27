"""مصفوفة المسافات بين كل الأيام — الصورة الكاملة في جدول واحد.

**لماذا نحتاجها:** المقارنات الثنائية السابقة أجابت «هل الجمعة مختلفة؟».
لكن السؤال الأعمق: **هل يوجد أي بنية أسبوعية في هذه البيانات أصلاً؟**

لو كانت البيانات نمطاً أسبوعياً حقيقياً، لكانت المسافة بين أي يومين
متشابهين (اثنين/ثلاثاء) صغيرة، وبين يومين مختلفين (جمعة/ثلاثاء) كبيرة،
وبين نفس اليوم في أسبوعين متوسطاً. المصفوفة تُظهر ذلك كله دفعة واحدة.

**القراءة:** كل خلية = متوسط الفرق المطلق (كم/س) على نفس المقاطع ونفس
الساعات. صفر = نفس الأرقام حرفياً.

**التنبؤ القابل للتكذيب:** إن كانت كل الخلايا متقاربة (أقل من ~0.5)،
فلا بنية أسبوعية — الجدول يوم واحد مُكرَّر. وإن كانت الخلايا القطرية
(نفس اليوم، أسبوعان) أصغر من البعيدة، فهناك بنية.

التشغيل: python scripts/day_matrix.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

DAYS = [
    ("11-30", "2026-11-30", "Mon"),
    ("12-01", "2026-12-01", "Tue"),
    ("12-02", "2026-12-02", "Wed"),
    ("12-03", "2026-12-03", "Thu"),
    ("12-04", "2026-12-04", "Fri"),
    ("12-05", "2026-12-05", "Sat"),
    ("12-06", "2026-12-06", "Sun"),
    ("12-07", "2026-12-07", "Mon"),
    ("12-08", "2026-12-08", "Tue"),
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
SELECT count(*) AS n, avg(abs(a.v - b.v)) AS mae
FROM a JOIN b USING (segment_id, hr)
"""


def main() -> int:
    print("── مصفوفة المسافة (متوسط الفرق المطلق، كم/س)")
    print("   صفر = نفس الأرقام حرفياً\n")

    labels = [f"{lbl} {dow}" for lbl, _, dow in DAYS]
    print("        " + "".join(f"{l[:5]:>7}" for l in labels))

    matrix: list[list[float | None]] = []
    with session_scope() as s:
        for i, (_, d1, _) in enumerate(DAYS):
            row: list[float | None] = []
            line = f"   {labels[i][:5]:<5} "
            for j, (_, d2, _) in enumerate(DAYS):
                if j > i:
                    line += f"{'':>7}"
                    row.append(None)
                    continue
                r = s.execute(text(SQL), {"d1": d1, "d2": d2}).one()
                n, mae = r
                v = float(mae) if n else None
                row.append(v)
                line += f"{v:>7.3f}" if v is not None else f"{'—':>7}"
            matrix.append(row)
            print(line)

    # تحليل: نفس اليوم في أسبوعين مقابل أيام مختلفة
    print("\n── التصنيف")
    same_dow: list[float] = []
    diff_dow: list[float] = []
    for i, (_, _, dow_i) in enumerate(DAYS):
        for j in range(i):
            v = matrix[i][j]
            if v is None:
                continue
            dow_j = DAYS[j][2]
            (same_dow if dow_i == dow_j else diff_dow).append(v)

    def stat(xs: list[float], name: str) -> None:
        if not xs:
            print(f"   {name}: لا بيانات")
            return
        print(
            f"   {name}: n={len(xs)}  متوسط {sum(xs)/len(xs):.4f}  "
            f"أدنى {min(xs):.4f}  أقصى {max(xs):.4f}"
        )

    stat(same_dow, "نفس اليوم، أسبوعان مختلفان")
    stat(diff_dow, "يومان مختلفان")

    print("\n── الحكم")
    if same_dow and diff_dow:
        a = sum(same_dow) / len(same_dow)
        b = sum(diff_dow) / len(diff_dow)
        print(f"   نفس اليوم: {a:.4f}   مختلف: {b:.4f}   النسبة {b/max(a,1e-9):.1f}×")
        if b < 1.0:
            print("   ✗ كل الأيام متقاربة بشكل مطلق (<1 كم/س).")
            print("     لا توجد بنية أسبوعية قابلة للقياس في هذه البيانات.")
            print("     الجدول = نمط واحد مُكرَّر لكل أيام الأسبوع.")
            return 2
        if a * 2 < b:
            print("   ✓ بنية أسبوعية واضحة: نفس اليوم أقرب بكثير.")
            return 0
        print("   ! بنية ضعيفة — الفرق بين الأيام داخل حدود الضجيج.")

    all_vals = [v for row in matrix for v in row if v is not None]
    if all_vals and max(all_vals) < 1.0:
        print("   ✗ أقصى مسافة في المصفوفة أقل من 1 كم/س — لا بنية.")
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
