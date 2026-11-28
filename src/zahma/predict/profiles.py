"""بناء ملفات تعريف السرعة — من العينات الخام إلى نموذج قابل للتنبؤ.

المنهج:
1. لكل عينة، نحدد (المقطع، نوع اليوم، الشريحة الزمنية، علم رمضان، علم الدراسة).
2. نحسب p10/p50/p90 لكل مجموعة — لا متوسط.
   لماذا: p50 يقاوم الشواذ، وp10/p90 يعطيان عدم اليقين الحقيقي.
3. نطبّق حداً أدنى للعينات (n >= 3) وإلا نترك المقطع بلا ملف.

هذه الخطوة هي الفرق بين «جمع بيانات» و«نموذج».
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import text

from zahma.db import session_scope

MIN_SAMPLES = 3

# ── إسناد أيام المصدر إلى أيامنا: بالسلوك لا بالتقويم ─────────────────
#
# **العيب الذي يصلحه هذا الجدول:** كان البناء يقرأ `calendar_days.day_type`
# مباشرة، أي يثق أن يوم الأحد في المصدر هو يوم أحد جزائري. القياس يثبت
# العكس تماماً.
#
# مقاس على 20 زوجاً عند 17:00 (متوسط المدة بالدقائق):
#
#     المصدر: الاثنين–الخميس 47.4 | الجمعة 47.3 | السبت 44.2 | الأحد 43.8
#
# أي أن Mapbox يطبّق **عطلة غربية**: السبت والأحد فارغان، والجمعة ذروة
# كاملة. والجزائر عكس ذلك: الجمعة أفرغ يوم، والأحد يوم عمل.
#
# الأثر المقاس قبل الإصلاح: كنّا نعرض للمستخدم أن الجمعة أسوأ يوم بفارق
# **3.5 دقيقة**، بينما هي أفرغ يوم في الجزائر. وكنّا نُدخل الأحد (فارغاً)
# في ملف `WORKDAY` فيخفّف ذروة أيام العمل الحقيقية بـ**3.6 دقيقة**.
#
# **الإصلاح:** نُسند يوم المصدر إلى اليوم الجزائري الذي يشبهه سلوكاً:
#   - أحد المصدر (أفرغ) ⇒ جمعة عندنا (أفرغ)
#   - سبت المصدر (شبه فارغ) ⇒ سبت عندنا
#   - اثنين–جمعة المصدر (ذروة) ⇒ يوم عمل عندنا
#
# **حدّ صريح:** هذا إسقاط سلوكي لا معرفة. نعرف أن الأحد المصدر يشبه
# الجمعة عندنا في *الفراغ*، ولا نعرف أن منحنى الجمعة الجزائري يساوي
# منحنى الأحد الغربي ساعةً بساعة. لذلك يبقى هذا أكبر مصدر خطأ منهجي في
# المنتج، ويحتاج حقيقة أرضية جزائرية لتصحيحه — وهي غير متاحة من أي مزوّد.
SOURCE_DAY_TYPE_MAP: dict[int, str] = {
    1: "WORKDAY",   # الاثنين
    2: "WORKDAY",   # الثلاثاء
    3: "WORKDAY",   # الأربعاء
    4: "WORKDAY",   # الخميس
    5: "WORKDAY",   # الجمعة (المصدر): ذروة كاملة — نُبقيها يوم عمل
    6: "SATURDAY",  # السبت (المصدر): شبه فارغ
    7: "FRIDAY",    # الأحد (المصدر): أفرغ يوم ⇒ جمعة عندنا
}


def _day_type_sql(alias: str = "s") -> str:
    """تعبير SQL يحوّل تاريخ العينة إلى نوع يوم جزائري بالسلوك.

    يُبنى من `SOURCE_DAY_TYPE_MAP` — مصدر واحد للحقيقة. لو كُتب التعبير
    يدوياً في كل استعلام لاختلف بين بناء الملفات وبناء ملفات الأصناف.

    **العطلات تبقى عطلات:** إن صنّفها تقويمنا `HOLIDAY` فلا نُعيد إسنادها،
    لأن يوم عطاء رسمي جزائري ليس له مقابل في أيام الأسبوع الغربية.

    **ورمضان ليس نوع يوم — بل عمود منفصل.** كان هذا التعبير يُنتج
    `day_type='RAMADAN'`، بينما المحرك يقرأ
    `WHERE day_type='WORKDAY' AND is_ramadan=true`. أي أن صفوف رمضان
    كانت تُكتب باسم **لا يُقرأ أبداً**: 30 يوماً في السنة تُجمع ثم تُهمَل
    بصمت، والنموذج يعود إلى نمط العمل العادي في رمضان — وهو أسوأ خطأ
    ممكن لأن رمضان يغيّر توقيت الذروة كلياً في الجزائر.

    والتصميم الصحيح: `day_type` يحمل سلوك الأسبوع (WORKDAY/FRIDAY/
    SATURDAY/HOLIDAY)، و`is_ramadan` عمود مستقل يضاعف التركيبات. المحرك
    يفلتر بالاثنين معاً — فالتعبير يجب أن يطابقه.
    """
    whens = "\n                ".join(
        f"WHEN {dow} THEN '{dtype}'" for dow, dtype in sorted(SOURCE_DAY_TYPE_MAP.items())
    )
    return f"""CASE
                    WHEN c.day_type = 'HOLIDAY' THEN 'HOLIDAY'
                    ELSE CASE EXTRACT(ISODOW FROM ({alias}.ts_utc AT TIME ZONE 'Africa/Algiers'))::int
                {whens}
                    END
                END"""


def rebuild(
    verbose: bool = True,
    sources: tuple[str, ...] | None = None,
    exclude_days: tuple[date, ...] | None = None,
    min_samples: int = MIN_SAMPLES,
) -> dict:
    """يعيد بناء speed_profiles من samples.

    يتم كل شيء في Postgres — أسرع بكثير من المعالجة في Python،
    ويستفيد من الفهارس الموجودة.

    `sources`: أي مصادر تُدخل في الحساب. الافتراضي كل شيء. تمرير
    `("mapbox",)` يبني الملفات من بيانات حقيقية فقط — وهذا مهم قبل
    الإطلاق: خلط بيانات `mock` (منحنى رياضي مصطنع) مع قياسات حقيقية
    يجعل الملفات تبدو أفضل مما هي، ويُخفي فجوات التغطية الحقيقية.

    `min_samples`: الحد الأدنى لعينات (مقطع × نوع يوم × شريحة). الافتراضي
    3 — يحمي من ملف مبني على عيّنة واحدة **صاخبة**. لكن هذا الحماية تفترض
    ضجيجاً، وجدول Mapbox بلا ضجيج: يعيد رقماً واحداً ثابتاً لكل (مقطع،
    شريحة، يوم). فيه يوم واحد من الجمعة يعطي n=1 لكل تركيبة — وهو
    **اكتمال** لا نقص. تمرير 1 يبني ملفات الجمعة والسبت، ويجب أن يقرنه
    القارئ بعلم أن n=1.
    """
    t0 = datetime.now(UTC)

    src_clause = ""
    params: dict = {}
    if sources:
        # المقارنة عبر ::text لا عبر نوع enum مباشرة: psycopg يرسل
        # قائمة Python كـtext[]، وPostgres لا يحوّلها إلى source_kind[]
        # تلقائياً في هذا السياق — فتعود النتيجة صفراً بلا أي خطأ.
        # عيب صامت: الملفات تُبنى فارغة ويبدو أن لا بيانات.
        src_clause = "AND s.source::text = ANY(CAST(:sources AS text[]))"
        params["sources"] = list(sources)
    if exclude_days:
        # حجز يوم للتقييم: نبني الملفات من بقية الأيام ثم نقيس دقتها
        # على اليوم المحجوز. بلا هذا، التقييم دائري — نقارن البيانات
        # بنفسها فنحصل على خطأ شبه صفر لا يعني شيئاً.
        src_clause += (
            " AND (s.ts_utc AT TIME ZONE 'Africa/Algiers')::date <> ALL("
            "CAST(:excl AS date[]))"
        )
        params["excl"] = list(exclude_days)

    sql = text(
        f"""
        WITH tagged AS (
            SELECT
                s.segment_id,
                s.speed_kmh,
                {_day_type_sql("s")} AS d_type,
                c.is_ramadan,
                c.is_school,
                ((EXTRACT(HOUR FROM (s.ts_utc AT TIME ZONE 'Africa/Algiers')) * 4)
                 + FLOOR(EXTRACT(MINUTE FROM (s.ts_utc AT TIME ZONE 'Africa/Algiers')) / 15))::smallint
                 AS bucket_15m
            FROM samples s
            JOIN calendar_days c
              ON c.day_local = (s.ts_utc AT TIME ZONE 'Africa/Algiers')::date
            WHERE s.speed_kmh IS NOT NULL
              AND s.speed_kmh > 0
              AND s.speed_kmh <= 200
              {src_clause}
        ),
        profiled AS (
            SELECT
                segment_id,
                d_type AS day_type,
                bucket_15m,
                is_ramadan,
                is_school,
                percentile_cont(0.10) WITHIN GROUP (ORDER BY speed_kmh) AS p10,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY speed_kmh) AS p50,
                percentile_cont(0.90) WITHIN GROUP (ORDER BY speed_kmh) AS p90,
                COUNT(*) AS n
            FROM tagged
            GROUP BY segment_id, d_type, bucket_15m, is_ramadan, is_school
            HAVING COUNT(*) >= {min_samples}
        )
        INSERT INTO speed_profiles
          (segment_id, day_type, bucket_15m, is_ramadan, is_school,
           p10_speed, p50_speed, p90_speed, samples_n, updated_at)
        SELECT segment_id, day_type, bucket_15m, is_ramadan, is_school,
               p10, p50, p90, n, now()
        FROM profiled
        ON CONFLICT (segment_id, day_type, bucket_15m, is_ramadan, is_school)
        DO UPDATE SET
            p10_speed = EXCLUDED.p10_speed,
            p50_speed = EXCLUDED.p50_speed,
            p90_speed = EXCLUDED.p90_speed,
            samples_n = EXCLUDED.samples_n,
            updated_at = now()
        """
    )

    with session_scope() as s:
        s.execute(text("TRUNCATE speed_profiles"))
        s.execute(sql, params)
        n = s.execute(text("SELECT COUNT(*) FROM speed_profiles")).scalar()
        n_seg = s.execute(text("SELECT COUNT(DISTINCT segment_id) FROM speed_profiles")).scalar()
        # تقرير من **حُذف** لا من بقي. الحد الأدنى MIN_SAMPLES صامت بطبيعته:
        # يمرّ يوم كامل بلا ملف ولا يقول شيئاً. قياس حقيقي: الجمعة والسبت
        # لهما 77,332 و68,811 تركيبة بمتوسط عينة **واحدة** لكل تركيبة،
        # فحُذفت كلها. بلا هذا التقرير يبدو الأمر «لا بيانات» بينما
        # البيانات موجودة والحد هو السبب.
        dropped = s.execute(
            text(
                f"""
                WITH tagged AS (
                    SELECT
                        s.segment_id,
                        s.speed_kmh,
                        {_day_type_sql("s")} AS d_type,
                        c.is_ramadan,
                        c.is_school,
                        ((EXTRACT(HOUR FROM (s.ts_utc AT TIME ZONE 'Africa/Algiers')) * 4)
                         + FLOOR(EXTRACT(MINUTE FROM (s.ts_utc AT TIME ZONE 'Africa/Algiers')) / 15))::smallint
                         AS bucket_15m
                    FROM samples s
                    JOIN calendar_days c
                      ON c.day_local = (s.ts_utc AT TIME ZONE 'Africa/Algiers')::date
                    WHERE s.speed_kmh IS NOT NULL
                      AND s.speed_kmh > 0
                      AND s.speed_kmh <= 200
                      {src_clause}
                )
                SELECT d_type,
                       COUNT(*) AS combos,
                       ROUND(AVG(n), 2) AS avg_n,
                       COUNT(*) FILTER (WHERE n < {min_samples}) AS below_min,
                       COUNT(DISTINCT segment_id) AS segs
                FROM (
                    SELECT d_type, segment_id, bucket_15m, is_ramadan, is_school,
                           COUNT(*) AS n
                    FROM tagged
                    GROUP BY 1, 2, 3, 4, 5
                ) x
                GROUP BY 1
                ORDER BY 1
                """
            ),
            params,
        ).all()

    elapsed = (datetime.now(UTC) - t0).total_seconds()
    out = {
        "profiles": int(n or 0),
        "segments": int(n_seg or 0),
        "seconds": round(elapsed, 1),
        "dropped": [
            {
                "day_type": str(dt),
                "combos": int(combos),
                "avg_samples": float(avg_n or 0),
                "below_min": int(below or 0),
                "segments": int(segs or 0),
            }
            for dt, combos, avg_n, below, segs in dropped
        ],
    }
    if verbose:
        print(f"[profiles] {out['profiles']:,} rows, {out['segments']:,} segments, {out['seconds']}s")
        for d in out["dropped"]:
            if d["below_min"] and d["below_min"] == d["combos"]:
                print(
                    f"  ! {d['day_type']}: كل الـ{d['combos']:,} تركيبة تحت "
                    f"الحد ({min_samples}) — متوسط {d['avg_samples']:.2f} عينة. "
                    f"هذا اليوم بلا ملف تعريف."
                )
    return out


def rebuild_class_profiles(
    verbose: bool = True, sources: tuple[str, ...] | None = None
) -> dict:
    """أولوية صنف الطريق — من المقاطع المقيسة إلى كل مقاطع الصنف.

    لماذا هذا ضروري: المسار داخل المدينة يمرّ عبر residential/tertiary
    لا نقيسها. بلا هذه الأولوية يرجع كل مقطع غير مقيس إلى السرعة الحرة،
    فيصبح منحنى الانطلاق مسطّحاً — أي أن المنتج لا يعرف الزحمة أصلاً.

    المنهج: نجمع عينات كل صنف في (نوع يوم، شريحة زمنية)، ونأخذ
    p10/p50/p90. المتوسط **مرجّح بطول المقطع** لا بالعدد: مقطع سريع
    طوله 2 كم يمثل الصنف أكثر من وصلة 8 أمتار.

    الحد الأدنى: 2 مقطع و5 عينات، وإلا لا نُنشئ صفاً — الصمت أفضل من
    أولوية مبنية على عينة واحدة.

    `sources`: مثل `rebuild` — `("mapbox",)` يبني من بيانات حقيقية فقط.
    """
    t0 = datetime.now(UTC)

    src_clause = ""
    params: dict = {}
    if sources:
        src_clause = "AND s.source::text = ANY(CAST(:sources AS text[]))"
        params["sources"] = list(sources)

    sql = text(
        f"""
        WITH tagged AS (
            SELECT
                s.segment_id,
                sg.road_class,
                s.speed_kmh,
                sg.length_m,
                sg.speed_free_kmh,
                {_day_type_sql("s")} AS d_type,
                c.is_ramadan,
                ((EXTRACT(HOUR FROM (s.ts_utc AT TIME ZONE 'Africa/Algiers')) * 4)
                 + FLOOR(EXTRACT(MINUTE FROM (s.ts_utc AT TIME ZONE 'Africa/Algiers')) / 15))::smallint
                 AS bucket_15m
            FROM samples s
            JOIN segments sg ON sg.seg_id = s.segment_id
            JOIN calendar_days c
              ON c.day_local = (s.ts_utc AT TIME ZONE 'Africa/Algiers')::date
            WHERE s.speed_kmh IS NOT NULL
              AND s.speed_kmh > 0
              AND s.speed_kmh <= 200
              AND sg.road_class IS NOT NULL
              AND sg.speed_free_kmh > 5
              {src_clause}
        ),
        profiled AS (
            SELECT
                road_class,
                d_type AS day_type,
                bucket_15m,
                is_ramadan,
                percentile_cont(0.10) WITHIN GROUP (ORDER BY speed_kmh) AS p10,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY speed_kmh) AS p50,
                percentile_cont(0.90) WITHIN GROUP (ORDER BY speed_kmh) AS p90,
                -- نسبة الأداء: السرعة الفعلية ÷ السرعة الحرة للمقطع نفسه.
                -- كمية بلا وحدة تصف سلوك الشارع نسبةً إلى طبيعته، فتنطبق
                -- على مقطع لم نمشِ عليه. مقاسة: تخفض p90 من 84% إلى 59%
                -- وتزيل التحيز (+6.9% ← -0.4%).
                percentile_cont(0.10) WITHIN GROUP (
                    ORDER BY speed_kmh / speed_free_kmh
                ) AS r10,
                percentile_cont(0.50) WITHIN GROUP (
                    ORDER BY speed_kmh / speed_free_kmh
                ) AS r50,
                percentile_cont(0.90) WITHIN GROUP (
                    ORDER BY speed_kmh / speed_free_kmh
                ) AS r90,
                COUNT(*) AS n,
                COUNT(DISTINCT segment_id) AS n_seg
            FROM tagged
            GROUP BY road_class, d_type, bucket_15m, is_ramadan
            HAVING COUNT(*) >= 5 AND COUNT(DISTINCT segment_id) >= 2
        )
        INSERT INTO class_profiles
          (road_class, day_type, bucket_15m, is_ramadan,
           p10_speed, p50_speed, p90_speed,
           ratio_p10, ratio_p50, ratio_p90,
           samples_n, segments_n, updated_at)
        SELECT road_class, day_type, bucket_15m, is_ramadan,
               p10, p50, p90,
               r10, r50, r90,
               n, n_seg, now()
        FROM profiled
        ON CONFLICT (road_class, day_type, bucket_15m, is_ramadan)
        DO UPDATE SET
            p10_speed = EXCLUDED.p10_speed,
            p50_speed = EXCLUDED.p50_speed,
            p90_speed = EXCLUDED.p90_speed,
            ratio_p10 = EXCLUDED.ratio_p10,
            ratio_p50 = EXCLUDED.ratio_p50,
            ratio_p90 = EXCLUDED.ratio_p90,
            samples_n = EXCLUDED.samples_n,
            segments_n = EXCLUDED.segments_n,
            updated_at = now()
        """
    )

    with session_scope() as s:
        s.execute(text("TRUNCATE class_profiles"))
        s.execute(sql, params)
        n = s.execute(text("SELECT COUNT(*) FROM class_profiles")).scalar()
        n_cls = s.execute(
            text("SELECT COUNT(DISTINCT road_class) FROM class_profiles")
        ).scalar()

    elapsed = (datetime.now(UTC) - t0).total_seconds()
    out = {"class_profiles": int(n or 0), "classes": int(n_cls or 0), "seconds": round(elapsed, 1)}
    if verbose:
        print(
            f"[class-profiles] {out['class_profiles']:,} rows, "
            f"{out['classes']} classes, {out['seconds']}s"
        )
    return out


def coverage_report() -> list[dict]:
    """تقرير تغطية: أي مقاطع لها ملف، وأيها لا."""
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                WITH prof AS (
                    SELECT DISTINCT segment_id FROM speed_profiles
                )
                SELECT
                    sg.road_class,
                    COUNT(*) AS total,
                    COUNT(pr.segment_id) AS with_profile,
                    ROUND(100.0 * COUNT(pr.segment_id) / COUNT(*), 1) AS pct
                FROM segments sg
                LEFT JOIN prof pr ON pr.segment_id = sg.seg_id
                GROUP BY sg.road_class
                ORDER BY total DESC
                """
            )
        ).mappings().all()
    return [dict(r) for r in rows]


def quality_report() -> dict:
    """هل الملفات سليمة؟ فحص p10 <= p50 <= p90 ووجود تباين."""
    with session_scope() as s:
        bad_order = s.execute(
            text(
                "SELECT COUNT(*) FROM speed_profiles "
                "WHERE NOT (p10_speed <= p50_speed AND p50_speed <= p90_speed)"
            )
        ).scalar()
        flat = s.execute(
            text(
                "SELECT COUNT(*) FROM speed_profiles "
                "WHERE abs(p90_speed - p10_speed) < 0.5"
            )
        ).scalar()
        tot = s.execute(text("SELECT COUNT(*) FROM speed_profiles")).scalar()
        avg_n = s.execute(text("SELECT AVG(samples_n) FROM speed_profiles")).scalar()
    return {
        "total": int(tot or 0),
        "bad_order": int(bad_order or 0),
        "flat_profiles": int(flat or 0),
        "avg_samples": round(float(avg_n or 0), 1),
    }
