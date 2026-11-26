# 03 — المعمارية التقنية

> هذا المستند يجاوب: بماذا نبنيه؟ بأي بيانات؟ بأي تكلفة؟ وكيف نبقى قانونيين في الجزائر؟

---

## 1. القرار المعماري الأهم: أي خريطة؟

هذا القرار يحدد كل شيء بعده. ثلاثة مسارات:

### المسار A — Google Maps Platform
| ✅ | ❌ |
|----|----|
| أسهل تكامل، خرائط مألوفة للمستخدم | **شروط الخدمة تمنع التوجيه اللحظي/turn-by-turn في تطبيق طرف ثالث** |
| بيانات حركة جيدة على المحاور الرئيسية | تكلفة تتضاعف بسرعة مع النمو |
| | لا تحكم في الطبقات (نقاط ساخنة، فيضان) |
| | بيانات الحركة على الطرق الفرعية ضعيفة في الجزائر |

**الحكم:** ❌ **مرفوض كأساس للملاحة.** يمكن استخدامه فقط للبحث عن الأماكن (Places) أو لمعاينة ثابتة، لكن الاعتماد عليه يقتل المنتج قانونياً.

> ملاحظة دقيقة: شروط Google Maps Platform تُجيز "real-time driving / turn-by-turn" ضمن شروط أمان محددة، لكنها تُحرّم تضمينها في أنظمة ترفيه السيارة، وتفرض متطلبات دقة موقع ومراقبة جودة GPS. الاعتماد على هذا المسار يعني التعايش مع قيود تعاقدية متغيرة — خطر استراتيجي لمشروع يقوم على الملاحة.

### المسار B — MapLibre + OpenStreetMap + مزوّد حركة منفصل ★ المُوصى به
| المكوّن | الاختيار | الترخيص/التكلفة |
|---------|----------|------------------|
| محرك العرض | **MapLibre GL Native** (Android/iOS) أو **flutter_map** | مجاني، مفتوح |
| بلاطات الخريطة | MapTiler / Stadia / self-hosted (Planetiler) | طبقة مجانية سخية، ثم ~$25–100/شهر |
| بيانات الطرق | **OpenStreetMap** | مجاني (ODbL) |
| حركة حية | **TomTom Traffic API** أو **HERE** أو **Mapbox** | TomTom: ~2500 طلب/يوم مجاني، ثم تسعير |
| توجيه (Routing) | **Valhalla** أو **OSRM** (self-hosted) | مجاني |
| الطقس | **Open-Meteo** | مجاني للاستخدام غير التجاري/التجاري المحدود |
| ترميز جغرافي | **Nominatim** (self-host) أو **Photon** | مجاني |

**الحكم:** ✅ **هذا هو المسار.** يعطي تحكماً كاملاً، لا قيود تعاقدية على الملاحة، وتكلفة قابلة للتحكم.

### المسار C — TomTom Orbis (كل شيء من مزوّد واحد)
| ✅ | ❌ |
|----|----|
| خرائط + حركة + توجيه من مصدر واحد | تكلفة أعلى عند الحجم |
| توافق MapLibre | اعتماد على مزوّد واحد |
| بيانات حركة قوية | |

**الحكم:** ⚠️ خيار جيد للنسخة 2 إذا أثبت المنتج نفسه وأصبحت التكلفة الهندسية أهم من التكلفة المالية.

### القرار النهائي
```
MVP:     MapLibre + OSM (self-hosted tiles أو MapTiler) + Valhalla + TomTom Traffic + Open-Meteo
V2:      تقييم الترحيل إلى TomTom Orbis إذا تجاوز الحجم 100k مستخدم
```

---

## 2. مصادر البيانات — جدول كامل

