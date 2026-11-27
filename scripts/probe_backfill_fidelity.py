"""هل إعادة سحب `depart_at` ماضٍ تعيد نفس ما خزّناه؟ — القياس الحاسم.

**لماذا هذا الملف:** ادّعينا «التشغيل الفائت يُملأ بلا خسارة» استناداً إلى
أن الطلب المتكرر في نفس الثانية يعطي نفس الرقم. لكن ذلك اختبار ضعيف:
إن كان هناك مكوّن حي يتحرك على مدى دقائق/ساعات، فالتكرار السريع لا يكشفه.

الاختبار الصحيح: نأخذ صفوفاً **خزّنّاها فعلاً في وقت سابق**، ونسحب نفس
`depart_at` الآن، ونقارن مقطعاً بمقطع. نسبة التطابق هي الرقم الذي يقرّر
إن كان الملء أميناً أم لا.

إن كانت النسبة 100% ⇒ الملء يعيد الماضي بدقة، والخادم 24/7 بلا قيمة.
إن كانت أقل ⇒ الملء يعيد *رأي المصدر اليوم* في ذلك الوقت، لا ما كان عليه.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text

from zahma.collect.match import measure_pair
from zahma.config import get_settings
from zahma.db import session_scope

# مقاطع مختارة: يومان عاديان + ليلة + ذروة صباحية.
SLOTS = [
    "2026-12-02T03:00",
    "2026-12-04T03:00",
    "2026-12-06T23:00",
    "2026-12-02T08:00",
    "2026-12-05T17:00",
]
PAIR = 15


def stored_for(depart: str) -> dict[int, float]:
    """القيم المخزَّنة للمقطع عند هذه الساعة بالضبط."""
    local = depart.replace("T", " ")
    with session_scope() as ss:
        rows = ss.execute(
            text(
                """
                SELECT segment_id, speed_kmh
                FROM samples
                WHERE source::text = 'mapbox' AND speed_kmh IS NOT NULL
                  AND split_part(raw_ref, ';', 1) = :p
                  AND ts_bucket >= (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                  AND ts_bucket <  (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                                   + interval '5 minutes'
                """
            ),
            {"p": f"pair={PAIR}", "d": local},
        ).all()
    return {int(r[0]): float(r[1]) for r in rows}


def main() -> int:
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
            {"p": PAIR},
        ).mappings().one()
    pair = {
        "pair_id": p["pair_id"],
        "from": (p["flat"], p["flon"]),
        "to": (p["tlat"], p["tlon"]),
    }

    print(f"إعادة سحب {len(SLOTS)} ساعة على الزوج {PAIR} ومقارنتها بالمخزَّن")
    print()
    total_seg = 0
    total_exact = 0
    total_close = 0

    for slot in SLOTS:
        old = stored_for(slot)
        if not old:
            print(f"── {slot}: لا صفوف مخزَّنة، تخطٍّ")
            continue

        with httpx.Client(timeout=30) as client:
            m = measure_pair(client, s.mapbox_token, pair, depart_at=slot)
        if m is None:
            print(f"── {slot}: فشل السحب")
            continue
        new = {e.seg_id: e.speed_kmh for e in m.edges}

        common = set(old) & set(new)
        exact = sum(1 for k in common if abs(old[k] - new[k]) < 0.005)
        close = sum(1 for k in common if abs(old[k] - new[k]) < 0.5)
        diffs = sorted(
            (abs(old[k] - new[k]), k) for k in common
        )[-3:]

        total_seg += len(common)
        total_exact += exact
        total_close += close

        pct_exact = 100.0 * exact / len(common) if common else 0.0
        pct_close = 100.0 * close / len(common) if common else 0.0
        print(
            f"── {slot}: {len(common)} مقطع مشترك | "
            f"مطابق تماماً {pct_exact:.1f}% | ضمن 0.5 كم/س {pct_close:.1f}%"
        )
        for d, k in diffs:
            if d > 0.5:
                print(f"     أكبر فرق: مقطع {k}  {old[k]:.2f} → {new[k]:.2f}")

    print()
    if total_seg:
        print(
            f"الإجمالي: {total_seg:,} مقطع | "
            f"مطابق تماماً {100.0 * total_exact / total_seg:.2f}% | "
            f"ضمن 0.5 كم/س {100.0 * total_close / total_seg:.2f}%"
        )
        rate = 100.0 * total_exact / total_seg
        print()
        if rate > 99.5:
            print("⇒ المصدر دالة محضة في `depart_at`. الملء أمين بالكامل.")
        elif rate > 95:
            print("⇒ شبه حتمي. الملء أمين تقريباً، مع انحراف نادر.")
        else:
            print("⇒ **ليس حتمياً.** الملء يعيد رأي المصدر الآن لا ما كان عليه.")
            print("   ادعاء «بلا خسارة» يحتاج تخفيفاً صريحاً.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
