"""لماذا 96 مقطعاً لها ملف عند 07:30 و72 فقط عند 07:45 بعد الجمع الكامل؟

**السياق:** جمعنا الشريحة 31 بـ20 زوجاً فأعطت 5,051 مقطعاً — نفس مستوى
الشريحة 30 (5,051). فالتغطية الكلية متساوية. لكن على مسارنا: 96 مقطعاً
لها ملف عند 30 و72 عند 31.

**الفرق 24 مقطعاً.** مصدره المحتمل: الشريحة 30 جُمعت في جلسات متعددة
على مدى أيام (كل جلسة 20 زوجاً لكن الأزواج مختلفة، أو جمع قديم بكل
المقاطع). فاتحاد الجلسات يعطي تغطية أوسع من جلسة واحدة.

**القياس:** من أين جاءت مقاطع الشريحة 30؟ نقارن عدد الصفوف وعدد
`samples` المميّزة لكل شريحة، ونفحص إن كان `samples` يحمل صفوفاً من
مصادر/تواريخ متعددة.
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

# شرائح الذروة الصباحية
BUCKETS = (26, 28, 30, 31, 32)


def main() -> int:
    with session_scope() as s:
        print("── تغطية الملفات لكل شريحة (بعد الجمع الكامل)")
        rows = s.execute(
            text(
                """
                SELECT bucket_15m AS b, count(*) AS segs, sum(samples_n) AS n
                FROM speed_profiles
                WHERE day_type='WORKDAY' AND bucket_15m = ANY(:bs)
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"bs": list(BUCKETS)},
        ).mappings().all()
        for r in rows:
            print(f"  {r['b']:2d}: {r['segs']:5d} مقطعاً  ({r['n']:,} عيّنة)")

        print()
        print("── من أين جاءت عيّنات كل شريحة؟ (تاريخ الجمع)")
        rows = s.execute(
            text(
                """
                SELECT
                    (extract(hour from ts_bucket AT TIME ZONE 'Africa/Algiers')*4
                     + floor(extract(minute from ts_bucket AT TIME ZONE 'Africa/Algiers')/15))::int AS b,
                    count(*) AS samples,
                    count(DISTINCT segment_id) AS segs,
                    count(DISTINCT (ts_bucket AT TIME ZONE 'Africa/Algiers')::date) AS days
                FROM samples
                WHERE source::text = 'mapbox'
                GROUP BY 1
                HAVING (extract(hour from ts_bucket AT TIME ZONE 'Africa/Algiers')*4
                     + floor(extract(minute from ts_bucket AT TIME ZONE 'Africa/Algiers')/15))::int
                     = ANY(:bs)
                ORDER BY 1
                """
            ),
            {"bs": list(BUCKETS)},
        ).mappings().all()
        for r in rows:
            print(
                f"  {r['b']:2d}: {r['samples']:6,} عيّنة  "
                f"{r['segs']:5d} مقطعاً  {r['days']} يوم/أيام"
            )

        print()
        print("── التغطية لكل تاريخ في شريحة الذروة (30 = 07:30)")
        rows = s.execute(
            text(
                """
                SELECT (ts_bucket AT TIME ZONE 'Africa/Algiers')::date AS d,
                       count(*) AS samples, count(DISTINCT segment_id) AS segs
                FROM samples
                WHERE source::text = 'mapbox'
                  AND (extract(hour from ts_bucket AT TIME ZONE 'Africa/Algiers')*4
                       + floor(extract(minute from ts_bucket AT TIME ZONE 'Africa/Algiers')/15))::int = 30
                GROUP BY 1 ORDER BY 1
                """
            )
        ).mappings().all()
        for r in rows:
            print(f"  {r['d']}: {r['samples']:6,} عيّنة  {r['segs']:5d} مقطعاً")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