| # | البيانات | المصدر | التكرار | التكلفة | الأهمية |
|---|----------|--------|---------|---------|---------|
| D1 | شبكة الطرق (هندسة، حارات، سرعة، نوع) | OSM / Geofabrik | شهرياً | مجاني | ★★★★★ |
| D2 | حركة حية (flow) | TomTom Traffic | 1–5 دقائق | ~2500/يوم مجاني | ★★★★★ |
| D3 | حركة تاريخية (نمط) | TomTom (إن متاح) + بناء ذاتي | مرة واحدة + تحديث | متغير | ★★★★★ |
| D4 | الحوادث والإغلاقات | TomTom Incidents + بلاغات المستخدمين | 1–5 دقائق | مشمول | ★★★★ |
| D5 | **GPS مجهول من مستخدمي التطبيق** | التطبيق نفسه | 15–30 ثانية | مجاني (أصل ذاتي) | ★★★★★ |
| D6 | تقارير المستخدمين | التطبيق | فوري | مجاني | ★★★★ |
| D7 | الطقس الحالي + توقعات 60 دقيقة | Open-Meteo | 15 دقيقة | مجاني | ★★★★ |
| D8 | تاريخ الفيضانات | يدوي (أرشيف صحفي + حماية مدنية) | مرة واحدة | مجاني | ★★★ |
| D9 | الأشغال | بلاغات + بيانات مفتوحة + الولاية | يومياً | مجاني | ★★★★ |
| D10 | النقل العمومي (خطوط، محطات) | OSM + ETUSA/SETRAM | شهرياً | مجاني | ★★★ |
| D11 | أوقات الحافلات الحية | ETUSA (لا يوجد API عام) | — | غير متاح | ★★ (مستقبلاً) |
| D12 | أحداث (مباريات، مناسبات) | يدوي/مجتمع | أسبوعياً | مجاني | ★★ |
| D13 | التقويم (رمضان، عطل، دخول مدرسي) | ثابت | سنوياً | مجاني | ★★★★ |
| D14 | **بيانات من Waze for Cities** | Waze | فوري | **مجاني للجهات الحكومية/مشغلي الطرق** | ★★★ (يتطلب شريكاً مؤسسياً) |

### 2.1 عن D14 — Waze for Cities
برنامج مجاني يتبادل البيانات مع الجهات الحكومية ومشغلي الطرق (1500+ شريك). يعطي تدفقاً حياً للتنبيهات والحوادث. **لكنه لا يُمنح لشركة خاصة بسهولة** — يتطلب أن يكون المتقدم جهة حكومية أو مشغّل طريق.

**الاستراتيجية:** إما (أ) شراكة مع الولاية/ETUSA تجعلنا "شريكاً تقنياً"، أو (ب) بناء البيانات الذاتية. لا نبني الخطة على هذا المصدر.

### 2.2 عن D5 — البيانات الذاتية (الأهم على المدى الطويل)
هذا هو **الخندق**. لا يمكن شراؤه، ولا يمكن لمنافس تقليده بسهولة.

```
كيف يعمل:
1. التطبيق يرسل نقطة مجهولة كل 20 ثانية أثناء الملاحة النشطة
   {lat, lng, speed, heading, accuracy, ts}  — بدون معرّف مستخدم دائم
2. الخادم يطابق النقطة مع edge في الرسم البياني
3. يحسب سرعة المرور الفعلية على المقطع
4. يدمج مع D2 (TomTom) بوزن يتناسب مع عدد الـprobes
5. يحتفظ بالبيانات المجمّعة فقط (لا مسارات فردية)

الحد الأدنى للفائدة:
- محور واحد: ≥ 30 سيارة/ساعة في الذروة
- 10 محاور: ≥ 300 مستخدم نشط متزامن
```

**الخصوصية:** لا معرّف دائم، تجميع على مستوى المقطع، حذف بعد 90 يوماً، إفصاح صريح، خيار إيقاف.

---

## 3. المعمارية العامة

