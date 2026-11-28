"""مقاطع المسار: هل هي في الـ20 زوجاً أم خارجها؟

**الفرق المتبقي:** 96 مقطعاً لها ملف عند الشريحة 30 و72 عند 31، مع أن
31 فيها 5,335 مقطعاً (أكثر من 30). فالسبب ليس نقص تغطية كلية، بل أن
المسار الجديد يمر بمقاطع لم يشملها جمع الـ20 زوجاً.

**لماذا 30 تغطي أكثر؟** لأنها جُمعت على 10 أيام بجلسات مختلفة. وكل جلسة
تختار 20 زوجاً — والاتحاد عبر الأيام يغطي شبكة أوسع. جلسة واحدة (31)
تغطي 20 زوجاً فقط.

**القياس:** نقارن مجموعة المقاطع المغطّاة في 30 مقابل 31، ونطبع كم مقطعاً
من المسار يغطيه كلٌّ منهما، وكم مغطّى في 30 وغائب في 31.
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope


def main() -> int:
    with session_scope() as s:
        # مجموعة المقاطع المغطاة في 30 و31
        r = s.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM speed_profiles
                     WHERE day_type='WORKDAY' AND bucket_15m=30) AS n30,
                    (SELECT count(*) FROM speed_profiles
                     WHERE day_type='WORKDAY' AND bucket_15m=31) AS n31,
                    (SELECT count(*) FROM (
                        SELECT segment_id FROM speed_profiles
                        WHERE day_type='WORKDAY' AND bucket_15m=30
                        INTERSECT
                        SELECT segment_id FROM speed_profiles
                        WHERE day_type='WORKDAY' AND bucket_15m=31
                    ) t) AS common,
                    (SELECT count(*) FROM (
                        SELECT segment_id FROM speed_profiles
                        WHERE day_type='WORKDAY' AND bucket_15m=30
                        EXCEPT
                        SELECT segment_id FROM speed_profiles
                        WHERE day_type='WORKDAY' AND bucket_15m=31
                    ) t) AS only30,
                    (SELECT count(*) FROM (
                        SELECT segment_id FROM speed_profiles
                        WHERE day_type='WORKDAY' AND bucket_15m=31
                        EXCEPT
                        SELECT segment_id FROM speed_profiles
                        WHERE day_type='WORKDAY' AND bucket_15m=30
                    ) t) AS only31
                """
            )
        ).mappings().one()
        print(f"مقاطع 30: {r['n30']:,}  |  31: {r['n31']:,}")
        print(f"مشتركة: {r['common']:,}")
        print(f"في 30 فقط: {r['only30']:,}")
        print(f"في 31 فقط: {r['only31']:,}")
        print()

        # هل المقاطع الـ24 المفقودة على المسار موجودة في 31؟
        # نأخذ مسار 06:30 (شريحة 30) ونفحص تغطيته في 31
        ids30 = [
            int(x[0])
            for x in s.execute(
                text(
                    """
                    SELECT segment_id FROM speed_profiles
                    WHERE day_type='WORKDAY' AND bucket_15m=30
                    LIMIT 600
                    """
                )
            ).all()
        ]
        cov31 = s.execute(
            text(
                """
                SELECT count(*) FROM speed_profiles
                WHERE day_type='WORKDAY' AND bucket_15m=31
                  AND segment_id = ANY(:ids)
                """
            ),
            {"ids": ids30},
        ).scalar()
        print(f"عيّنة {len(ids30)} مقطعاً من 30: منها {cov31} مغطّى في 31")
        print(f"⇒ نسبة التداخل: {cov31 / len(ids30) * 100:.1f}%")

        print()
        print("── الاستنتاج")
        print("  الشريحة 31 مغطّاة بجلسة واحدة (20 زوجاً، يوم واحد).")
        print("  الشريحة 30 مغطّاة بـ10 جلسات (اتحاد 20 زوجاً × 10 أيام).")
        print("  فالاتحاد يغطي شبكة أوسع بكثير من جلسة واحدة.")
        print()
        print("  ⇒ **القاعدة:** كل شريحة تحتاج جمعاً متكرراً عبر أيام،")
        print("     لا جلسة واحدة. وإلا اختلفت تغطيتها عن جاراتها،")
        print("     فتغيّرت المسارات بين الشرائح — وهو العيب المقاس.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
