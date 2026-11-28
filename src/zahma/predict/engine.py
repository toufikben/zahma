"""محرك التنبؤ — قلب المنتج.

السؤال الذي يجيب عنه: «إن خرجت في الساعة T، كم ستستغرق الرحلة؟»

**وطبيعة الجواب — تُقال بلا تجميل: كل رقم هنا قبلي (forecast).**

قياسنا على 768,477 صفاً: **صفر** منها طابعه الزمني في الماضي. المصدر
(Mapbox) لا يعطينا حالة آنية للجزائر — نطلب منه جدولاً لساعة مستقبلية
فيعيده. وأثبتنا ذلك مباشرة: نداء «بلا `depart_at`»، ونداء «`depart_at`
= الآن بالضبط»، ونداء «الآن ±3 دقائق» أعطت **نفس بصمة السرعات حرفياً**.
لو كانت هناك حالة حية لتغيّرت.

فالمنتج **نمط أسبوعي نموذجي**، لا «حالة الطريق الآن». وهو مفيد: قرار
«متى أخرج» يحتاج نمطاً لا لحظة. لكن تسميته «آنية» كذب.

ومسار العيّنة الحية أدناه (`LIVE_MAX_AGE_MIN`) مبني ومُختبَر، لكنه **لا
يُنشَّط** على بياناتنا الحالية لأن شرطه `ts_utc <= now` لا يطابق صفاً
واحداً. سيعمل حين يصلنا مصدر يعطي قياساً فعلياً (سائق، مستخدم، أو مزوّد
يغطي الجزائر).

المدخلات:
- ملف تعريف المقطع (سرعة p50 لكل شريحة زمنية، نوع اليوم)
- عيّنة حية حديثة (إن وُجدت — لا توجد اليوم)
- عامل الطقس
- عامل الأعطال

المخرجات:
- المدة المتوقعة (p50) والفاصل (p90)
- نسبة ثقة مبنية على أدلة قابلة للتفسير، لا رقم عشوائي

المبدأ الحاكم:
- لا تنبؤ بثقة منخفضة. «لا أعرف» أفضل من رقم خاطئ.
- كل رقم معروض يحمل: مصدره، عمره، وثقته.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from zahma.db import session_scope
from zahma.predict.router import SNAP_MAX_KM

TZ = ZoneInfo("Africa/Algiers")


# ============================================================
# أدوات التقويم
# ============================================================

def local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(TZ)


def bucket_15m(dt: datetime) -> int:
    """شريحة 15 دقيقة داخل اليوم المحلي: 0..95.

    **مهم:** المدخل قد يكون UTC. الشرائح تُبنى من التوقيت المحلي
    (Africa/Algiers = UTC+1)، فاستخدام `.hour` مباشرة على UTC يزحف
    كل شيء ساعة كاملة — أي 4 شرائح. القياس: 07:30 محلي كان يُقرأ
    كـ06:30، فالذروة الصباحية تقرأ بيانات ما قبل الذروة.
    لذلك نُحوّل دائماً إلى المحلي هنا، مهما كان نوع المدخل.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return local_now(dt).hour * 4 + local_now(dt).minute // 15


def day_type_of(now: datetime | None = None) -> str:
    local = local_now(now)
    try:
        with session_scope() as s:
            row = s.execute(
                text("SELECT day_type FROM calendar_days WHERE day_local = :d"),
                {"d": local.date()},
            ).scalar()
        if row:
            return row
    except Exception:  # noqa: BLE001
        pass
    wd = local.weekday()
    return "FRIDAY" if wd == 4 else "SATURDAY" if wd == 5 else "WORKDAY"


def _unroutable_reason(path) -> str:
    """رسالة صادقة تفرّق بين سببين مختلفين تماماً.

    **«خارج التغطية» ليست «الشبكة مقطوعة».** الأول يعني أن النقطة أبعد من
    أن نسحبها (بومرداس 11.3 كم)، والثاني يعني أن النقطتين داخل الشبكة
    لكن لا طريق يربطهما. الخلط بينهما يرسل المستخدم يبحث عن عطل لا وجود له.

    ولا نطبع 999 كمسافة — رقم مخترع. نقول «أبعد من مدى البحث» كما هو.
    """
    def _side(km: float) -> str:
        if km >= 999.0:
            return "أبعد من مدى البحث (لا عقدة قريبة)"
        return f"{km:.1f} كم"

    if path.snap_from_km > SNAP_MAX_KM or path.snap_to_km > SNAP_MAX_KM:
        return (
            f"خارج التغطية: نقطة الانطلاق {_side(path.snap_from_km)} "
            f"عن شبكتنا، والوجهة {_side(path.snap_to_km)} "
            f"(الحد المقبول {SNAP_MAX_KM:.0f} كم)"
        )
    return "داخل التغطية لكن لا مسار متصل بين النقطتين"


def nearest_network_km(lat: float, lon: float) -> float:
    """كم تبعد النقطة عن أقرب مقطع في شبكتنا؟ — تشخيص الصدق.

    **لماذا دالة بدل رسالة عامة:** حين يقول التطبيق «تعذّر إيجاد مسار»،
    السؤال الأول للمستخدم: هل الشبكة مقطوعة، أم أنا خارج التغطية؟
    الرقم يجيب. وبدونه تصير كل نقطة خارج الولاية «خطأ» مبهمة.

    **ملاحظة أداء مقاسة:** `geom::geography` يُلغي فهرس GIST (تحويل كل
    صف)، فاستعلام بسيط يصير مسحاً كاملاً على 294 ألف مقطع. لذلك نستخدم
    `ST_Expand` بمربّع درجات ثم `<->` — أي نُقلّص المرشّحين بالفهرس أولاً.
    """
    # 0.15° ≈ 16 كم — يكفي ليجد أي مقطع قريب دون مسح الشبكة كلها.
    with session_scope() as s:
        v = s.execute(
            text(
                """
                WITH box AS (
                    SELECT ST_Expand(
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 0.15
                    ) AS g
                )
                SELECT min(ST_Distance(
                           geom::geography,
                           ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                       )) / 1000.0
                FROM segments, box
                WHERE geom && box.g
                """
            ),
            {"lat": lat, "lon": lon},
        ).scalar()
    if v is None:
        return 999.0
    return float(v)