```
┌──────────────────────────────────────────────────────────────┐
│  التطبيق (Flutter)                                           │
│  ├─ الخريطة (MapLibre)                                       │
│  ├─ محرك الحالة المحلي (SQLite/Drift)                        │
│  ├─ إشعارات (FCM / APNs)                                     │
│  ├─ إرسال probes (مُجمّع، مُشفّر)                            │
│  └─ كاش أوفلاين (بلاطات + مسارات محفوظة)                     │
└─────────────────────────┬────────────────────────────────────┘
                          │ HTTPS / gRPC-web
┌─────────────────────────▼────────────────────────────────────┐
│  API Gateway (rate limit, auth, quotas)                      │
└─────────────────────────┬────────────────────────────────────┘
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ Routing Svc   │ │ Forecast Svc  │ │ Alert Svc     │
│ (Valhalla)    │ │ (Python)      │ │ (scheduler)   │
│ + uncertainty │ │ + patterns    │ │ + FCM         │
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          ▼
        ┌─────────────────────────────────────┐
        │  Graph & Traffic Store              │
        │  ├─ PostgreSQL + PostGIS (edges,    │
        │  │   hotspots, users, subs)         │
        │  ├─ Redis (حالة لحظية، كاش)         │
        │  └─ ClickHouse (سلاسل زمنية، نماذج) │
        └─────────────────────────────────────┘
                          ▲
        ┌─────────────────┴─────────────────┐
        │  Ingest Workers                   │
        │  ├─ TomTom poller (5 دقائق)        │
        │  ├─ Open-Meteo poller (15 دقيقة)   │
        │  ├─ OSM graph rebuilder (شهرياً)   │
        │  └─ probe aggregator (مستمر)       │
        └───────────────────────────────────┘
                          ▲
        ┌─────────────────┴─────────────────┐
        │  Batch / ML                       │
        │  ├─ Pattern builder (ليلي)         │
        │  ├─ Model trainer (أسبوعي)         │
        │  └─ Hotspot detector (أسبوعي)      │
        └───────────────────────────────────┘
```

### 3.1 اختيار التقنيات

| الطبقة | الاختيار | السبب |
|--------|----------|-------|
| التطبيق | **Flutter** | كود واحد لـ Android+iOS، دعم RTL ممتاز، `flutter_map`/`maplibre_gl` ناضجان |
| الخريطة | `maplibre_gl` أو `flutter_map` + `vector_map_tiles` | MapLibre = لا قيود تعاقدية |
| قاعدة محلية | Drift (SQLite) | أوفلاين، استعلامات |
| الخادم | **Python (FastAPI)** + **Go** (خدمة التوجيه) | Python للنماذج، Go للأداء |
| قاعدة رئيسية | PostgreSQL + PostGIS | جغرافياً قوي |
| سلاسل زمنية | ClickHouse | استعلامات أنماط سريعة |
| كاش/لحظي | Redis | حالة كل edge |
| التوجيه | **Valhalla** (Docker) | يدعم costing مخصص، matrices، isochrones |
| النماذج | LightGBM + scikit-learn | بسيط، سريع، قابل للتفسير |
| الاستضافة | **VPS في الجزائر أو أوروبا** (Hetzner/OVH) | التكلفة + زمن الوصول |
| الإشعارات | FCM (Android) + APNs (iOS) | مجاني |
| التحليلات | PostHog (self-host) أو Umami | خصوصية |

> **ملاحظة عن الاستضافة:** الاستضافة داخل الجزائر محدودة. الخيارات: (أ) VPS أوروبي (فرنسا/ألمانيا) — زمن وصول ~40–60ms، مقبول؛ (ب) مزوّد محلي (Algérie Télécom, ICOSNET) — أفضل للامتثال، أسوأ للأداء والمرونة. **التوصية:** أوروبا للـMVP، مع خطة ترحيل/نسخة محلية عند نمو المستخدمين، لأن قانون 18-07 يقيّد النقل خارج الحدود.

---

## 4. نموذج البيانات الأساسي

