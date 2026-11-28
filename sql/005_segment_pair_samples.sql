-- تفصيل القياسات لكل زوج: يحفظ ما كان `ON CONFLICT` يمحوه.
--
-- **العيب الذي يحلّه هذا الجدول:** `samples` مفتاحه (segment_id, source,
-- ts_bucket) — صف واحد لكل مقطع في الشريحة. لكننا نجمع 17.2 زوجاً، والمقطع
-- نفسه يمر به عدة أزواج بقيم مختلفة. فكان `ON CONFLICT DO UPDATE` يجعل
-- **آخر كاتب يفوز**، والكتابة متوازية فالفائز عشوائي.
--
-- المقاس: ~6,800 حافة في الشريحة، 4,350 صفاً مخزَّناً ⇒ **~36% تُمحى**.
-- وأُثبت مباشرة: مقطع بقيمة 20 ثم 80 كم/س يبقى صف واحد بـ80، و20 ضاعت.
--
-- **الحل:** هذا الجدول يحفظ كل قياس بزوجه ومسافته، بلا تصادم. و`samples`
-- يبقى مجمَّعاً (وسيط موزون) — الشكل الذي يحتاجه التنبؤ.
--
-- ولماذا المسافة: حافة 5 م لا تساوي حافة 300 م عند حساب وسيط المقطع.

CREATE TABLE IF NOT EXISTS segment_pair_samples (
    id          bigserial PRIMARY KEY,
    segment_id  bigint NOT NULL REFERENCES segments(seg_id) ON DELETE CASCADE,
    pair_id     int NOT NULL REFERENCES od_pairs(pair_id) ON DELETE CASCADE,
    source      source_kind NOT NULL,
    ts_utc      timestamptz NOT NULL,
    ts_bucket   timestamptz NOT NULL,
    speed_kmh   double precision NOT NULL,
    dist_m      double precision,
    offset_m    double precision,
    created_at  timestamptz NOT NULL DEFAULT now(),
    -- المفتاح يمنح idempotency: إعادة جمع نفس (الزوج، المقطع، الشريحة)
    -- تحدّث القيمة بدل أن تُكرّرها.
    UNIQUE (segment_id, pair_id, source, ts_bucket)
);

CREATE INDEX IF NOT EXISTS sps_bucket_idx
    ON segment_pair_samples (ts_bucket DESC);

CREATE INDEX IF NOT EXISTS sps_pair_bucket_idx
    ON segment_pair_samples (pair_id, ts_bucket DESC);

CREATE INDEX IF NOT EXISTS sps_seg_bucket_idx
    ON segment_pair_samples (segment_id, ts_bucket DESC);