def calendar_flags(now: datetime | None = None) -> dict[str, bool]:
    local = local_now(now)
    with session_scope() as s:
        row = s.execute(
            text(
                "SELECT is_ramadan, is_school, is_summer FROM calendar_days "
                "WHERE day_local = :d"
            ),
            {"d": local.date()},
        ).mappings().first()
    if row:
        return dict(row)
    month = local.month
    return {
        "is_ramadan": False,
        "is_school": month not in (7, 8),
        "is_summer": month in (7, 8),
    }


# ============================================================
# بنية النتيجة
# ============================================================

@dataclass(slots=True)
class SegmentEstimate:
    segment_id: int
    length_m: float
    speed_kmh: float
    duration_s: float
    basis: str          # live | profile | freeflow | estimated
    age_min: float | None = None
    confidence: float = 0.5


@dataclass(slots=True)
class RouteEstimate:
    duration_s: float
    duration_p90_s: float
    confidence: float
    basis_counts: dict[str, int] = field(default_factory=dict)
    segments: list[SegmentEstimate] = field(default_factory=list)
    weather_factor: float = 1.0
    incident_penalty: float = 1.0
    warnings: list[str] = field(default_factory=list)
    # **حقل صريح لا يُستنتج من الصفر.** كان `duration_s=0.0` يُعرض كـ
    # «0.0 دقيقة» — أي أن نقطة خارج الشبكة تبدو رحلة لحظية. والفرق جوهري:
    # «لا أعرف» ليست «صفر». أي واجهة تعرض `minutes` وحدها ستكذب على
    # المستخدم، فالحقل يجعل الخطأ مستحيلاً بالبناء.
    routable: bool = True

    @property
    def minutes(self) -> float:
        return round(self.duration_s / 60, 1)

    @property
    def minutes_p90(self) -> float:
        return round(self.duration_p90_s / 60, 1)

    @property
    def uncertainty_min(self) -> float:
        return round((self.duration_p90_s - self.duration_s) / 60, 1)


# ============================================================
# 1. تقدير مقطع واحد
# ============================================================

LIVE_MAX_AGE_MIN = 10.0     # بعدها نعتبر العينة القديمة
LIVE_WEIGHT = 0.7           # وزن العينة الحية مقابل ملف التعريف

# **أقصى مسافة استيفاء بين شريحة معروفة والشريحة المطلوبة — عيب مقاس.**
#
# كان الاستيفاء في `fetch_profile_speeds_bulk` و`fetch_class_speeds_bulk`
# يبحث عن أقرب شريحة **قبل** وأقرب **بعد** بلا أي حدّ زمني. فمقطع مقيس
# عند 06:30 فقط يحمل سرعته إلى 22:30 — أي أن قياس ساعة واحدة يُعمَّم على
# اليوم كله بصمت.
#
# **الأثر على المنتج مقاس:** منحنى الانطلاق من باب الزوار إلى وسط الجزائر
# قفز +6.78 دقيقة عند 06:45 ثم هبط −4.34 عند 07:00. والسبب أن الشريحة 26
# (06:30) كاملة التغطية (3,926 مقطعاً) والشرائح الجديدة جزئية (2,057).
# فالمقاطع الساقطة تتراجع إلى وسيط الصنف، فتتغيّر السرعات النسبية،
# **فيختار Dijkstra مساراً آخر**: 261 مقطعاً عند 06:30 مقابل 317 عند 06:45.
#
# أي أن القفزة ليست ازدحاماً — هي **رحلة مختلفة**. وهذا أسوأ من رقم خاطئ:
# منحنى يُقارن فيه مساران مختلفان.
#
# **الحدّ: 8 شرائح = ساعتان.** أبعد من ذلك ليس استيفاءً بل تخميناً، ولا
# يبقى منه إلا ادّعاء دقة. عند تجاوزه نرجع إلى وسيط الصنف — وهو صادق
# (مصدره معلن) بدل استيفاء بعيد يُوهم بدقة غير موجودة.
MAX_INTERP_BUCKETS = 8


def fetch_live_speed(segment_id: int, now: datetime) -> tuple[float | None, float]:
    """أحدث سرعة حية لمقطع + عمرها بالدقائق."""
    with session_scope() as s:
        row = s.execute(
            text(
                """
                SELECT speed_kmh, ts_utc FROM samples
                WHERE segment_id = :i AND speed_kmh IS NOT NULL
                  AND ts_utc <= :now
                ORDER BY ts_utc DESC LIMIT 1
                """
            ),
            {"i": segment_id, "now": now},
        ).mappings().first()
    if not row:
        return None, 9999.0
    age = (now - row["ts_utc"]).total_seconds() / 60
    return float(row["speed_kmh"]), age