```sql
-- الرسم البياني
CREATE TABLE edges (
  id            BIGSERIAL PRIMARY KEY,
  osm_way_id    BIGINT,
  geom          GEOGRAPHY(LINESTRING, 4326),
  length_m      INT,
  road_class    TEXT,        -- motorway, trunk, primary, secondary, residential
  lanes         INT,
  free_flow_kph NUMERIC(5,1),
  oneway        BOOL,
  slope_pct     NUMERIC(4,1),
  has_signal    BOOL,
  hotspot_id    BIGINT REFERENCES hotspots(id),
  corridor_id   INT REFERENCES corridors(id)
);

-- النمط التاريخي (الطبقة 2)
CREATE TABLE edge_pattern (
  edge_id     BIGINT,
  day_type    SMALLINT,   -- 0=عادي 1=جمعة 2=سبت 3=رمضان 4=عيد 5=صيف 6=عطلة مدرسية
  bucket      SMALLINT,   -- 0..287  (5 دقائق)
  median_kph  NUMERIC(5,1),
  p10_kph     NUMERIC(5,1),
  p90_kph     NUMERIC(5,1),
  samples     INT,
  updated_at  TIMESTAMPTZ,
  PRIMARY KEY (edge_id, day_type, bucket)
);

-- الحالة اللحظية (Redis، لكن نسخة دائمة للتاريخ)
CREATE TABLE edge_observation (
  edge_id    BIGINT,
  ts         TIMESTAMPTZ,
  speed_kph  NUMERIC(5,1),
  source     SMALLINT,   -- 1=TomTom 2=probe 3=user_report 4=model
  confidence NUMERIC(3,2)
);
-- تُقسَّم زمنياً (TimescaleDB أو ClickHouse)

-- النقاط الساخنة
CREATE TABLE hotspots (
  id           BIGSERIAL PRIMARY KEY,
  name_ar      TEXT NOT NULL,
  name_fr      TEXT,
  geom         GEOGRAPHY(POINT, 4326),
  radius_m     INT DEFAULT 200,
  kind         TEXT,        -- intersection, bridge, tunnel, slope, market, school
  severity     SMALLINT,    -- 1..5
  cause        TEXT,
  flood_risk   SMALLINT,    -- 0..3
  verified_at  DATE,
  source       TEXT
);

CREATE TABLE hotspot_windows (
  hotspot_id BIGINT REFERENCES hotspots(id),
  day_type   SMALLINT,
  start_min  SMALLINT,   -- دقائق من منتصف الليل
  end_min    SMALLINT,
  severity   SMALLINT,
  PRIMARY KEY (hotspot_id, day_type, start_min)
);

-- المستخدم والاشتراك
CREATE TABLE users (
  id            UUID PRIMARY KEY,
  created_at    TIMESTAMPTZ,
  locale        TEXT DEFAULT 'ar',
  home_geom     GEOGRAPHY(POINT,4326),
  work_geom     GEOGRAPHY(POINT,4326),
  consent_at    TIMESTAMPTZ,     -- موافقة معالجة الموقع
  deletion_at   TIMESTAMPTZ      -- حق الحذف
);

CREATE TABLE subscriptions (
  user_id     UUID REFERENCES users(id),
  plan        TEXT,        -- free, monthly, yearly, pro
  platform    TEXT,        -- play, appstore, chargily
  receipt     TEXT,
  status      TEXT,        -- active, expired, refunded
  started_at  TIMESTAMPTZ,
  expires_at  TIMESTAMPTZ,
  verified_at TIMESTAMPTZ
);

-- المسارات المتكررة
CREATE TABLE commutes (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID REFERENCES users(id),
  label       TEXT,
  origin      GEOGRAPHY(POINT,4326),
  dest        GEOGRAPHY(POINT,4326),
  typical_depart_min SMALLINT,
  typical_duration_s INT,
  learn_count INT DEFAULT 0,
  active      BOOL DEFAULT true
);
```

---

## 5. خدمات الخادم — العقود

### 5.1 `POST /v1/route`
```json
// طلب
{
  "origin": {"lat": 36.7538, "lng": 3.0588},
  "dest":   {"lat": 36.7166, "lng": 3.2100},
  "depart_at": "2026-11-26T07:10:00+01:00",   // أو "now"
  "arrive_by": null,
  "alternatives": 2,
  "profile": "car",
  "avoid": ["toll"],
  "locale": "ar"
}

// استجابة
{
  "routes": [
    {
      "id": "r1",
      "label": "fastest",
      "duration_s": 2880,
      "duration_range_s": [2520, 3480],
      "distance_m": 18400,
      "confidence": 0.78,
      "p_arrive_by": 0.82,
      "hazards": [
        {"hotspot_id": 12, "name_ar": "تقاطع الحراش", "delay_s": 420}
      ],
      "polyline": "…",
      "steps": [ … ],
      "why": "أسرع بـ 5 دقائق، لكن تقلب أعلى (‎±8د) بسبب نقطة الحراش"
    },
    { "id": "r2", "label": "most_stable", … },
    { "id": "r3", "label": "fallback", … }
  ],
  "data_freshness_s": 42,
  "model_version": "2026.11.3"
}
```

