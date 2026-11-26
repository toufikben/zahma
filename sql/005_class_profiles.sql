-- ============================================================
-- 005: أولوية صنف الطريق (Class Prior)
--
-- المشكلة التي يحلها هذا الملف:
-- المسارات داخل المدينة تمرّ عبر مقاطع residential/tertiary لا نقيسها
-- (لا حصة TomTom ولا Mapbox تكفي لكل شوارع العاصمة). في النسخة السابقة
-- كان كل مقطع غير مقيس يرجع إلى «السرعة الحرة» — وهي ثابتة لا تعرف
-- الساعة. النتيجة: منحنى الانطلاق مسطّح تماماً، والمنتج يبدو كأنه
-- لا يعرف الزحمة، وهو فعلاً لا يعرفها على تلك المقاطع.
--
-- الحل الصادق: لكل (صنف طريق، نوع يوم، شريحة زمنية) نحسب سرعة نموذجية
-- من المقاطع **المقيسة** من نفس الصنف. المقطع غير المقيس يرث سلوك
-- صنفه الزمني — فيعرف أن الطرق الرئيسية تتباطأ 08:00 وتهدأ 14:00.
--
-- هذا «مُقدَّر» لا «مقيس»، ويُعرض للمستخدم بثقة أقل وبوسم واضح.
-- الفرق بين 0.35 و0.6 في الثقة هو الفرق بين «نعرف» و«نستنتج».
-- ============================================================

CREATE TABLE IF NOT EXISTS class_profiles (
    road_class   text     NOT NULL,
    day_type     text     NOT NULL,
    bucket_15m   smallint NOT NULL,
    is_ramadan   boolean  NOT NULL DEFAULT false,
    p10_speed    double precision,
    p50_speed    double precision,
    p90_speed    double precision,
    samples_n    int      NOT NULL DEFAULT 0,
    segments_n   int      NOT NULL DEFAULT 0,
    updated_at   timestamptz DEFAULT now(),
    PRIMARY KEY (road_class, day_type, bucket_15m, is_ramadan)
);

CREATE INDEX IF NOT EXISTS class_profiles_lookup_idx
    ON class_profiles (road_class, day_type, bucket_15m);
