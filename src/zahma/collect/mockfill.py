"""ملء البيانات الوهمية — يسمح ببناء النموذج والتطبيق قبل وصول المفاتيح."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from zahma.collect.writer import write_result
from zahma.db import session_scope
from zahma.sources.mock import MockSource

TZ = ZoneInfo("Africa/Algiers")


def fill(
    days: int = 14,
    step_min: int = 30,
    n_segments: int = 200,
    n_pairs: int = 40,
    corridors_only: bool = True,
) -> dict:
    """يولّد تاريخاً وهمياً واقعياً.

    **أي مقاطع نملأ؟** هذا قرار جوهري لا تفصيل.

    الترتيب بـ`importance` المطلق يعطي الطرق السريعة فقط: أهميتها
    (طول × صنف) تهيمن، فتُختار الـmotorway وحدها ويبقى وسط المدينة
    بلا عينات. النتيجة: منحنى الانطلاق مسطّح على أي مسار داخلي،
    والمنتج يبدو كأنه لا يعرف شيئاً — وهو فعلاً لا يعرف، لأننا لم نقس.

    لذلك نملأ **مقاطع المحاور** أولاً: هي ما سنقيسه فعلياً في الإنتاج
    (TomTom Flow على 6 محاور + Mapbox على 200 زوج). ملء أي شيء آخر
    يعطينا نموذجاً يقيس ما لن نقيسه.
    """
    with session_scope() as s:
        # التوزيع على الأصناف — لا ترتيب مطلق.
        #
        # الترتيب المطلق بـimportance يعطي motorway دائماً: أهميتها
        # (طول × صنف) تهيمن على كل شيء، فيبقى residential/tertiary
        # بلا عينات. النتيجة: كل مسار داخلي يقع على مقاطع لم نقسها،
        # فيصبح المنحنى مسطّحاً — وهذا ما حدث فعلاً.
        #
        # نقسّم الحصة على الأصناف بالسوية تقريباً، ثم نأخذ الأعلى
        # أهمية داخل كل صنف. هكذا نملك عينات لكل صنف، وأولوية الصنف
        # (class_profiles) تصبح ممكنة.
        if corridors_only:
            segs = s.execute(
                text(
                    """
                    WITH pool AS (
                        SELECT g.seg_id, g.speed_free_kmh, g.length_m, g.road_class,
                               g.importance,
                               ROW_NUMBER() OVER (
                                   PARTITION BY g.road_class ORDER BY g.importance DESC
                               ) AS rn
                        FROM segments g
                        WHERE g.seg_id IN (SELECT unnest(seg_ids) FROM corridors)
                          AND g.measurable
                    )
                    SELECT seg_id, speed_free_kmh, length_m, road_class
                    FROM pool
                    WHERE rn <= GREATEST(10, :per_class)
                    ORDER BY importance DESC
                    LIMIT :k
                    """
                ),
                {"k": n_segments, "per_class": max(10, n_segments // 6)},
            ).mappings().all()
            # إن كانت المحاور أقل من المطلوب، نكمل من بقية المقاطع القابلة
            # للقياس — بنفس التوزيع على الأصناف.
            if len(segs) < n_segments:
                have = [r["seg_id"] for r in segs] or [0]
                extra = s.execute(
                    text(
                        """
                        WITH pool AS (
                            SELECT g.seg_id, g.speed_free_kmh, g.length_m, g.road_class,
                                   g.importance,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY g.road_class ORDER BY g.importance DESC
                                   ) AS rn
                            FROM segments g
                            WHERE g.measurable AND NOT (g.seg_id = ANY(:have))
                        )
                        SELECT seg_id, speed_free_kmh, length_m, road_class
                        FROM pool
                        WHERE rn <= GREATEST(10, :per_class)
                        ORDER BY importance DESC
                        LIMIT :k
                        """
                    ),
                    {
                        "have": have,
                        "k": n_segments - len(segs),
                        "per_class": max(10, (n_segments - len(segs)) // 6),
                    },
                ).mappings().all()
                segs = list(segs) + list(extra)
        else:
            segs = s.execute(
                text(
                    """
                    WITH pool AS (
                        SELECT seg_id, speed_free_kmh, length_m, road_class, importance,
                               ROW_NUMBER() OVER (
                                   PARTITION BY road_class ORDER BY importance DESC
                               ) AS rn
                        FROM segments WHERE measurable
                    )
                    SELECT seg_id, speed_free_kmh, length_m, road_class
                    FROM pool
                    WHERE rn <= GREATEST(10, :per_class)
                    ORDER BY importance DESC
                    LIMIT :k
                    """
                ),
                {"k": n_segments, "per_class": max(10, n_segments // 6)},
            ).mappings().all()

        pairs = s.execute(
            text("SELECT pair_id, crow_km FROM od_pairs ORDER BY weight DESC LIMIT :k"),
            {"k": n_pairs},
        ).mappings().all()

    seg_list = [dict(r) for r in segs]
    pair_list = [dict(r) for r in pairs]

    mock = MockSource()
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    total = {"segments": 0, "routes": 0, "incidents": 0}
    t = start
    n = 0
    while t <= end:
        # نمرّر عدد المقاطع كاملاً: الافتراضي 40 كان يقصّ القائمة،
        # فتصل العينات إلى 40 مقطعاً فقط من 600 — أي أن 93% من
        # القائمة لم تُقس أبداً وبقيت بلا ملف تعريف.
        res = mock.fetch(
            segments=seg_list,
            pairs=pair_list,
            now=t,
            n_segments=len(seg_list),
            n_pairs=len(pair_list),
        )
        w = write_result(res)
        for k in total:
            total[k] += w.get(k, 0)
        n += 1
        if n % 100 == 0:
            print(f"  {n} steps, {total}", flush=True)
        t += timedelta(minutes=step_min)

    print(f"[mock] {n} steps -> {total}", flush=True)
    return total


if __name__ == "__main__":
    fill()