### 5.2 `GET /v1/departure-plan`
```json
// طلب: ?origin=…&dest=…&arrive_by=08:30&step_min=5
// استجابة
{
  "arrive_by": "08:30",
  "samples": [
    {"depart": "06:30", "duration_s": 2700, "p_on_time": 0.97, "level": "good"},
    {"depart": "06:45", "duration_s": 2880, "p_on_time": 0.94, "level": "good"},
    {"depart": "07:00", "duration_s": 3360, "p_on_time": 0.71, "level": "warn"},
    {"depart": "07:15", "duration_s": 4320, "p_on_time": 0.28, "level": "bad"}
  ],
  "optimal_window": ["06:40", "06:55"],
  "tipping_point": "07:05",
  "advice_ar": "اخرج قبل 07:00. بعد 07:05 احتمال التأخر 72%.",
  "alternative_if_late": {
    "depart": "07:15",
    "route_id": "r2",
    "arrive_estimate": "08:24",
    "spread_s": 540
  }
}
```

### 5.3 `POST /v1/probes` (دفعة)
```json
{
  "session": "anon-uuid",
  "points": [
    {"lat":36.75,"lng":3.06,"kph":18,"hdg":92,"acc":12,"ts":1732600000}
  ]
}
// استجابة: 204
// ملاحظة: تُرسل مجمّعة كل 60 ثانية، تُحذف المعرّفات بعد التجميع
```

### 5.4 `POST /v1/reports`
```json
{
  "kind": "accident|jam|police|closure|flood|works",
  "geom": {"lat":36.74,"lng":3.09},
  "edge_id": 88213,
  "severity": 3,
  "note": "حادث عند الجسر"
}
// يُقيَّم بسمعة المستخدم، ويُدمج بعد 2–3 تقارير متوافقة
```

### 5.5 `GET /v1/hotspots?bbox=…`
يعيد النقاط الساخنة داخل الحدود مع نوافذها الزمنية.

### 5.6 `POST /v1/alerts/subscribe`
يسجّل جهاز المستخدم + المسار + نافذة الإشعار.

---

## 6. خط أنابيب البيانات (Pipelines)

### 6.1 بناء الرسم البياني (شهرياً)
```
Geofabrik Algeria PBF
  → osmium extract (bbox العاصمة + محاور الولايات)
  → Valhalla tile build (graph)
  → استخراج edges إلى PostGIS (طول، فئة، حارات، سرعة)
  → حساب المنحدر من DEM (SRTM 30m)
  → ربط بـ hotspots عبر مسافة < 250م
  → نشر النسخة الجديدة (blue/green)
```

### 6.2 سحب الحركة (كل 5 دقائق)
```
TomTom Traffic Flow (bbox tiles)
  → فك الترميز (OpenLR)
  → مطابقة مع edges
  → كتابة edge_observation
  → تحديث Redis (الحالة اللحظية)
  → إذا edge جديد بلا مطابقة ⇒ تسجيله لمطابقة يدوية
```

### 6.3 تجميع الـprobes (مستمر)
```
دفعة probes
  → تحقق من الجودة (acc < 50m، kph > 0)
  → مطابقة map-matching مع edge
  → تجميع لكل (edge, دقيقة): median, count
  → دمج مع TomTom بوزن = f(count)
  → كتابة observation
```

### 6.4 بناء الأنماط (ليلياً، 02:00)
```
SELECT edge_id, day_type, bucket,
       median(kph), percentile_cont(0.1), percentile_cont(0.9), count(*)
FROM edge_observation
WHERE ts > now() - interval '90 days'
GROUP BY 1,2,3
HAVING count(*) >= 3
→ تمليس (moving average على 3 خانات)
→ تعبئة الفراغات من (corridor, day_type, bucket)
→ upsert edge_pattern
```

