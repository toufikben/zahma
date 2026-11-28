"""هل اختلاف الشرائح في عدد المقاطع يفسّر تذبذب المنحنى؟

**المشكلة:** منحنى الانطلاق يقفز +6.78 دقيقة عند 06:45 ثم يهبط −4.34 عند
07:00. والسرعة المتوسطة تبدو متذبذبة: 67.43 ← 57.02 ← 61.41.

**الفرضية:** المقارنة بين شرائح ذات مجموعات مقاطع مختلفة. الشرائح القديمة
(26، 28، 30، 32) جمعت كل الأزواج (~5,000 مقطع)، والجديدة التي جمعتها الآن
(27، 29، 31) استخدمت `--pairs 3` فقط (~2,000 مقطع). والمقاطع المغطاة في
الجديدة طرق سريعة أساساً (أسرع)، فالخلط يُنتج تذبذباً مصطنعاً.

**التحقق:** (أ) عدد المقاطع لكل شريحة، (ب) توزيع أصناف الطرق، (ج) المتوسط
على المقاطع المشتركة فقط.
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

BUCKETS = (26, 27, 28, 29, 30, 31, 32)


def main() -> int:
    with session_scope() as s:
        print("── عدد المقاطع لكل شريحة")
        rows = s.execute(
            text(
                """
                SELECT bucket_15m AS b, count(*) AS segs
                FROM speed_profiles
                WHERE day_type='WORKDAY' AND bucket_15m = ANY(:bs)
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"bs": list(BUCKETS)},
        ).mappings().all()
        for r in rows:
            print(f"  bucket {r['b']:2d}: {r['segs']:5d} مقطعاً")

        print()
        print("── توزيع أصناف الطرق (26 = قديم كامل، 27 = جديد جزئي)")
        for b in (26, 27):
            rows = s.execute(
                text(
                    """
                    SELECT seg.road_class, count(*) AS n,
                           round(avg(p.p50_speed)::numeric, 1) AS avg_kmh
                    FROM speed_profiles p
                    JOIN segments seg ON seg.seg_id = p.segment_id
                    WHERE p.day_type='WORKDAY' AND p.bucket_15m = :b
                    GROUP BY 1 ORDER BY 2 DESC
                    """
                ),
                {"b": b},
            ).mappings().all()
            print(f"  --- bucket {b}")
            for r in rows:
                print(f"      {r['road_class']:14s} {r['n']:5d}  {r['avg_kmh']}")

        print()
        print("── المتوسط على المقاطع المشتركة في كل الشرائح السبع")
        rows = s.execute(
            text(
                """
                WITH p AS (
                    SELECT segment_id, bucket_15m AS b, p50_speed
                    FROM speed_profiles
                    WHERE day_type='WORKDAY' AND bucket_15m = ANY(:bs)
                ),
                common AS (
                    SELECT segment_id FROM p GROUP BY 1 HAVING count(*) = :n
                )
                SELECT p.b, count(*) AS segs,
                       round(avg(p.p50_speed)::numeric, 2) AS avg_kmh
                FROM p JOIN common USING (segment_id)
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"bs": list(BUCKETS), "n": len(BUCKETS)},
        ).mappings().all()
        for r in rows:
            print(f"  bucket {r['b']:2d}: {r['segs']:5d} مقطعاً  {r['avg_kmh']} كم/س")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
