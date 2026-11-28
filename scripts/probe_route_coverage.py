"""هل تغطية مقاطع المسار متساوية عبر الشرائح؟ — مصدر التذبذب المتبقي.

**السؤال:** المحرك يستوفي خطياً بين أقرب شريحة قبل/بعد لكل مقطع (سطور
445–463 من `engine.py`). فلو كان مقطع مقيساً في 26 و28 وغائباً في 27،
فإن 27 يُستوفى — ولا تذبذب.

**فالمتبقي:** مقطع غائب من **كل** الشرائح المجاورة يتراجع إلى وسيط الصنف.
إن اختلف عدد هؤلاء بين الشرائح، اختلف المنحنى لأسباب لا علاقة لها بالطريق.

**القياس:** نأخذ مسار باب الزوار ← وسط الجزائر، ونطبع لكل شريحة كم مقطعاً
عليه ملف حقيقي وكم تراجع إلى الصنف.
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope

FROM = (36.7167, 3.1833)
TO = (36.7705, 3.0589)
BUCKETS = tuple(range(24, 36))  # 06:00 .. 08:45


def route_segments() -> list[int]:
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                WITH a AS (
                    SELECT seg_id FROM segments
                    ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:flon, :flat), 4326)
                    LIMIT 1
                ),
                b AS (
                    SELECT seg_id FROM segments
                    ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:tlon, :tlat), 4326)
                    LIMIT 1
                )
                SELECT seg_id FROM a UNION SELECT seg_id FROM b
                """
            ),
            {"flat": FROM[0], "flon": FROM[1], "tlat": TO[0], "tlon": TO[1]},
        ).all()
    return [int(r[0]) for r in rows]


def main() -> int:
    with session_scope() as s:
        print("── تغطية ملفات التعريف لكل شريحة (كل الشبكة)")
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
            print(f"  {r['b']:2d}: {r['segs']:5d}")

        print()
        print("── هل الاستيفاء يغطي الفراغات؟ (مقطع له 26 و28 يُستوفى في 27)")
        rows = s.execute(
            text(
                """
                WITH p AS (
                    SELECT segment_id, bucket_15m AS b
                    FROM speed_profiles
                    WHERE day_type='WORKDAY' AND bucket_15m = ANY(:bs)
                ),
                segs AS (SELECT DISTINCT segment_id FROM p)
                SELECT
                    count(*) AS total_segments,
                    count(*) FILTER (
                        WHERE EXISTS (SELECT 1 FROM p WHERE p.segment_id = segs.segment_id
                                      AND p.b = 26)
                          AND EXISTS (SELECT 1 FROM p WHERE p.segment_id = segs.segment_id
                                      AND p.b = 28)
                    ) AS has_26_and_28,
                    count(*) FILTER (
                        WHERE EXISTS (SELECT 1 FROM p WHERE p.segment_id = segs.segment_id
                                      AND p.b = 27)
                    ) AS has_27
                FROM segs
                """
            ),
            {"bs": list(BUCKETS)},
        ).mappings().one()
        print(f"  مقاطع لها ملف في أي شريحة: {rows['total_segments']}")
        print(f"  لها 26 و28 (تُستوفى 27): {rows['has_26_and_28']}")
        print(f"  لها 27 مباشرة:          {rows['has_27']}")

        n26 = rows["has_26_and_28"]
        n27 = rows["has_27"]
        print()
        if n27 < n26 * 0.9:
            print("⇒ **فراغ حقيقي:** مقاطع كثيرة تُستوفى في 27 لكنها مقيسة")
            print("   مباشرة في 26 و28. الاستيفاء يعمل، لكن الشريحة 27")
            print("   مبنية على استيفاء لا على قياس — فدقتها أقل.")
            print("   الإصلاح: جمع 27 و29 و31 بكل الأزواج، لا بـ3.")
        else:
            print("⇒ التغطية متقاربة — الاستيفاء يكفي.")

    print()
    print("── أثر ذلك على المسار تحديداً")
    segs = route_segments()
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT bucket_15m AS b, count(*) AS covered
                FROM speed_profiles
                WHERE day_type='WORKDAY' AND segment_id = ANY(:ids)
                  AND bucket_15m = ANY(:bs)
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"ids": segs, "bs": list(BUCKETS)},
        ).mappings().all()
    print(f"  مقاطع المسار: {len(segs)}")
    for r in rows:
        print(f"  {r['b']:2d}: {r['covered']} مغطّى")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