### 6.5 تدريب النموذج (أسبوعياً)
```
لكل edge:
  features(t)  = [kph(t), kph(t-15), kph(t-30), kph(t-60),
                  pattern_median, pattern_p10, pattern_p90,
                  upstream_kph, downstream_kph,
                  weather, day_type, is_holiday, hour_sin/cos]
  target       = kph(t + 15 | 30 | 60 | 120)

LightGBM (MAE objective)، 4 نماذج (أفق واحد لكل نموذج)
تقييم: split زمني (لا عشوائي!) — آخر أسبوعين كاختبار
نشر: إذا MAE_new < MAE_old × 1.02
```

### 6.6 كشف النقاط الساخنة تلقائياً (أسبوعياً)
```
لكل edge:
  ratio = median_kph(peak) / free_flow_kph
  إذا ratio < 0.45 في ≥ 3 أيام من 5 ⇒ مرشّح نقطة ساخنة
  تجميع المرشّحين المتجاورين ⇒ نقطة ساخنة مقترحة
  إشعار لفريق البيانات للمراجعة (لا نشر تلقائي في البداية)
```

---

## 7. خادم التوجيه — كيف نتعامل مع عدم اليقين

Valhalla يعطي مسارات لكن ليس توزيعات. نضيف طبقة:

```python
def route_with_uncertainty(origin, dest, depart_at, n_routes=3):
    # 1. زمن كل edge = median من النموذج (نمط + تصحيح لحظي)
    # 2. تباين كل edge = (p90 - p10) / 2.56  (تقريب σ)
    # 3. Valhalla يعطي المسارات المرشحة (fastest + alternatives)
    # 4. لكل مسار: محاكاة مونت كارلو (200 عيّنة)
    #    زمن المسار = Σ sample(edge_i) حيث sample من توزيع لوغ-طبيعي
    # 5. النتائج: median, p10, p90, P(arrive_by T)
    # 6. اختيار:
    #    fastest    = أقل median
    #    stable     = أقل (p90 - p10) مع median ضمن +15% من الأسرع
    #    fallback   = أقل تداخل مع fastest (Jaccard < 0.4)
    return routes
```

**لماذا مونت كارلو وليس جمع التباينات؟** لأن التباينات مترابطة على طول المسار (إذا ازدحم مقطع، ازدحم ما بعده). المحاكاة تلتقط الترابط.

---

## 8. التطبيق — هيكل Flutter

```
lib/
├── main.dart
├── core/
│   ├── config.dart            # endpoints, flags
│   ├── result.dart            # Result<T> type
│   └── errors.dart
├── data/
│   ├── api/                   # clients (route, plan, probes, reports)
│   ├── local/                 # drift db, tiles cache
│   ├── models/                # freezed models
│   └── repositories/
├── domain/
│   ├── entities/
│   ├── usecases/
│   │   ├── plan_departure.dart
│   │   ├── get_routes.dart
│   │   ├── learn_commute.dart
│   │   └── report_hazard.dart
│   └── services/
│       ├── probe_recorder.dart
│       ├── alert_scheduler.dart
│       └── offline_manager.dart
├── features/
│   ├── map/                   # الشاشة الرئيسية
│   ├── departure/             # "متى أخرج؟"
│   ├── routes/                # المسارات الثلاثة
│   ├── patterns/              # الخريطة الحرارية
│   ├── reports/               # تقارير المستخدم
│   ├── settings/
│   └── paywall/
├── l10n/                      # ar, fr, (en)
└── theme/                     # RTL, dark, high-contrast
```

### 8.1 مكتبات أساسية
| الغرض | المكتبة |
|-------|---------|
| الخريطة | `maplibre_gl` أو `flutter_map` + `vector_map_tiles` |
| الحالة | `riverpod` |
| النماذج | `freezed` + `json_serializable` |
| الشبكة | `dio` |
| قاعدة محلية | `drift` |
| الموقع | `geolocator` |
| الإشعارات | `firebase_messaging` + `flutter_local_notifications` |
| الدفع | `in_app_purchase` + `webview_flutter` (Chargily) |
| الخلفية | `workmanager` (تسجيل probes، جدولة) |
| الترجمة | `flutter_localizations` + `intl` |
| التتبع | `sentry_flutter` |