def fetch_live_speeds_bulk(now: datetime, max_age_min: float = 10.0) -> dict[int, float]:
    """أحدث سرعة حية لكل مقطع، باستعلام واحد.

    `DISTINCT ON` في Postgres يعطي أحدث صف لكل مقطع دون مسح متكرر.
    هذا يحوّل 156 ألف استعلام إلى استعلام واحد.

    **الحد الأعلى `ts_utc <= :now` ليس احتياطاً — هو إصلاح عيب خطير.**
    جمعنا يعمل بـ`depart_at`، فكل صفوفنا تحمل طوابع زمنية **مستقبلية**
    (30 نوفمبر – 8 ديسمبر بينما الساعة 27 نوفمبر). استعلام بلا حد أعلى
    (`> now - 10min`) التقط 674,137 صفاً «مستقبلاً» وسمّاها قياساً حياً
    بثقة 0.9 — وهي تنبؤات. النتيجة: المحرّك يعلن «أعرف الآن» بينما يقرأ
    جدولاً نموذجياً متنكّراً.

    **ولماذا `forecast` مستبعد صراحةً:** حتى لو وقع طابع زمني في الماضي،
    الصف الذي وسمه الجمع `forecast` ليس قياساً آنياً بل تنبؤاً لذلك الوقت.
    خلطه بالقياس الحي يجعل المنتج يكذب على نفسه.
    """
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT DISTINCT ON (segment_id) segment_id, speed_kmh
                FROM samples
                WHERE ts_utc > :from_t AND ts_utc <= :now
                  AND speed_kmh IS NOT NULL AND speed_kmh > 0
                  AND (raw_ref IS NULL OR raw_ref NOT LIKE '%forecast%')
                ORDER BY segment_id, ts_utc DESC
                """
            ),
            {"from_t": now - timedelta(minutes=max_age_min), "now": now},
        ).all()
    return {int(r[0]): float(r[1]) for r in rows}


def fetch_class_ratios_bulk(
    b: int, dtype: str, flags: dict[str, bool]
) -> dict[str, float]:
    """نسبة الأداء p50 لكل صنف طريق — البديل الأفضل للسرعة المطلقة.

    **لماذا النسبة أفضل من السرعة المطلقة:** مقطعان من نفس الصنف
    (residential) لكن سرعتيهما الحرة 40 و60 كم/س يتصرفان بشكل مختلف.
    وسيط السرعة المطلقة يعطيهما نفس الرقم ويخسر الفرق. النسبة
    (الفعلية ÷ الحرة) بلا وحدة، فتنطبق على أي مقطع عرفنا سرعته الحرة.

    **القياس** (حجز مكاني، 180,940 قياساً على مقاطع لم تُقس):
      مطلق:   وسيط 18.7%، p90 83.9%، تحيز +6.9%
      نسبة:   وسيط 17.7%، p90 59.2%، تحيز -0.4%
    """
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                WITH exact AS (
                    SELECT road_class, ratio_p50 AS r FROM class_profiles
                    WHERE day_type = :d AND bucket_15m = :b AND is_ramadan = :r
                      AND ratio_p50 IS NOT NULL
                ),
                before AS (
                    SELECT DISTINCT ON (road_class) road_class, ratio_p50 AS r,
                           bucket_15m
                    FROM class_profiles
                    WHERE day_type = :d AND bucket_15m <= :b AND bucket_15m >= :b_lo
                      AND is_ramadan = :r AND ratio_p50 IS NOT NULL
                    ORDER BY road_class, bucket_15m DESC
                ),
                after AS (
                    SELECT DISTINCT ON (road_class) road_class, ratio_p50 AS r,
                           bucket_15m
                    FROM class_profiles
                    WHERE day_type = :d AND bucket_15m >= :b AND bucket_15m <= :b_hi
                      AND is_ramadan = :r AND ratio_p50 IS NOT NULL
                    ORDER BY road_class, bucket_15m ASC
                ),
                interp AS (
                    SELECT
                        COALESCE(bf.road_class, af.road_class) AS road_class,
                        CASE
                            WHEN bf.r IS NULL THEN af.r
                            WHEN af.r IS NULL THEN bf.r
                            WHEN bf.bucket_15m = af.bucket_15m THEN bf.r
                            ELSE bf.r + (af.r - bf.r)
                                 * (:b - bf.bucket_15m)::double precision
                                 / (af.bucket_15m - bf.bucket_15m)
                        END AS v
                    FROM before bf
                    FULL OUTER JOIN after af ON af.road_class = bf.road_class
                ),
                work AS (
                    SELECT road_class, ratio_p50 AS r FROM class_profiles
                    WHERE day_type = 'WORKDAY' AND bucket_15m = :b
                      AND ratio_p50 IS NOT NULL
                )
                SELECT COALESCE(e.road_class, i.road_class, w.road_class) AS rc,
                       COALESCE(e.r, i.v, w.r) AS v
                FROM exact e
                FULL OUTER JOIN interp i ON i.road_class = e.road_class
                FULL OUTER JOIN work w ON w.road_class = COALESCE(e.road_class, i.road_class)
                """
            ),
            {"d": dtype, "b": b, "r": flags["is_ramadan"],
             "b_lo": max(0, b - MAX_INTERP_BUCKETS),
             "b_hi": min(95, b + MAX_INTERP_BUCKETS)},
        ).all()
    return {str(r[0]): float(r[1]) for r in rows if r[0] is not None and r[1] is not None}


