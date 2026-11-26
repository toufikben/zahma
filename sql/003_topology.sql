-- زحمة — إضافة الطوبولوجيا: معرّفات عقد OSM
-- السبب: ربط الحواف بالإحداثيات المقرّبة أنتج 7544 مكوّناً منفصلاً.
-- بمعرّفات العقد الحقيقية، الشبكة متصلة كما هي في الواقع.

ALTER TABLE segments ADD COLUMN IF NOT EXISTS u bigint;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS v bigint;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS measurable boolean DEFAULT false;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS in_main boolean DEFAULT false;

CREATE INDEX IF NOT EXISTS segments_u_idx ON segments (u);
CREATE INDEX IF NOT EXISTS segments_v_idx ON segments (v);
CREATE INDEX IF NOT EXISTS segments_measurable_idx ON segments (measurable) WHERE measurable;
CREATE INDEX IF NOT EXISTS segments_main_idx ON segments (in_main) WHERE in_main;
CREATE INDEX IF NOT EXISTS segments_importance_idx ON segments (importance DESC);

-- التوجيه يقرأ كل المقاطع: نضيف فهرساً على الطول
CREATE INDEX IF NOT EXISTS segments_length_idx ON segments (length_m);
