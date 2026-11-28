"""هل يعطي Mapbox سرعة **آنية** للجزائر، أم جدولاً دائماً؟

**السؤال الذي يقرّر صدق المنتج كله.** إن كان المصدر يعطي حالة آنية، فنحن
نستطيع تقديم «حي». وإن كان يعيد جدولاً ثابتاً، فلا يوجد حي أصلاً — لا في
الكود ولا في المصدر — وكل ما نبنيه قبلي بطبيعته.

**ما نعرفه حتى الآن:**
- `depart_at` لماضٍ يعيد نفس الرقم بعد سنة (1575.8 ث في 4 تواريخ).
- الجدول مقابل المصدر: 100.000% مطابقة على 11,570 قياساً.
- النداء الحي يعيد الجدول حرفياً (نفس بصمة السرعات).

**ما نقيسه هنا:** نداء **بلا `depart_at`** — أي «الحالة الآن» بحسب
Mapbox — مقارنةً بنداء بـ`depart_at` صريح. إن اختلفا، فالحي موجود.
وإن تطابقا، فـ«الآن» عند Mapbox هو جدول أيضاً.
"""

from __future__ import annotations

import hashlib
import json

import httpx

from zahma.config import get_settings

# بومرداس ← زرالدة، مسار طويل يمر بذروات مختلفة.
ROUTE = "3.4770,36.7530;2.8420,36.7070"
# داخل الجزائر.
ROUTE2 = "3.1833,36.7167;3.0589,36.7705"


def call(token: str, coords: str, extra: dict) -> dict | None:
    params = {
        "access_token": token,
        "annotations": "speed,duration",
        "overview": "false",
        **extra,
    }
    r = httpx.get(
        f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{coords}",
        params=params,
        timeout=30,
    )
    d = r.json()
    if d.get("code") != "Ok":
        print(f"    ERR {d.get('code')}: {str(d.get('message'))[:70]}")
        return None
    rt = d["routes"][0]
    speeds = []
    for leg in rt["legs"]:
        speeds.extend(leg["annotation"]["speed"])
    return {
        "duration": rt["duration"],
        "typical": rt.get("duration_typical"),
        "n_edges": len(speeds),
        "speeds": speeds,
        "hash": hashlib.sha256(
            json.dumps([round(s, 3) for s in speeds]).encode()
        ).hexdigest()[:16],
    }


def main() -> int:
    s = get_settings()
    for name, coords in [("بومرداس←زرالدة", ROUTE), ("داخل الجزائر", ROUTE2)]:
        print(f"══ {name}")
        cases = [
            ("بلا depart_at (الآن)", {}),
            ("depart_at=now", {"depart_at": "now"}),
            ("depart_at=بعد ساعة", {"depart_at": "2026-12-11T08:00"}),
            ("depart_at=بعد أسبوع", {"depart_at": "2026-12-18T08:00"}),
        ]
        out = []
        for label, extra in cases:
            r = call(s.mapbox_token, coords, extra)
            if r is None:
                out.append((label, None))
                continue
            print(
                f"  {label:22s} dur={r['duration']:>8.1f}  "
                f"typical={r['typical']:>8.1f}  edges={r['n_edges']:>4}  "
                f"hash={r['hash']}"
            )
            out.append((label, r))

        print()
        valid = [(lbl, r) for lbl, r in out if r]
        if len(valid) >= 2:
            hashes = {r["hash"] for _, r in valid}
            durs = {round(r["duration"], 1) for _, r in valid}
            print(f"  بصمات مختلفة: {len(hashes)} | مدد مختلفة: {len(durs)}")
            if len(hashes) == 1:
                print("  ⇒ **كل النداءات متطابقة.** لا حالة آنية: «الآن»")
                print("     عند Mapbox جدول أيضاً. المنتج قبلي بطبيعته.")
            else:
                print("  ⇒ المصدر يميّز بين النداءات — قد توجد حالة آنية.")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
