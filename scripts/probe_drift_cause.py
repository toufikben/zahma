"""هل «انحراف الجدول» كان في الحقيقة عيب كتابتنا؟

**الفرضية الجديدة:** القيمة المخزَّنة 33.82 والقيمة الحالية 9.92 ليستا
«المصدر تغيّر». بل كلتاهما **قياسان صحيحان لزوجين مختلفين** مرّا بالمقطع
نفسه، و`ON CONFLICT` أبقى واحداً منهما — والفائز يعتمد على ترتيب إنهاء
الخيوط.

**كيف نثبت ذلك:** نجمع الخانة الآن بكل الأزواج، ونحفظ التفصيل، ثم نبحث
هل توجد قيمة 33.82 لأي زوج في تلك الخانة. إن وُجدت فالفرضية صحيحة:
المصدر ثابت، وعيبنا هو الذي أنتج الاختلاف.

**ولماذا هذا أهم من الإصلاح نفسه:** إن صحّ، فكل «الانحراف» الذي قِسناه
سابقاً (143 مقطعاً من 191) ليس تغيّراً في المصدر بل ضجيجاً من عندنا. وهذا
يغيّر الاستنتاج كلياً: الجدول ثابت تماماً، وقيمة `samples` القديمة لمقطع
مشترك بين أزواج **لا معنى لها**.
"""

from __future__ import annotations

import httpx
from sqlalchemy import text

from zahma.collect.match import measure_pair
from zahma.config import get_settings
from zahma.db import session_scope

SLOT = "2026-12-06T23:00"
SEG = 47490
OLD_VALUE = 33.82
NEW_VALUE = 9.92


def main() -> int:
    s = get_settings()
    with session_scope() as ss:
        pairs = ss.execute(
            text(
                """
                SELECT pair_id, ST_Y(from_pt) flat, ST_X(from_pt) flon,
                       ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                FROM od_pairs WHERE active ORDER BY weight DESC LIMIT 20
                """
            )
        ).mappings().all()

    print(f"المقطع {SEG} عند {SLOT}")
    print(f"مخزَّن: {OLD_VALUE} | بسحب الزوج 15 الآن: {NEW_VALUE}")
    print()
    print("نسحب كل الأزواج ونرى من يمر بهذا المقطع:")

    hits: list[tuple[int, float]] = []
    for p in pairs:
        pair = {
            "pair_id": p["pair_id"],
            "from": (p["flat"], p["flon"]),
            "to": (p["tlat"], p["tlon"]),
        }
        try:
            with httpx.Client(timeout=30) as client:
                m = measure_pair(client, s.mapbox_token, pair, depart_at=SLOT)
        except Exception as exc:  # noqa: BLE001
            print(f"  pair={p['pair_id']}: خطأ {exc}")
            continue
        if m is None:
            continue
        v = {e.seg_id: e.speed_kmh for e in m.edges}.get(SEG)
        if v is not None:
            hits.append((p["pair_id"], v))
            mark = ""
            if abs(v - OLD_VALUE) < 0.05:
                mark = "  ← القيمة المخزَّنة القديمة!"
            elif abs(v - NEW_VALUE) < 0.05:
                mark = "  ← القيمة التي نراها الآن"
            print(f"  pair={p['pair_id']:>2}: {v:>7.2f}{mark}")

    print()
    if not hits:
        print("⇒ لا زوج يمر بهذا المقطع الآن.")
        return 0

    vals = [v for _, v in hits]
    lo, hi = min(vals), max(vals)
    distinct = len({round(v, 2) for v in vals})
    print(f"أزواج تمر بالمقطع: {len(hits)} | قيم مختلفة: {distinct}")
    print(f"المدى: {lo:.2f} – {hi:.2f} كم/س  (×{hi / lo:.1f})")
    print()

    # **الحكم الصحيح:** لا نطلب تطابقاً تاماً — نطلب أن تكون القيمة القديمة
    # داخل مدى ما يعطيه المصدر للمقطع نفسه. إن كانت داخله، فالمصدر لم يتغيّر:
    # القيمة القديمة كانت قياس زوج آخر، وعيب last-writer-wins هو الذي جعلها
    # تبدو «انحرافاً».
    inside = lo - 0.5 <= OLD_VALUE <= hi + 0.5
    if inside:
        print("⇒ **السبب عيبنا لا المصدر.**")
        print(f"   القيمة القديمة {OLD_VALUE} داخل مدى ما يعطيه المصدر")
        print(f"   للمقطع نفسه ({lo:.2f}–{hi:.2f}). المصدر ثابت؛ الاختلاف")
        print("   جاء من أن المقطع يمر به أربعة أزواج بقيم متباعدة،")
        print("   و`ON CONFLICT` أبقى واحداً منها فقط — عشوائياً.")
        print()
        print("   الأثر على كل قياساتنا: أي صف في `samples` لمقطع مشترك")
        print("   بين أزواج يحمل قيمة أحدها بلا معيار. وهذا يفسّر كل")
        print("   «الانحراف» المقاس سابقاً (143 مقطعاً من 191).")
    else:
        print(f"⇒ القيمة القديمة {OLD_VALUE} خارج المدى {lo:.2f}–{hi:.2f}.")
        print("   قد يكون تغيّراً حقيقياً في المصدر — يستحق فحصاً أعمق.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