def fetch_class_speeds_bulk(
    b: int, dtype: str, flags: dict[str, bool]
) -> dict[str, float]:
    """سرعة p50 لكل صنف طريق في شريحة زمنية — أولوية للمقاطع غير المقيسة.

    هذا ما يجعل منحنى الانطلاق يعرف الزحمة على شوارع المدينة التي لا
    نقيسها مباشرة. بلا هذا، كل مقطع residential/tertiary يرجع إلى
    السرعة الحرة الثابتة، فيصبح المنحنى خطاً مستقيماً.

    **الاستيفاء الخطي بدل «أقرب شريحة»** — وهذا إصلاح عيب حقيقي:

    الشرائح تُبنى من عينات فعلية، والعينات ليست في كل شريحة (جمع كل
    60 دقيقة يعطي الشرائح 3، 7، 11... فقط). «أقرب شريحة» يعني أن
    الشريحة 30 تختار بين 27 و35 — والمسافة متساوية، فيختار Postgres
    أحدهما عشوائياً. النتيجة المقاسة في CI: منحنى يتراوح صعوداً وهبوطاً
    (23.2 ← 11.9 ← 20.5 ← 11.9)، أي أن المستخدم يرى «اخرج في 08:00
    أسرع من 08:30» — تناقض يهدم الثقة في كل رقم آخر.

    الحل: نأخذ أقرب شريحة **قبل** وأقرب شريحة **بعد**، ونستوفي بينهما
    خطياً بوزن المسافة. السرعة تتغيّر بسلاسة في الواقع، والاستيفاء يعكس
    ذلك. عند غياب أحد الطرفين نستخدم المتوفر.
    """
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                WITH exact AS (
                    SELECT road_class, p50_speed FROM class_profiles
                    WHERE day_type = :d AND bucket_15m = :b AND is_ramadan = :r
                ),
                before AS (
                    SELECT DISTINCT ON (road_class) road_class, p50_speed, bucket_15m
                    FROM class_profiles
                    WHERE day_type = :d AND bucket_15m <= :b AND bucket_15m >= :b_lo
                      AND is_ramadan = :r
                    ORDER BY road_class, bucket_15m DESC
                ),
                after AS (
                    SELECT DISTINCT ON (road_class) road_class, p50_speed, bucket_15m
                    FROM class_profiles
                    WHERE day_type = :d AND bucket_15m >= :b AND bucket_15m <= :b_hi
                      AND is_ramadan = :r
                    ORDER BY road_class, bucket_15m ASC
                ),
                interp AS (
                    SELECT
                        COALESCE(bf.road_class, af.road_class) AS road_class,
                        CASE
                            WHEN bf.p50_speed IS NULL THEN af.p50_speed
                            WHEN af.p50_speed IS NULL THEN bf.p50_speed
                            WHEN bf.bucket_15m = af.bucket_15m THEN bf.p50_speed
                            ELSE bf.p50_speed
                                 + (af.p50_speed - bf.p50_speed)
                                   * (:b - bf.bucket_15m)::double precision
                                   / (af.bucket_15m - bf.bucket_15m)
                        END AS v
                    FROM before bf
                    FULL OUTER JOIN after af ON af.road_class = bf.road_class
                ),
                work AS (
                    SELECT road_class, p50_speed FROM class_profiles
                    WHERE day_type = 'WORKDAY' AND bucket_15m = :b
                )
                SELECT COALESCE(e.road_class, i.road_class, w.road_class) AS rc,
                       COALESCE(e.p50_speed, i.v, w.p50_speed) AS v
                FROM exact e
                FULL OUTER JOIN interp i ON i.road_class = e.road_class
                FULL OUTER JOIN work w ON w.road_class = COALESCE(e.road_class, i.road_class)
                """
            ),
            {"d": dtype, "b": b, "r": flags["is_ramadan"],
             "b_lo": max(0, b - MAX_INTERP_BUCKETS),
             "b_hi": min(95, b + MAX_INTERP_BUCKETS)},
        ).all()
    return {str(r[0]): float(r[1]) for r in rows if r[0] is not None and r[1] is not None}


def fetch_profile_speeds_bulk(
    b: int, dtype: str, flags: dict[str, bool]
) -> dict[int, float]:
    """سرعة p50 لكل مقطع في شريحة زمنية — باستعلام واحد، مع تراجع تدريجي.

    التراجع: تطابق تام ← نفس اليوم أي شريحة قريبة ← يوم عمل نفس الشريحة.
    نطبّقه في SQL بـCOALESCE حتى يبقى استعلاماً واحداً.
    """
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                WITH exact AS (
                    SELECT segment_id, p50_speed FROM speed_profiles
                    WHERE day_type = :d AND bucket_15m = :b
                      AND is_ramadan = :r AND is_school = :sc
                ),
                before AS (
                    SELECT DISTINCT ON (segment_id) segment_id, p50_speed, bucket_15m
                    FROM speed_profiles
                    WHERE day_type = :d AND bucket_15m <= :b AND bucket_15m >= :b_lo
                    ORDER BY segment_id, bucket_15m DESC
                ),
                after AS (
                    SELECT DISTINCT ON (segment_id) segment_id, p50_speed, bucket_15m
                    FROM speed_profiles
                    WHERE day_type = :d AND bucket_15m >= :b AND bucket_15m <= :b_hi
                    ORDER BY segment_id, bucket_15m ASC
                ),
                interp AS (
                    -- استيفاء خطي بين أقرب شريحة قبل وأقرب شريحة بعد،
                    -- **محدود بـ`MAX_INTERP_BUCKETS`**. بلا الحدّ كان
                    -- مقطع مقيس عند 06:30 فقط يحمل سرعته إلى 22:30،
                    -- فالمقاطع غير المقيسة في الشرائح الجزئية تتراجع إلى
                    -- وسيط الصنف وتتغيّر السرعات النسبية — **فيختار
                    -- Dijkstra مساراً آخر**. المقاس: 261 مقطعاً عند 06:30
                    -- مقابل 317 عند 06:45 على نفس المسار، وقفزة +6.78 د.
                    -- أي أن المنحنى كان يقارن رحلتين مختلفتين.
                    -- «أقرب شريحة» بلا استيفاء يعطي نتائج متذبذبة عند
                    -- تساوي المسافة (شريحة 30 بين 27 و35)، فيصبح منحنى
                    -- الانطلاق صعوداً وهبوطاً — عيب مقاس في CI.
                    SELECT
                        COALESCE(bf.segment_id, af.segment_id) AS segment_id,
                        CASE
                            WHEN bf.p50_speed IS NULL THEN af.p50_speed
                            WHEN af.p50_speed IS NULL THEN bf.p50_speed
                            WHEN bf.bucket_15m = af.bucket_15m THEN bf.p50_speed
                            ELSE bf.p50_speed
                                 + (af.p50_speed - bf.p50_speed)
                                   * (:b - bf.bucket_15m)::double precision
                                   / (af.bucket_15m - bf.bucket_15m)
                        END AS p50_speed
                    FROM before bf
                    FULL OUTER JOIN after af ON af.segment_id = bf.segment_id
                ),
                work AS (
                    SELECT segment_id, p50_speed FROM speed_profiles
                    WHERE day_type = 'WORKDAY' AND bucket_15m = :b
                )
                SELECT COALESCE(e.segment_id, i.segment_id, w.segment_id) AS sid,
                       COALESCE(e.p50_speed, i.p50_speed, w.p50_speed) AS v
                FROM exact e
                FULL OUTER JOIN interp i ON i.segment_id = e.segment_id
                FULL OUTER JOIN work w ON w.segment_id = COALESCE(e.segment_id, i.segment_id)
                """
            ),
            {
                "d": dtype, "b": b,
                "r": flags["is_ramadan"], "sc": flags["is_school"],
                "b_lo": max(0, b - MAX_INTERP_BUCKETS),
                "b_hi": min(95, b + MAX_INTERP_BUCKETS),
            },
        ).all()
    return {int(r[0]): float(r[1]) for r in rows if r[0] is not None and r[1] is not None}


