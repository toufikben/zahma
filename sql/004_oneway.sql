-- زحمة — اتجاه الطريق
-- السبب: pyrosm يُخرج كل طريق مرة واحدة فقط (0 حواف معاكسة في 294 ألف حافة).
-- الشوارع ذات الاتجاهين تحتاج حافة معاكسة تُضاف عند بناء الرسم، وإلا
-- انقسمت الشبكة إلى 118 ألف مكوّن strongly-connected.

ALTER TABLE segments ADD COLUMN IF NOT EXISTS oneway text;

CREATE INDEX IF NOT EXISTS segments_oneway_idx ON segments (oneway);
