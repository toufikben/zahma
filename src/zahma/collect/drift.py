"""كشف انحراف جدول المصدر — القدرة التي يمحوها `ON CONFLICT` بلا أثر.

**المشكلة التي يحلّها هذا الملف:**

`samples` يستخدم `ON CONFLICT (segment_id, source, ts_bucket) DO UPDATE`.
أي إعادة جمع نفس الساعة **تستبدل** القيمة القديمة بصمت. النتيجة: لو تغيّر
جدول Mapbox بين جمعين، لا يمكن معرفة ذلك — الانحراف يُمحى في لحظة كتابته.

**وهذا ليس نظرياً:** قياسنا كشف خانة واحدة من تسع (2026-12-06 23:00)
أعادت 9.92 بدل 33.82 المخزَّنة. لو أعدنا جمعها بلا تسجيل، لضاعت الحقيقة
بلا أثر.

**الحل:** `verify_slot` تقارن المخزَّن بالجديد **قبل** الاستبدال، وتسجّل
كل فرق في `table_drift`. الجدول يصير سجل التغييرات الوحيد للمصدر — وهو
الأساس الذي يبرّر الجمع الدوري أصلاً.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text

from zahma.collect.match import measure_pair
from zahma.config import get_settings
from zahma.db import session_scope


def verify_slot(
    pair_id: int,
    depart_at: str,
    *,
    store_rows: bool = False,
    tolerance_kmh: float = 0.5,
) -> dict:
    """يسحب `depart_at` ماضياً ويقارنه بالمخزَّن، ويسجّل الانحراف.

    `store_rows`: إن صحّ، يُخزَّن ما أعاده المصدر (استبدال). الافتراضي
    خطأ — التحقق يجب أن يكون **قراءة فقط**، وإلا صار هو نفسه مصدر
    الانحراف الذي يقيسه.

    `tolerance_kmh`: عتبة عدّ الفرق انحرافاً. 0.5 كم/س — أصغر من أي
    تغيّر ذي معنى في قرار سفر، وأكبر من تقريب الفاصلة العائمة.
    """
    s = get_settings()
    with session_scope() as ss:
        p = ss.execute(
            text(
                """
                SELECT pair_id, ST_Y(from_pt) flat, ST_X(from_pt) flon,
                       ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                FROM od_pairs WHERE pair_id = :p
                """
            ),
            {"p": pair_id},
        ).mappings().first()
    if not p:
        return {"ok": False, "error": f"pair {pair_id} غير موجود"}

    pair = {
        "pair_id": p["pair_id"],
        "from": (p["flat"], p["flon"]),
        "to": (p["tlat"], p["tlon"]),
    }

    local = depart_at.replace("T", " ")
    with session_scope() as ss:
        stored = ss.execute(
            text(
                """
                SELECT segment_id, speed_kmh
                FROM segment_pair_samples
                WHERE source::text = 'mapbox' AND speed_kmh IS NOT NULL
                  AND pair_id = :p
                  AND ts_bucket >= (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                  AND ts_bucket <  (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                                   + interval '5 minutes'
                """
            ),
            {"p": pair_id, "d": local},
        ).all()
    old = {int(r[0]): float(r[1]) for r in stored}
    if not old:
        return {"ok": False, "error": "لا صفوف مخزَّنة لهذه الخانة"}

    with httpx.Client(timeout=30) as client:
        m = measure_pair(client, s.mapbox_token, pair, depart_at=depart_at)
    if m is None:
        return {"ok": False, "error": "فشل السحب"}

    new = {e.seg_id: e.speed_kmh for e in m.edges}
    common = set(old) & set(new)

    drifted = []
    for seg in common:
        diff = abs(old[seg] - new[seg])
        if diff > tolerance_kmh:
            rel = diff / old[seg] if old[seg] else None
            drifted.append(
                {
                    "segment_id": seg,
                    "old": old[seg],
                    "new": new[seg],
                    "abs_diff": round(diff, 3),
                    "rel_diff": round(rel, 4) if rel is not None else None,
                }
            )

    if drifted:
        with session_scope() as ss:
            ss.execute(
                text(
                    """
                    INSERT INTO table_drift
                        (source, pair_id, depart_at, scope, ref_id,
                         old_value, new_value, abs_diff, rel_diff)
                    VALUES
                        (CAST('mapbox' AS source_kind), :pair,
                         CAST(:dep AS timestamp) AT TIME ZONE 'Africa/Algiers',
                         'segment', :seg, :old, :new, :ad, :rd)
                    """
                ),
                [
                    {
                        "pair": pair_id,
                        "dep": local,
                        "seg": d["segment_id"],
                        "old": d["old"],
                        "new": d["new"],
                        "ad": d["abs_diff"],
                        "rd": d["rel_diff"],
                    }
                    for d in drifted
                ],
            )

    if store_rows and new:
        from zahma.collect.match import store
        from zahma.collect.match import _parse_depart
        from datetime import UTC, datetime

        ts = _parse_depart(depart_at) or datetime.now(UTC)
        store([m], ts, forecast=True)

    return {
        "ok": True,
        "pair_id": pair_id,
        "depart_at": depart_at,
        "compared": len(common),
        "drifted": len(drifted),
        "drift_pct": round(100.0 * len(drifted) / len(common), 2) if common else 0.0,
        "max_abs_diff": max((d["abs_diff"] for d in drifted), default=0.0),
        "examples": drifted[:3],
    }