def fetch_profile_speed(
    segment_id: int, b: int, dtype: str, flags: dict[str, bool]
) -> float | None:
    """سرعة نموذجية من ملف التعريف، مع تراجع تدريجي عند غياب التخصص."""
    with session_scope() as s:
        # المحاولة 1: تطابق تام
        v = s.execute(
            text(
                """
                SELECT p50_speed FROM speed_profiles
                WHERE segment_id = :i AND day_type = :d AND bucket_15m = :b
                  AND is_ramadan = :r AND is_school = :sc
                """
            ),
            {
                "i": segment_id, "d": dtype, "b": b,
                "r": flags["is_ramadan"], "sc": flags["is_school"],
            },
        ).scalar()
        if v is not None:
            return float(v)

        # المحاولة 2: نفس نوع اليوم، أقرب شريحة ضمن حدّ الاستيفاء.
        #
        # كان الحدّ ±1 (15 دقيقة). وهو ضيّق جداً: مقطع مقيس عند 06:30
        # يُعتبر مجهولاً عند 06:45، فيتراجع إلى وسيط الصنف — بينما هو
        # **مقيس فعلاً** على بعد 15 دقيقة. وهذا يُنتج اختلاف تغطية بين
        # الشرائح، وهو سبب تغيّر المسار المقاس (261 مقابل 317 مقطعاً).
        #
        # الحدّ الآن هو نفسه المستخدم في الاستيفاء الجماعي
        # (`MAX_INTERP_BUCKETS`)، فالمساران يتفقان.
        v = s.execute(
            text(
                """
                SELECT p50_speed FROM speed_profiles
                WHERE segment_id = :i AND day_type = :d
                  AND bucket_15m BETWEEN :b1 AND :b2
                ORDER BY abs(bucket_15m - :b) LIMIT 1
                """
            ),
            {"i": segment_id, "d": dtype, "b": b,
             "b1": max(0, b - MAX_INTERP_BUCKETS),
             "b2": min(95, b + MAX_INTERP_BUCKETS)},
        ).scalar()
        if v is not None:
            return float(v)

        # المحاولة 3: أي يوم عمل، نفس الشريحة
        v = s.execute(
            text(
                """
                SELECT p50_speed FROM speed_profiles
                WHERE segment_id = :i AND day_type = 'WORKDAY' AND bucket_15m = :b
                """
            ),
            {"i": segment_id, "b": b},
        ).scalar()
    return float(v) if v is not None else None