### 8.2 اعتبارات حرجة في التطبيق
- **البطارية:** تسجيل الموقع فقط أثناء الملاحة النشطة أو عند الاقتراب من نافذة الخروج. لا تتبع دائم.
- **البيانات:** خريطة متجهية (أصغر بكثير من الراستر)، كاش بلاطات، ضغط الاستجابات.
- **الأوفلاين:** آخر مسار محفوظ يعمل بلا شبكة (مع تحذير "بيانات قديمة").
- **بدء سريع:** زمن الإقلاع < 2 ثانية، الخريطة تظهر < 1.5 ثانية.
- **RTL:** كل التخطيطات تُختبر بالعربية أولاً.
- **إمكانية الوصول:** تباين AA، أحجام لمس ≥ 48dp، دعم قارئ الشاشة.

---

## 9. التكاليف — تقدير شهري

### 9.1 مرحلة MVP (≤ 1000 مستخدم)
| البند | التكلفة |
|-------|---------|
| VPS (4 vCPU, 8GB) × 2 | ~$40 |
| PostgreSQL مُدار (أو على نفس VPS) | ~$15 |
| Redis | ~$10 |
| MapTiler (بلاطات) | $0 (طبقة مجانية) |
| TomTom Traffic | $0 (2500/يوم) |
| Open-Meteo | $0 |
| FCM/APNs | $0 |
| Sentry | $0 (خطة مجانية) |
| نطاق + شهادة | ~$2 |
| **المجموع** | **~$70/شهر** |

### 9.2 مرحلة النمو (10,000 مستخدم نشط)
| البند | التكلفة |
|-------|---------|
| VPS أكبر (16 vCPU, 32GB) × 2 | ~$180 |
| PostgreSQL + PostGIS مُدار | ~$80 |
| ClickHouse | ~$60 |
| Redis | ~$30 |
| MapTiler (500k tile requests) | ~$100 |
| TomTom Traffic (تجاوز المجاني: ~50k/شهر) | ~$150 |
| Sentry + PostHog | ~$50 |
| **المجموع** | **~$650/شهر** |

### 9.3 عند 100,000 مستخدم
| البند | التكلفة |
|-------|---------|
| حوسبة (k8s أو VMs) | ~$1,200 |
| قواعد بيانات | ~$600 |
| بلاطات | ~$800 |
| حركة | ~$1,500 |
| CDN/نقل | ~$300 |
| مراقبة | ~$200 |
| **المجموع** | **~$4,600/شهر** |

**حساب الوحدة:** عند 100k مستخدم و 3% تحويل × 600 دج/شهر ≈ 1.8 مليون دج ≈ $13,000/شهر. التكلفة 35%. مقبول لكن يجب تحسينه (بلاطات ذاتية الاستضافة، تخزين مؤقت أذكى).

---

## 10. الامتثال القانوني — الجزائر

### 10.1 القانون 18-07 (حماية المعطيات الشخصية) + تعديل 25-11
هذا ليس تفصيلاً — هو **شرط وجود**.

| المتطلب | التطبيق |
|---------|---------|
| تصريح مسبق للسلطة الوطنية (ANPDP) | **إلزامي** قبل جمع أي بيانات شخصية |
| تعيين مسؤول حماية بيانات (DPO) | مطلوب عند المعالجة الواسعة |
| سجل المعالجات | وثيقة داخلية إلزامية |
| موافقة صريحة | شاشة موافقة قبل تفعيل الموقع |
| إشعار بالمعلومات | سياسة خصوصية بالعربية والفرنسية |
| حق الوصول/التصحيح/الحذف | شاشات في التطبيق + مهلة استجابة |
| نقل البيانات خارج الحدود | **يتطلب ترخيصاً من ANPDP** — وهذا يؤثر على اختيار الاستضافة |
| أمن المعالجة | تشفير، سجلات، اختبار اختراق |
| الإخطار بالخروقات | إجراء موثّق |

**العقوبات:** غرامات مالية وحتى حبس في الحالات الجسيمة.

