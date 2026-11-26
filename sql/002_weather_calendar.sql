-- زحمة — إضافات: الطقس + مؤشرات الجودة
-- يُنفَّذ بعد 001_schema.sql

CREATE TABLE IF NOT EXISTS weather_obs (
    id          bigserial PRIMARY KEY,
    ts_utc      timestamptz NOT NULL,
    ts_bucket   timestamptz NOT NULL,
    temp_c      double precision,
    precip_mm   double precision,
    rain_mm     double precision,
    weather_code int,
    wind_kmh    double precision,
    visibility_m double precision,
    factor      double precision NOT NULL DEFAULT 1.0,
    UNIQUE (ts_bucket)
);
CREATE INDEX IF NOT EXISTS weather_ts_idx ON weather_obs (ts_utc DESC);

-- جدول التقويم: يحدد نوع اليوم وأعلامه
CREATE TABLE IF NOT EXISTS calendar_days (
    day_local   date PRIMARY KEY,
    day_type    text NOT NULL,              -- WORKDAY|FRIDAY|SATURDAY|HOLIDAY
    is_ramadan  boolean DEFAULT false,
    is_school   boolean DEFAULT true,
    is_summer   boolean DEFAULT false,
    note        text
);

-- تعبئة أساسية: أنواع الأيام للسنوات القادمة (تُصحَّح يدوياً للعطل)
INSERT INTO calendar_days (day_local, day_type, is_school, is_summer)
SELECT d::date,
       CASE EXTRACT(ISODOW FROM d)
            WHEN 5 THEN 'FRIDAY'
            WHEN 6 THEN 'SATURDAY'
            ELSE 'WORKDAY' END,
       NOT (EXTRACT(MONTH FROM d) IN (7, 8)),
       EXTRACT(MONTH FROM d) IN (7, 8)
FROM generate_series('2026-01-01'::date, '2027-12-31'::date, '1 day') d
ON CONFLICT (day_local) DO NOTHING;

-- رمضان 1448 (تقديري): 2027-02-08 .. 2027-03-09
UPDATE calendar_days
SET is_ramadan = true
WHERE day_local BETWEEN '2027-02-08' AND '2027-03-09';

-- رمضان 1447 (تقديري): 2026-02-18 .. 2026-03-19
UPDATE calendar_days
SET is_ramadan = true
WHERE day_local BETWEEN '2026-02-18' AND '2026-03-19';