def estimate_segment(
    seg: dict,
    when: datetime,
    dtype: str,
    flags: dict[str, bool],
    now: datetime,
    live_map: dict[int, float] | None = None,
    prof_map: dict[int, float] | None = None,
    class_map: dict[str, float] | None = None,
    ratio_map: dict[str, float] | None = None,
) -> SegmentEstimate:
    """تقدير مقطع واحد بالترتيب: حي ← ملف تعريف ← صنف ← سرعة حرة.

    `live_map`/`prof_map`/`class_map` اختيارية: عند تمريرها لا نستعلم
    لكل مقطع، بل نقرأ من الخريطة الجاهزة. هذا يحوّل مساراً من 200 مقطع
    من 400 استعلام إلى استعلامين أو ثلاثة.

    **الترتيب مقصود ولا يُعكس:**
    - حي (conf 0.9): نعرف هذا المقطع الآن.
    - ملف تعريف (0.6): نعرف هذا المقطع في مثل هذا الوقت.
    - صنف (0.35): لا نعرف هذا المقطع، لكن نعرف كيف يتصرف صنفه —
      طريق رئيسي في 08:00 يتباطأ حتى لو لم نقسه بنفسه.
    - سرعة حرة (0.3): لا نعرف شيئاً. نعرضها بثقة منخفضة وبوسم واضح.

    الفرق بين 0.35 و0.6 هو الفرق بين «نستنتج» و«نعرف» — ولا نخلط بينهما.
    """
    sid = int(seg["seg_id"])
    length = float(seg["length_m"])
    free = float(seg["speed_free_kmh"])
    b = bucket_15m(when)

    if live_map is not None:
        live = live_map.get(sid)
        age = 0.0 if live is not None else 9999.0
    else:
        live, age = fetch_live_speed(sid, now)

    if prof_map is not None:
        prof = prof_map.get(sid)
    else:
        prof = fetch_profile_speed(sid, b, dtype, flags)

    if live is not None and age <= LIVE_MAX_AGE_MIN:
        speed = LIVE_WEIGHT * live + (1 - LIVE_WEIGHT) * (prof or free)
        basis = "live"
        conf = 0.9 if age <= 5 else 0.8
    elif prof is not None:
        if live is not None and age <= 60:
            w = max(0.0, 0.4 * (1 - age / 60))
            speed = (1 - w) * prof + w * live
            basis = "profile+stale"
            conf = 0.6
        else:
            speed = prof
            basis = "profile"
            conf = 0.6
        age = None
    else:
        # لا نعرف هذا المقطع. هل نعرف صنفه؟
        prior = None
        # النسبة أولاً: تصف سلوك الشارع نسبةً إلى سرعته الحرة، فتصحّ
        # لمقطع سرعته الحرة 40 أو 60 على حد سواء. الوسيط المطلق يخلط
        # بينهما. مقاسة: النسبة تخفض p90 من 84% إلى 59%.
        if ratio_map is not None:
            r = ratio_map.get(str(seg.get("road_class") or ""))
            if r is not None and r > 0:
                prior = r * free
        if prior is None and class_map is not None:
            prior = class_map.get(str(seg.get("road_class") or ""))
        if prior is not None:
            speed = prior
            basis = "class"
            conf = 0.35
        else:
            speed = free
            basis = "freeflow"
            conf = 0.3
        age = None

    speed = max(3.0, speed)
    dur = length / (speed / 3.6)
    return SegmentEstimate(
        segment_id=sid,
        length_m=length,
        speed_kmh=round(speed, 1),
        duration_s=round(dur, 1),
        basis=basis,
        age_min=round(age, 1) if age is not None else None,
        confidence=conf,
    )


# ============================================================
# 2. عوامل التصحيح
# ============================================================

