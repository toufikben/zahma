"""هل ملفات التعريف (ما يقرأه المحرّك فعلاً) تميّز الجمعة؟

**الفرق عن كل القياسات السابقة:** كل ما سبق قاس **العينات الخام**. لكن
المحرّك لا يقرأ العينات — يقرأ `class_profiles` و`speed_profiles`. لو
كانت هناك أي معالجة تفصل الجمعة، لظهرت هنا.

**السؤال المحدد:** لأي (صنف طريق، شريحة زمنية) يوجد صفّان — واحد
`WORKDAY` وواحد `FRIDAY` — ما الفرق بين `ratio_p50` فيهما؟

إن كان الفرق صفراً أو داخل الضجيج، فالمحرّك يعطي الجمعة نفس الرقم
بالضبط الذي يعطيه لثلاثاء — لكنه **يعلن ثقة 0.6** كما لو كان يعرف
الجمعة. هذا هو العيب: الثقة تقول «أعرف هذا اليوم» والرقم يقول «لا».

**ولماذا يهم:** الجمعة في الجزائر أهدأ يوم وأكثرها تنقلاً للزيارات.
المستخدم يفتح التطبيق صباح الجمعة، يرى رقماً واثقاً، ويجد الطريق
مختلفاً. الثقة الكاذبة أسوأ من عدم المعرفة — لأنها تمنع المستخدم من
التشكيك.

التشغيل: python scripts/profile_friday_gap.py
"""

from __future__ import annotations

from sqlalchemy import text

from zahma.db import session_scope


def main() -> int:
    with session_scope() as s:
        # 1. كم صفاً لكل نوع يوم؟
        rows = s.execute(
            text(
                """
                SELECT day_type, count(*) AS rows, count(DISTINCT road_class) AS classes,
                       round(avg(ratio_p50)::numeric, 4) AS mean_ratio,
                       round(avg(p50_speed)::numeric, 3) AS mean_speed
                FROM class_profiles
                GROUP BY 1 ORDER BY 1
                """
            )
        ).all()

        print("── class_profiles حسب نوع اليوم")
        print(f"   {'نوع':<10} {'صفوف':>7} {'أصناف':>7} {'نسبة':>9} {'سرعة':>9}")
        for dt, n, c, mr, ms in rows:
            print(f"   {dt:<10} {n:>7,} {c:>7} {float(mr or 0):>9.4f} {float(ms or 0):>9.3f}")

        # 2. المقارنة المباشرة: نفس الصنف، نفس الشريحة، يومان مختلفان
        print("\n── الفرق بين ملف الجمعة وملف أيام العمل (نفس الصنف والشريحة)")
        for other in ("FRIDAY", "SATURDAY"):
            r = s.execute(
                text(
                    """
                    SELECT count(*) AS pairs,
                           round(avg(abs(f.ratio_p50 - w.ratio_p50))::numeric, 5) AS mae_ratio,
                           round(max(abs(f.ratio_p50 - w.ratio_p50))::numeric, 4) AS max_ratio,
                           round(avg(abs(f.p50_speed - w.p50_speed))::numeric, 4) AS mae_speed,
                           count(*) FILTER (
                               WHERE abs(f.ratio_p50 - w.ratio_p50) < 0.005
                           ) AS exact
                    FROM class_profiles f
                    JOIN class_profiles w
                      ON w.road_class = f.road_class
                     AND w.bucket_15m = f.bucket_15m
                     AND w.is_ramadan = f.is_ramadan
                     AND w.day_type = 'WORKDAY'
                    WHERE f.day_type = :dt
                      AND f.ratio_p50 IS NOT NULL
                      AND w.ratio_p50 IS NOT NULL
                    """
                ),
                {"dt": other},
            ).one()
            pairs, mae_r, max_r, mae_s, exact = r
            if not pairs:
                print(f"   {other}: لا أزواج")
                continue
            print(
                f"   {other:<9} أزواج {pairs:>5,}  "
                f"متوسط فرق النسبة {float(mae_r):.5f}  أقصى {float(max_r):.4f}  "
                f"متوسط فرق السرعة {float(mae_s):.3f} كم/س  "
                f"مطابق تماماً {exact/pairs*100:.1f}%"
            )

        # 3. الضابطة: يومان من أيام العمل يجب أن يكونا متطابقين أيضاً
        print("\n── ضابطة: MONDAY مقابل WORKDAY (يجب أن يكونا متطابقين)")
        r = s.execute(
            text(
                """
                SELECT count(*) AS pairs,
                       round(avg(abs(m.ratio_p50 - w.ratio_p50))::numeric, 5) AS mae,
                       count(*) FILTER (WHERE abs(m.ratio_p50 - w.ratio_p50) < 0.005) AS exact
                FROM class_profiles m
                JOIN class_profiles w
                  ON w.road_class = m.road_class
                 AND w.bucket_15m = m.bucket_15m
                 AND w.is_ramadan = m.is_ramadan
                 AND w.day_type = 'WORKDAY'
                WHERE m.day_type = 'MONDAY' AND m.ratio_p50 IS NOT NULL
                  AND w.ratio_p50 IS NOT NULL
                """
            )
        ).one()
        pairs, mae, exact = r
        if pairs:
            print(f"   MONDAY: أزواج {pairs:,}  متوسط فرق {float(mae):.5f}  مطابق {exact/pairs*100:.1f}%")
        else:
            print("   MONDAY غير موجود كصف مستقل — أي أن كل أيام العمل في نوع واحد.")

        # 4. أكبر الفروق في الجمعة — هل هي في ساعات حساسة؟
        print("\n── أكبر 8 فروق للجمعة (صنف، ساعة، نسبة أيام العمل ← الجمعة)")
        detail = s.execute(
            text(
                """
                SELECT f.road_class,
                       (f.bucket_15m / 4) AS hr,
                       w.ratio_p50 AS wd_ratio,
                       f.ratio_p50 AS fr_ratio,
                       abs(f.ratio_p50 - w.ratio_p50) AS d
                FROM class_profiles f
                JOIN class_profiles w
                  ON w.road_class = f.road_class
                 AND w.bucket_15m = f.bucket_15m
                 AND w.is_ramadan = f.is_ramadan
                 AND w.day_type = 'WORKDAY'
                WHERE f.day_type = 'FRIDAY'
                  AND f.ratio_p50 IS NOT NULL AND w.ratio_p50 IS NOT NULL
                ORDER BY d DESC
                LIMIT 8
                """
            )
        ).all()
        for rc, hr, wr, fr, d in detail:
            print(
                f"   {rc:<12} {hr:>2}h  {float(wr):.3f} ← {float(fr):.3f}  "
                f"فرق {float(d):.4f}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
