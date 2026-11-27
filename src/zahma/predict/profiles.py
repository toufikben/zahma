"""بناء ملفات تعريف السرعة — من العينات الخام إلى نموذج قابل للتنبؤ.

المنهج:
1. لكل عينة، نحدد (المقطع، نوع اليوم، الشريحة الزمنية، علم رمضان، علم الدراسة).
2. نحسب p10/p50/p90 لكل مجموعة — لا متوسط.
   لماذا: p50 يقاوم الشواذ، وp10/p90 يعطيان عدم اليقين الحقيقي.
3. نطبّق حداً أدنى للعينات (n >= 3) وإلا نترك المقطع بلا ملف.

هذه الخطوة هي الفرق بين «جمع بيانات» و«نموذج».
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from zahma.db import session_scope

MIN_SAMPLES = 3


def rebuild(verbose: bool = True, sources: tuple[str, ...] | None = None) -> dict:
    """يعيد بناء speed_profiles من samples.

    يتم كل شيء في Postgres — أسرع بكثير من المعالجة في Python،
    ويستفيد من الفهارس الموجودة.

    `sources`: أي مصادر تُدخل في الحساب. الافتراضي كل شيء. تمرير
    `("mapbox",)` يبني الملفات من بيانات حقيقية فقط — وهذا مهم قبل
    الإطلاق: خلط بيانات `mock` (منحنى رياضي مصطنع) مع قياسات حقيقية
    يجعل الملفات تبدو أفضل مما هي، ويُخفي فجوات التغطية الحقيقية.
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

    sql = text(
        f"""
        WITH tagged AS (
            SELECT
                s.segment_id,
                s.speed_kmh,
                CASE
                    WHEN c.is_ramadan THEN 'RAMADAN'
                    ELSE c.day_type
                END AS d_type,
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
            HAVING COUNT(*) >= {MIN_SAMPLES}
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

    elapsed = (datetime.now(UTC) - t0).total_seconds()
    out = {"profiles": int(n or 0), "segments": int(n_seg or 0), "seconds": round(elapsed, 1)}
    if verbose:
        print(f"[profiles] {out['profiles']:,} rows, {out['segments']:,} segments, {out['seconds']}s")
    return out


def rebuild_class_profiles(verbose: bool = True) -> dict:
    """أولوية صنف الطريق — من المقاطع المقيسة إلى كل مقاطع الصنف.

    لماذا هذا ضروري: المسار داخل المدينة يمرّ عبر residential/tertiary
    لا نقيسها. بلا هذه الأولوية يرجع كل مقطع غير مقيس إلى السرعة الحرة،
    فيصبح منحنى الانطلاق مسطّحاً — أي أن المنتج لا يعرف الزحمة أصلاً.

    المنهج: نجمع عينات كل صنف في (نوع يوم، شريحة زمنية)، ونأخذ
    p10/p50/p90. المتوسط **مرجّح بطول المقطع** لا بالعدد: مقطع سريع
    طوله 2 كم يمثل الصنف أكثر من وصلة 8 أمتار.

    الحد الأدنى: 2 مقطع و5 عينات، وإلا لا نُنشئ صفاً — الصمت أفضل من
    أولوية مبنية على عينة واحدة.
    """
    t0 = datetime.now(UTC)
    sql = text(
        """
        WITH tagged AS (
            SELECT
                s.segment_id,
                sg.road_class,
                s.speed_kmh,
                sg.length_m,
                CASE WHEN c.is_ramadan THEN 'RAMADAN' ELSE c.day_type END AS d_type,
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
                COUNT(*) AS n,
                COUNT(DISTINCT segment_id) AS n_seg
            FROM tagged
            GROUP BY road_class, d_type, bucket_15m, is_ramadan
            HAVING COUNT(*) >= 5 AND COUNT(DISTINCT segment_id) >= 2
        )
        INSERT INTO class_profiles
          (road_class, day_type, bucket_15m, is_ramadan,
           p10_speed, p50_speed, p90_speed, samples_n, segments_n, updated_at)
        SELECT road_class, day_type, bucket_15m, is_ramadan,
               p10, p50, p90, n, n_seg, now()
        FROM profiled
        ON CONFLICT (road_class, day_type, bucket_15m, is_ramadan)
        DO UPDATE SET
            p10_speed = EXCLUDED.p10_speed,
            p50_speed = EXCLUDED.p50_speed,
            p90_speed = EXCLUDED.p90_speed,
            samples_n = EXCLUDED.samples_n,
            segments_n = EXCLUDED.segments_n,
            updated_at = now()
        """
    )

    with session_scope() as s:
        s.execute(text("TRUNCATE class_profiles"))
        s.execute(sql)
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