def weather_factor_now(now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    with session_scope() as s:
        v = s.execute(
            text(
                "SELECT factor FROM weather_obs "
                "WHERE ts_utc > :t AND ts_utc <= :now "
                "ORDER BY ts_utc DESC LIMIT 1"
            ),
            {"t": now - timedelta(hours=2), "now": now},
        ).scalar()
    return float(v) if v is not None else 1.0


def incident_penalty_for(segment_ids: list[int]) -> tuple[float, list[str]]:
    """عقوبة الأعطال على مسار.

    القاعدة:
    - إغلاق طريق: المسار يجب استبعاده (نعيد عقوبة عالية جداً + تحذير).
    - حادث/أشغال: عقوبة 1.15..1.35 حسب الخطورة.
    """
    if not segment_ids:
        return 1.0, []

    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT segment_id, category_name, severity, magnitude, delay_s
                FROM incidents
                WHERE segment_id = ANY(:ids)
                  AND ts_utc > now() - interval '2 hours'
                """
            ),
            {"ids": segment_ids},
        ).mappings().all()

    if not rows:
        return 1.0, []

    penalty = 1.0
    warnings: list[str] = []
    for r in rows:
        cat = r["category_name"] or ""
        if cat == "road_closed":
            penalty *= 3.0
            warnings.append(f"طريق مغلق على المقطع {r['segment_id']}")
        elif cat in ("accident", "broken_down_vehicle"):
            penalty *= 1.25
            warnings.append(f"حادث/عطل على المقطع {r['segment_id']}")
        elif cat in ("road_works", "lane_closed"):
            penalty *= 1.15
            warnings.append(f"أشغال على المقطع {r['segment_id']}")
        elif cat == "jam":
            penalty *= 1.10
    return min(penalty, 3.0), warnings


# ============================================================
# 3. تقدير مسار
# ============================================================

def route_segments(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    when: datetime | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """مقاطع المسار الحقيقي — توجيه Dijkstra على شبكتنا.

    كانت الطريقة القديمة تأخذ كل مقطع داخل 900م من خط مستقيم، فتجمع
    مئات المقاطع غير المتصلة. الآن نأخذ المسار الفعلي: متصل، بطول حقيقي.
    """
    from zahma.predict.router import route_at

    path = route_at(from_lat, from_lon, to_lat, to_lon, when=when, now=now)
    if not path.found:
        return []

    ids = path.seg_ids
    if not ids:
        return []

    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT seg_id, length_m, speed_free_kmh, road_class
                FROM segments WHERE seg_id = ANY(:ids)
                """
            ),
            {"ids": ids},
        ).mappings().all()

    by_id = {int(r["seg_id"]): dict(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def estimate_route(
    from_lat: float, from_lon: float, to_lat: float, to_lon: float,
    when: datetime | None = None, now: datetime | None = None,
    distance_m: float | None = None,
) -> RouteEstimate:
    """التقدير الكامل لرحلة — على المسار الحقيقي.

    الترتيب مهم للأداء: نقرأ السرعات الحية وملفات التعريف **مرة واحدة**،
    نستخدمها للتوجيه ولتقدير كل مقطع. القراءة مرتين كانت تضاعف العمل
    بلا فائدة، وقد تُنتج سرعتين مختلفتين لنفس المقطع في نفس الطلب.

    ملاحظة: `distance_m` للتحقق فقط (مقارنة طول المسار المحسوب بمسافة
    خارجية). لم نعد نطبّع عليه، لأن طول المسار الآن صحيح بطبيعته.
    """
    from zahma.predict.router import route, speeds_at

    now = now or datetime.now(UTC)
    when = when or now
    dtype = day_type_of(when)
    flags = calendar_flags(when)
    b = bucket_15m(when)

    # السرعات تُقرأ مرة واحدة وتُستخدم للتوجيه ولتقدير كل مقطع.
    # القراءة مرتين كانت تُنتج سرعتين مختلفتين لنفس المقطع في نفس الطلب.
    speeds = speeds_at(when=when, now=now)

    live_map = fetch_live_speeds_bulk(now, max_age_min=LIVE_MAX_AGE_MIN)
    prof_map = fetch_profile_speeds_bulk(b, dtype, flags)
    class_map = fetch_class_speeds_bulk(b, dtype, flags)
    ratio_map = fetch_class_ratios_bulk(b, dtype, flags)

    path = route(from_lat, from_lon, to_lat, to_lon, speeds=speeds)
    if not path.found:
        # المسافة تأتي من الراوتر نفسه — قياس واحد لا استعلام ثانٍ.
        return RouteEstimate(
            duration_s=0.0, duration_p90_s=0.0, confidence=0.0,
            routable=False,
            warnings=[_unroutable_reason(path)],
        )

    ids = path.seg_ids
    with session_scope() as s:
        rows = s.execute(
            text(
                "SELECT seg_id, length_m, speed_free_kmh, road_class "
                "FROM segments WHERE seg_id = ANY(:ids)"
            ),
            {"ids": ids},
        ).mappings().all()
    by_id = {int(r["seg_id"]): dict(r) for r in rows}
    segs = [by_id[i] for i in ids if i in by_id]

    estimates = [
        estimate_segment(
            s, when, dtype, flags, now,
            live_map=live_map, prof_map=prof_map, class_map=class_map,
            ratio_map=ratio_map,
        )
        for s in segs
    ]
    return _aggregate(estimates, now)


def _aggregate(estimates: list[SegmentEstimate], now: datetime) -> RouteEstimate:
    """يجمع تقديرات المقاطع في تقدير رحلة — مصدر واحد للحقيقة.

    يُستخدم من `estimate_route` (مسار موجَّه) ومن `estimate_on_path`
    (مسار مثبَّت). لو كُتب التجميع مرتين لاختلف الرقمان لنفس الطريق —
    وهو بالضبط نوع التناقض الذي يهدم الثقة.
    """
    raw_total = sum(e.duration_s for e in estimates)

    wf = weather_factor_now(now)
    inc_penalty, warnings = incident_penalty_for([e.segment_id for e in estimates])

    total = raw_total * wf * inc_penalty

    basis_counts: dict[str, int] = {}
    for e in estimates:
        basis_counts[e.basis] = basis_counts.get(e.basis, 0) + 1

    n = len(estimates)
    n_live = basis_counts.get("live", 0)

    # الثقة = متوسط يقين مقاطع المسار، لا صيغة سحرية.
    #
    # النسخة السابقة كانت `0.25 + 0.5*measured_share` حيث «المقيس» هو
    # الحي وملف التعريف فقط. النتيجة: مسار كله أولوية صنف (وهي معلومة
    # حقيقية عن سلوك الصنف الزمني) كان يحصل على 0.25 — أي أننا نعاقب
    # أنفسنا على استنتاج صحيح. والأسوأ: العتبة 0.4 تمنع أي توصية،
    # فيصمت المنتج تماماً على كل شوارع المدينة.
    #
    # المتوسط مفهوم ويُشرح للمستخدم: «متوسط ما نعرفه عن مقاطع طريقك».
    # حي 0.9، ملف 0.6، صنف 0.35، حر 0.3 — والمتوسط يقع بينها بصدق.
    conf = sum(e.confidence for e in estimates) / n if n else 0.0

    if n and n_live / n > 0.3:
        conf += 0.10  # معظم المسار مقيس الآن
    if inc_penalty > 1.0:
        conf -= 0.10
    if wf > 1.05:
        conf -= 0.05
    conf = max(0.0, min(0.95, conf))

    p90 = total * (1.0 + 0.22 * (1.0 - conf) + 0.05)

    return RouteEstimate(
        duration_s=round(total, 1),
        duration_p90_s=round(p90, 1),
        confidence=round(conf, 3),
        basis_counts=basis_counts,
        segments=estimates,
        weather_factor=wf,
        incident_penalty=inc_penalty,
        warnings=warnings,
    )


# ============================================================
# 4. مستشار الانطلاق
# ============================================================

@dataclass(slots=True)
class DepartureOption:
    depart_at: datetime
    arrive_at: datetime
    duration_s: float
    duration_p90_s: float
    confidence: float
    saving_vs_now_s: float


def departure_curve(
    from_lat: float, from_lon: float, to_lat: float, to_lon: float,
    horizon_min: int = 180, step_min: int = 5,
    now: datetime | None = None,
) -> list[DepartureOption]:
    """منحنى: مدة الرحلة مقابل وقت الخروج — **على مسار ثابت**.

    هذه الميزة التي تبيع: «اخرج في 06:35 فتصل في 07:06». والمقارنة لا
    تصحّ إلا إذا كانت كل نقطة تقيس **نفس الرحلة**.

    **العيب المقاس الذي يحرسه هذا التصميم:** كان كل خيار يستدعي
    `estimate_route` كاملاً، فيوجّه Dijkstra من جديد بسرعات تلك الشريحة.
    وحين تختلف تغطية الملفات بين الشرائح، تتغيّر الأوزان النسبية، فيختار
    مساراً آخر. القياس على باب الزوار ← وسط الجزائر:

       07:30: 261 مقطعاً، 14.78 كم، 21.55 د
       07:45: 298 مقطعاً، 13.94 كم، 28.34 د

    المسار **أقصر** لكن المدة **أطول بـ6.79 دقيقة** — ثم تعود. وهذا
    يفسّر القفزة +6.78 ثم −4.34 التي كسرت حارس الرتابة.

    **الفصل الحاسم:** حسبنا مدة كل مسار بالسرعتين:

       نفس المسار، سرعتان مختلفتان:  2.5–3.6% فرقاً
       مساران مختلفان، سرعات مختلفة: 10.6% فرقاً

    أي أن التذبذب **ثلاثة أضعاف** من اختيار المسار لا من السرعة. فالسرعات
    سليمة؛ المنحنى كان يقارن رحلتين.

    **الحل:** نوجّه مرة واحدة، ثم نقيس المدة على **نفس المقاطع** لكل
    شريحة. هذا ما تفعله تطبيقات الملاحة: «نفس الطريق، أوقات مختلفة».
    وهو أيضاً ما يسأل عنه المستخدم: «أخرج الآن أم بعد ساعة **على طريقي**».

    **الحدّ المقصود:** لا نُعيد التوجيه داخل المنحنى. من يريد مساراً
    بديلاً يطلب رحلة جديدة — وهذا صريح لا مخفي.
    """
    from zahma.predict.router import route, speeds_at

    now = now or datetime.now(UTC)

    # المسار يُثبَّت مرة واحدة بسرعات وقت الانطلاق.
    path = route(
        from_lat, from_lon, to_lat, to_lon,
        speeds=speeds_at(when=now, now=now),
    )
    if not path.found:
        return []

    seg_ids = list(path.seg_ids)
    base = estimate_route(from_lat, from_lon, to_lat, to_lon, when=now, now=now)
    if not base.routable:
        return []

    out: list[DepartureOption] = []
    for m in range(0, horizon_min + 1, step_min):
        t = now + timedelta(minutes=m)
        if m == 0:
            est = base
        else:
            est = estimate_on_path(seg_ids, when=t, now=now)
        out.append(
            DepartureOption(
                depart_at=t,
                arrive_at=t + timedelta(seconds=est.duration_s),
                duration_s=est.duration_s,
                duration_p90_s=est.duration_p90_s,
                confidence=est.confidence,
                saving_vs_now_s=base.duration_s - est.duration_s,
            )
        )
    return out


def estimate_on_path(
    seg_ids: list[int],
    when: datetime,
    now: datetime | None = None,
) -> RouteEstimate:
    """تقدير مدة **مسار محدّد** في وقت معيّن — بلا إعادة توجيه.

    يُستخدم في `departure_curve` لتثبيت المقارنة على نفس الطريق. ويعيد
    نفس بنية `RouteEstimate` كي يبقى العقد واحداً بين المسارين.
    """
    from zahma.predict.router import speeds_at

    now = now or datetime.now(UTC)
    dtype = day_type_of(when)
    flags = calendar_flags(when)
    b = bucket_15m(when)

    live_map = fetch_live_speeds_bulk(now, max_age_min=LIVE_MAX_AGE_MIN)
    prof_map = fetch_profile_speeds_bulk(b, dtype, flags)
    class_map = fetch_class_speeds_bulk(b, dtype, flags)
    ratio_map = fetch_class_ratios_bulk(b, dtype, flags)

    with session_scope() as s:
        rows = s.execute(
            text(
                "SELECT seg_id, length_m, speed_free_kmh, road_class "
                "FROM segments WHERE seg_id = ANY(:ids)"
            ),
            {"ids": seg_ids},
        ).mappings().all()
    by_id = {int(r["seg_id"]): dict(r) for r in rows}
    segs = [by_id[i] for i in seg_ids if i in by_id]
    if not segs:
        return RouteEstimate(
            duration_s=0.0, duration_p90_s=0.0, confidence=0.0,
            routable=False, warnings=["لا مقاطع في المسار المحدّد"],
        )

    estimates = [
        estimate_segment(
            s, when, dtype, flags, now,
            live_map=live_map, prof_map=prof_map, class_map=class_map,
            ratio_map=ratio_map,
        )
        for s in segs
    ]
    return _aggregate(estimates, now)


def best_departure(
    curve: list[DepartureOption], min_confidence: float = 0.4
) -> DepartureOption | None:
    """أفضل نافذة: أقل مدة، بشرط ثقة مقبولة."""
    usable = [c for c in curve if c.confidence >= min_confidence]
    if not usable:
        return None
    return min(usable, key=lambda c: c.duration_s)


def latest_departure_for_deadline(
    curve: list[DepartureOption], deadline: datetime, confidence_target: float = 0.8
) -> DepartureOption | None:
    """«اخرج قبل 07:23 لتصل قبل 08:00 بثقة 80%».

    نأخذ آخر خروج يضمن الوصول في الموعد بـ p90 (لا p50).
    استخدام p90 هنا مقصود: المستخدم يفضّل الوصول مبكراً على التأخر.
    """
    ok = [c for c in curve if c.arrive_at + timedelta(
        seconds=(c.duration_p90_s - c.duration_s)
    ) <= deadline]
    if not ok:
        return None
    return max(ok, key=lambda c: c.depart_at)
