"""بعد إصلاح تصادم الكتابة: هل يتغيّر الجدول إطلاقاً؟

**السؤال الذي يقرّر مصير الجدولة كلها.** سابقاً قِسنا «انحرافاً» بنسبة
7.4% (خانة من 9)، ثم اكتشفنا أن السبب كان عيب last-writer-wins في كتابتنا
لا تغيّراً في المصدر.

بعد الإصلاح، نعيد نفس القياس على نفس الخانات. إن كانت النتيجة 100%
مطابقة، فالجدول ثابت تماماً، والجمع الدوري بلا قيمة — ويجب أن نبنيه
للكشف عن التغيّر فقط لا لجمع البيانات.

**كيف نقيس الآن بشكل صحيح:** نقارن **قياس الزوج نفسه** (من
`segment_pair_samples`) بما يعيده المصدر لنفس الزوج. سابقاً كنا نقارن
صفاً مجمَّعاً — وهو ما جعل النتيجة كاذبة.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text

from zahma.collect.match import measure_pair
from zahma.config import get_settings
from zahma.db import session_scope

SLOTS = [
    ("2026-12-09T08:00", 20),
]


def detail_for(pair_id: int, depart: str) -> dict[int, float]:
    local = depart.replace("T", " ")
    with session_scope() as ss:
        rows = ss.execute(
            text(
                """
                SELECT segment_id, speed_kmh
                FROM segment_pair_samples
                WHERE source::text = 'mapbox' AND pair_id = :p
                  AND ts_bucket >= (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                  AND ts_bucket <  (CAST(:d AS timestamp) AT TIME ZONE 'Africa/Algiers')
                                   + interval '5 minutes'
                """
            ),
            {"p": pair_id, "d": local},
        ).all()
    return {int(r[0]): float(r[1]) for r in rows}


def main() -> int:
    s = get_settings()

    for slot, n_pairs in SLOTS:
        print(f"══ الخانة {slot}")
        with session_scope() as ss:
            pairs = ss.execute(
                text(
                    """
                    SELECT pair_id, ST_Y(from_pt) flat, ST_X(from_pt) flon,
                           ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                    FROM od_pairs WHERE active ORDER BY weight DESC LIMIT :n
                    """
                ),
                {"n": n_pairs},
            ).mappings().all()

        total = exact = close = 0
        worst: list[tuple[float, int, int]] = []

        for p in pairs:
            old = detail_for(p["pair_id"], slot)
            if not old:
                continue
            pair = {
                "pair_id": p["pair_id"],
                "from": (p["flat"], p["flon"]),
                "to": (p["tlat"], p["tlon"]),
            }
            try:
                with httpx.Client(timeout=30) as client:
                    m = measure_pair(client, s.mapbox_token, pair, depart_at=slot)
            except Exception as exc:  # noqa: BLE001
                print(f"  pair={p['pair_id']}: خطأ {exc}")
                continue
            if m is None:
                continue
            new = {e.seg_id: e.speed_kmh for e in m.edges}
            common = set(old) & set(new)
            if not common:
                continue
            e_n = sum(1 for k in common if abs(old[k] - new[k]) < 0.005)
            c_n = sum(1 for k in common if abs(old[k] - new[k]) < 0.5)
            total += len(common)
            exact += e_n
            close += c_n
            for k in common:
                d = abs(old[k] - new[k])
                if d > 0.5:
                    worst.append((d, p["pair_id"], k))
            print(
                f"  pair={p['pair_id']:>2}: {len(common):>4} مقطع | "
                f"مطابق تماماً {100.0 * e_n / len(common):>6.2f}%"
            )

        print()
        if total:
            print(
                f"الإجمالي: {total:,} مقطع-قياس | "
                f"مطابق تماماً {100.0 * exact / total:.3f}% | "
                f"ضمن 0.5 {100.0 * close / total:.3f}%"
            )
            worst.sort(reverse=True)
            for d, pid, seg in worst[:5]:
                print(f"  أكبر فرق: pair={pid} مقطع={seg} فرق={d:.2f}")
            print()
            if exact == total:
                print("⇒ **الجدول ثابت تماماً.** لا تغيّر إطلاقاً.")
                print("   الجمع الدوري لا يجمع بيانات — يكشف تغيّراً فقط.")
            elif 100.0 * exact / total > 99.0:
                print("⇒ شبه ثابت (انحراف نادر). الجمع الدوري للمراقبة فقط.")
            else:
                print("⇒ الجدول يتغيّر فعلاً — الجمع الدوري ضروري.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