**النتيجة العملية:** إذا استضفنا في أوروبا، نحتاج **ترخيص نقل**. البديل: استضافة محلية. **القرار:** ابدأ بالتصريح + سياسة خصوصية قوية + تجميع مجهول (تقليل المخاطر)، وابدأ إجراء ترخيص النقل بالتوازي.

### 10.2 قواعد المتاجر
| المتطلب | ملاحظة |
|---------|--------|
| سياسة خصوصية عامة | إلزامية على Play و App Store |
| Data Safety (Play) | يجب الإفصاح عن جمع الموقع |
| App Privacy (Apple) | نفس الشيء |
| إذن الموقع في الخلفية | يحتاج تبريراً واضحاً — قد يُرفض؛ تجنّبه في MVP |
| الإفصاح عن الإعلانات | مطلوب |

### 10.3 قيود Google Maps
حتى لو استخدمنا Places فقط، يجب مراجعة الشروط. **الأفضل:** تجنّب Google كلياً في الملاحة.

### 10.4 الترخيص
- OSM: ODbL — يجب نسب البيانات وإتاحة الأعمال المشتقة.
- MapLibre: BSD.
- Valhalla: MIT.
- Open-Meteo: CC-BY (يتطلب نسب).
- TomTom: تجاري — لا يجوز إعادة توزيع البيانات الخام.

---

## 11. الأداء والموثوقية

| المتطلب | الهدف | كيف |
|---------|-------|-----|
| زمن استجابة المسار | p95 < 900ms | كاش + Valhalla مُسخّن |
| زمن استجابة خطة الانطلاق | p95 < 600ms | حساب مسبق للنوافذ الشائعة |
| تحديث الحالة | ≤ 5 دقائق | poller + probes |
| توفر | 99.5% | نسختان + health checks |
| فشل المصدر الخارجي | يعمل | fallback إلى النمط التاريخي |
| حجم التطبيق | < 40MB | بلاطات عند الطلب |

---

## 12. الأمان

- TLS إلزامي، HSTS.
- مصادقة: JWT قصير العمر + refresh.
- التحقق من إيصالات الشراء على الخادم (Play/Apple/Chargily).
- Rate limiting لكل مستخدم ولـIP.
- لا مفاتيح API في التطبيق (كل شيء عبر الخادم).
- سجلات بلا معرّفات شخصية.
- اختبار اختراق قبل الإطلاق.
- نسخ احتياطي يومي + اختبار استرجاع شهري.

---

## 13. خطة البناء التقنية (تفصيلية)

| الأسبوع | العمل |
|---------|-------|
| 1 | إعداد المستودع، CI، هيكل Flutter، إعداد MapLibre + خريطة تعمل |
| 2 | بناء الرسم البياني من OSM، Valhalla يعمل، مسار بسيط من A إلى B |
| 3 | ربط TomTom Traffic، حالة لحظية على الخريطة، تخزين |
| 4 | **إدخال 50 نقطة ساخنة يدوياً** + طبقة عرضها |
| 5 | بناء edge_pattern من بيانات TomTom التاريخية + backfill |
| 6 | خدمة `departure-plan` + شاشة "متى أخرج؟" |
| 7 | المسارات الثلاثة + الثقة + مونت كارلو |
| 8 | probes + تقارير المستخدمين + لوحة إشراف بسيطة |
| 9 | الإشعارات + جدولة + FCM |
| 10 | الاشتراك + Paywall + Chargily |
| 11 | الطقس + الفيضان + تلميع RTL + الأداء |
| 12 | اختبار مغلق (50 مستخدم) + قياس MAE + إصلاح |

**نقطة حرجة:** الأسبوع 5 (النمط التاريخي) هو أكبر خطر. البديل: بناء النمط من بيانات TomTom التاريخية إن كانت متاحة في الطبقة المجانية، وإلا من الـprobes المبكرة (وهذا يعني تأخير الإطلاق أو إطلاق "نسخة عرض" بلا تنبؤ).

**تخفيف:** أطلق نسخة "عرض فقط + نقاط ساخنة" في الأسبوع 8، واجمع probes، وأضف التنبؤ في الأسبوع 12 بعد توفر بيانات كافية.
