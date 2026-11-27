"""هل يميّز Mapbox أيام الأسبوع على مستوى المسار؟ — الاختبار الحاسم.

**ما قِسناه سابقاً على مستوى المقطع أعطى نتيجة مختلطة** (السبت والأحد
يختلفان >3 كم/س على ~55% من المقاطع، لكن 30% أسرع و24% أبطأ). الاتجاه
المختلط يرجّح ضجيج إسقاط لا نمطاً حقيقياً.

**الاختبار النظيف:** على مستوى المسار (`duration`)، لا إسقاط ولا مقاطع.
نأخذ أسبوعاً كاملاً: الاثنين 11-30 → الأحد 12-06، نفس الساعة، ونقارن.

إن تطابقت المدة لكل يوم ⇒ الجدول لا يميّز أيام الأسبوع إطلاقاً.
إن اختلفت ⇒ يميّز، ونقيس بأي اتجاه.
"""

from __future__ import annotations

import httpx

from zahma.config import get_settings

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"
COORDS = "3.1,36.74;2.84,36.71"  # pair 15

DAYS = [
    ("2026-11-30", "الاثنين"),
    ("2026-12-01", "الثلاثاء"),
    ("2026-12-02", "الأربعاء"),
    ("2026-12-03", "الخميس"),
    ("2026-12-04", "الجمعة"),
    ("2026-12-05", "السبت"),
    ("2026-12-06", "الأحد"),
]


def dur(depart_at: str) -> float | None:
    s = get_settings()
    r = httpx.get(
        f"{BASE}/{COORDS}",
        params={
            "access_token": s.mapbox_token,
            "overview": "false",
            "depart_at": depart_at,
        },
        timeout=30,
    )
    if r.status_code >= 400:
        return None
    return r.json()["routes"][0]["duration"]


def main() -> int:
    for hour in ("08:00", "17:00", "03:00"):
        print(f"══ الساعة {hour}")
        vals = {}
        for d, name in DAYS:
            v = dur(f"{d}T{hour}")
            vals[name] = v
            print(f"   {name:9} {d}  " + (f"{v:.2f} ث" if v else "فشل"))
        good = {k: v for k, v in vals.items() if v}
        if len(good) > 1:
            spread = max(good.values()) - min(good.values())
            distinct = len({round(v, 2) for v in good.values()})
            print()
            print(f"   المدى: {spread:.2f} ث | قيم مختلفة: {distinct} من {len(good)}")
            if distinct == 1:
                print("   ⇒ **متطابق تماماً.** الجدول لا يميّز أيام الأسبوع.")
            elif spread < 1.0:
                print("   ⇒ فروق ضئيلة (<1 ث). عملياً لا يميّز.")
            else:
                print("   ⇒ يميّز أيام الأسبوع فعلاً.")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
