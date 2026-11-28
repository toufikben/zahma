-- جدول انحراف الجدول: يسجّل ما كان مخزَّناً وما أعاده المصدر لاحقاً.
--
-- **لماذا هذا الجدول ضروري:** `samples` يستخدم ON CONFLICT ... DO UPDATE،
-- فإعادة جمع نفس الساعة **تستبدل** القيمة القديمة بصمت. النتيجة: لا يمكن
-- أبداً معرفة أن الجدول تغيّر — الانحراف يُمحى في لحظة كتابته.
--
-- وهذا ليس نظرياً: قياسنا كشف خانة واحدة من 9 أعادت 9.92 بدل 33.82. بلا
-- هذا الجدول، لو أعدنا جمعها لما عرفنا أن شيئاً تغيّر.
--
-- لذلك: كل عملية تحقّق تقارن المخزَّن بالجديد **قبل** الاستبدال، وتسجّل
-- الفرق هنا. الجدول يصير سجل التغييرات الوحيد للمصدر.

CREATE TABLE IF NOT EXISTS table_drift (
    id           bigserial PRIMARY KEY,
    detected_at  timestamptz NOT NULL DEFAULT now(),
    source       source_kind NOT NULL,
    pair_id      int,
    depart_at    timestamptz NOT NULL,
    scope        text NOT NULL,              -- 'route' أو 'segment'
    ref_id       bigint NOT NULL,            -- pair_id أو segment_id
    old_value    double precision,
    new_value    double precision,
    abs_diff     double precision,
    rel_diff     double precision
);

CREATE INDEX IF NOT EXISTS table_drift_detected_idx
    ON table_drift (detected_at DESC);

CREATE INDEX IF NOT EXISTS table_drift_depart_idx
    ON table_drift (depart_at DESC);

-- ملخص سريع: هل تغيّر الجدول إطلاقاً، وبأي حجم؟
CREATE OR REPLACE VIEW table_drift_summary AS
SELECT date_trunc('day', detected_at) AS day,
       source,
       scope,
       count(*) AS changed_rows,
       round(avg(abs_diff)::numeric, 3) AS mean_abs_diff,
       round(max(abs_diff)::numeric, 3) AS max_abs_diff,
       count(DISTINCT depart_at) AS slots_checked
FROM table_drift
GROUP BY 1, 2, 3
ORDER BY 1 DESC;
