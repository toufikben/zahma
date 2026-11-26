-- زحمة — مخطط قاعدة البيانات (PostgreSQL 16 + PostGIS 3)
-- المبدأ: كل مقطع قابل للقياس، كل قياس قابل للتتبع، كل فجوة مسجّلة.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ============================================================
-- 1. الشبكة
-- ============================================================

CREATE TABLE IF NOT EXISTS segments (
    seg_id            bigint PRIMARY KEY,
    osm_way_id        bigint,
    name              text,
    name_ar           text,
    road_class        text NOT NULL,
    length_m          double precision NOT NULL,
    speed_free_kmh    double precision NOT NULL,
    travel_time_free_s double precision NOT NULL,
    betweenness       double precision DEFAULT 0,
    importance        double precision DEFAULT 0,
    rank              int,
    geom              geometry(LineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS segments_geom_idx ON segments USING GIST (geom);
CREATE INDEX IF NOT EXISTS segments_class_idx ON segments (road_class);
CREATE INDEX IF NOT EXISTS segments_rank_idx ON segments (rank);

-- المحاور: مجموعات مقاطع ذات معنى مروري
CREATE TABLE IF NOT EXISTS corridors (
    corridor_id   int PRIMARY KEY,
    name          text NOT NULL,
    road_class    text NOT NULL,
    seg_count     int NOT NULL,
    total_km      double precision NOT NULL,
    importance    double precision NOT NULL,
    betweenness   double precision NOT NULL,
    centroid      geometry(Point, 4326),
    seg_ids       bigint[] NOT NULL,
    active        boolean DEFAULT true,
    created_at    timestamptz DEFAULT now()
);

-- أزواج الانطلاق/الوصول للمسح الواسع
CREATE TABLE IF NOT EXISTS od_pairs (
    pair_id     int PRIMARY KEY,
    from_name   text NOT NULL,
    from_pt     geometry(Point, 4326) NOT NULL,
    to_name     text NOT NULL,
    to_pt       geometry(Point, 4326) NOT NULL,
    crow_km     double precision NOT NULL,
    weight      double precision NOT NULL,
    active      boolean DEFAULT true
);
CREATE INDEX IF NOT EXISTS od_from_idx ON od_pairs USING GIST (from_pt);
CREATE INDEX IF NOT EXISTS od_to_idx ON od_pairs USING GIST (to_pt);

-- ============================================================
-- 2. القياسات
-- ============================================================

-- نوع المصدر
DO $$ BEGIN
    CREATE TYPE source_kind AS ENUM ('mapbox', 'tomtom_flow', 'tomtom_incidents',
                                     'weather', 'field', 'probe', 'mock');
EXCEPTION WHEN duplicate_object THEN null; END $$;

-- قياس مستوى المقطع (سرعة/زمن)
CREATE TABLE IF NOT EXISTS samples (
    id            bigserial PRIMARY KEY,
    segment_id    bigint NOT NULL REFERENCES segments(seg_id) ON DELETE CASCADE,
    source        source_kind NOT NULL,
    ts_utc        timestamptz NOT NULL,
    ts_bucket     timestamptz NOT NULL,          -- تقريب لـ5 دقائق، مفتاح idempotency
    speed_kmh     double precision,
    freeflow_kmh  double precision,
    travel_time_s double precision,
    confidence    double precision,              -- 0..1 من المصدر نفسه
    ratio         double precision,              -- speed/freeflow
    raw_ref       text,                          -- مرجع للبيانات الخام
    UNIQUE (segment_id, source, ts_bucket)
);
CREATE INDEX IF NOT EXISTS samples_seg_ts_idx ON samples (segment_id, ts_utc DESC);
CREATE INDEX IF NOT EXISTS samples_ts_idx ON samples (ts_utc DESC);
CREATE INDEX IF NOT EXISTS samples_bucket_idx ON samples (ts_bucket DESC);
CREATE INDEX IF NOT EXISTS samples_source_idx ON samples (source, ts_bucket DESC);

-- قياس مستوى الزوج (رحلة كاملة من Mapbox)
CREATE TABLE IF NOT EXISTS route_samples (
    id             bigserial PRIMARY KEY,
    pair_id        int NOT NULL REFERENCES od_pairs(pair_id) ON DELETE CASCADE,
    source         source_kind NOT NULL,
    ts_utc         timestamptz NOT NULL,
    ts_bucket      timestamptz NOT NULL,
    duration_s     double precision NOT NULL,    -- مع الزحمة
    duration_free_s double precision,            -- بلا زحمة (إن توفر)
    distance_m     double precision,
    delay_ratio    double precision,             -- duration / duration_free
    confidence     double precision,
    geometry       geometry(LineString, 4326),
    UNIQUE (pair_id, source, ts_bucket)
);
CREATE INDEX IF NOT EXISTS route_samples_pair_ts_idx ON route_samples (pair_id, ts_utc DESC);
CREATE INDEX IF NOT EXISTS route_samples_bucket_idx ON route_samples (ts_bucket DESC);

-- الأعطال
CREATE TABLE IF NOT EXISTS incidents (
    id          bigserial PRIMARY KEY,
    source      source_kind NOT NULL,
    external_id text NOT NULL,
    ts_utc      timestamptz NOT NULL,
    category    int,
    category_name text,
    severity    int,
    magnitude   int,
    delay_s     int,
    length_m    int,
    description text,
    from_desc   text,
    to_desc     text,
    road_name   text,
    geom        geometry(Geometry, 4326),
    segment_id  bigint REFERENCES segments(seg_id) ON DELETE SET NULL,
    UNIQUE (source, external_id, ts_utc)
);
CREATE INDEX IF NOT EXISTS incidents_ts_idx ON incidents (ts_utc DESC);
CREATE INDEX IF NOT EXISTS incidents_geom_idx ON incidents USING GIST (geom);
CREATE INDEX IF NOT EXISTS incidents_seg_idx ON incidents (segment_id);

-- ============================================================
-- 3. النموذج
-- ============================================================

-- ملف تعريف المقطع: سرعة نموذجية لكل (نوع يوم، شريحة 15 دقيقة)
CREATE TABLE IF NOT EXISTS speed_profiles (
    segment_id   bigint NOT NULL REFERENCES segments(seg_id) ON DELETE CASCADE,
    day_type     text NOT NULL,              -- WORKDAY|FRIDAY|SATURDAY|HOLIDAY
    bucket_15m   smallint NOT NULL,          -- 0..95
    is_ramadan   boolean NOT NULL DEFAULT false,
    is_school    boolean NOT NULL DEFAULT true,
    p10_speed    double precision,
    p50_speed    double precision,
    p90_speed    double precision,
    samples_n    int NOT NULL DEFAULT 0,
    updated_at   timestamptz DEFAULT now(),
    PRIMARY KEY (segment_id, day_type, bucket_15m, is_ramadan, is_school)
);
CREATE INDEX IF NOT EXISTS profiles_lookup_idx
    ON speed_profiles (segment_id, day_type, bucket_15m);

-- التنبؤات المُصدرة (للتقييم والتدقيق)
CREATE TABLE IF NOT EXISTS predictions (
    id            bigserial PRIMARY KEY,
    issued_at     timestamptz NOT NULL DEFAULT now(),
    departure_ts  timestamptz NOT NULL,
    corridor_id   int,
    pair_id       int,
    duration_p50  double precision NOT NULL,
    duration_p90  double precision NOT NULL,
    confidence    double precision NOT NULL,
    model_version text NOT NULL,
    basis         jsonb
);
CREATE INDEX IF NOT EXISTS predictions_pair_idx ON predictions (pair_id, issued_at DESC);

-- ============================================================
-- 4. الجودة والتشغيل
-- ============================================================

-- الفجوات: كل نافذة فاتت تُسجَّل صراحة. النموذج يتجاهلها ولا يخترعها.
CREATE TABLE IF NOT EXISTS collection_gaps (
    id         bigserial PRIMARY KEY,
    source     source_kind NOT NULL,
    from_ts    timestamptz NOT NULL,
    to_ts      timestamptz NOT NULL,
    reason     text,
    detected_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS gaps_source_idx ON collection_gaps (source, from_ts DESC);

-- صحة كل مصدر
CREATE TABLE IF NOT EXISTS source_health (
    source               source_kind PRIMARY KEY,
    last_ok_ts           timestamptz,
    last_error_ts        timestamptz,
    last_error           text,
    consecutive_failures int DEFAULT 0,
    requests_today       int DEFAULT 0,
    day_utc              date,
    circuit_open         boolean DEFAULT false,
    updated_at           timestamptz DEFAULT now()
);

-- استهلاك الحصة (لتجنب تجاوز الحد المجاني)
CREATE TABLE IF NOT EXISTS quota_usage (
    source    source_kind NOT NULL,
    month_utc date NOT NULL,            -- أول يوم من الشهر
    used      int NOT NULL DEFAULT 0,
    limit_hit timestamptz,
    PRIMARY KEY (source, month_utc)
);

-- ============================================================
-- 5. المستخدمون (مجهولون افتراضياً)
-- ============================================================

CREATE TABLE IF NOT EXISTS devices (
    device_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  timestamptz DEFAULT now(),
    last_seen   timestamptz DEFAULT now(),
    locale      text DEFAULT 'ar',
    tz          text DEFAULT 'Africa/Algiers'
);

CREATE TABLE IF NOT EXISTS places (
    id          bigserial PRIMARY KEY,
    device_id   uuid NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    label       text NOT NULL,             -- home | work | custom
    name        text,
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    created_at  timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS places_device_idx ON places (device_id);

CREATE TABLE IF NOT EXISTS departure_windows (
    id          bigserial PRIMARY KEY,
    device_id   uuid NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    from_place  bigint REFERENCES places(id) ON DELETE CASCADE,
    to_place    bigint REFERENCES places(id) ON DELETE CASCADE,
    earliest    time NOT NULL,
    latest      time NOT NULL,
    days        smallint[] NOT NULL DEFAULT '{0,1,2,3,4}',  -- 0=الأحد
    enabled     boolean DEFAULT true
);

-- ============================================================
-- 6. عرض مساعد
-- ============================================================

CREATE OR REPLACE VIEW v_latest_samples AS
SELECT DISTINCT ON (segment_id, source)
       segment_id, source, ts_utc, speed_kmh, freeflow_kmh, ratio, confidence
FROM samples
ORDER BY segment_id, source, ts_utc DESC;

CREATE OR REPLACE VIEW v_source_status AS
SELECT h.source,
       h.last_ok_ts,
       round(extract(epoch FROM (now() - h.last_ok_ts)) / 60)::int AS minutes_stale,
       h.consecutive_failures,
       h.circuit_open,
       coalesce(q.used, 0) AS used_month,
       h.last_error
FROM source_health h
LEFT JOIN quota_usage q
       ON q.source = h.source
      AND q.month_utc = date_trunc('month', now())::date;
