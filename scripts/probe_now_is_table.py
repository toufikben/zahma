"""هل «الآن» حالة حية، أم مجرد خانة الساعة الحالية في الجدول؟

**السؤال الحاسم.** القياس السابق: نداء بلا `depart_at` أعطى 1044.8 ث،
ونداء بـ`depart_at=08:00` أعطى 1557.2 ث. الفرق كبير — لكن الساعة الآن
01:00 ليلاً، وخانة الليل في الجدول أسرع بطبيعتها (60%).

فالفرق قد يكون:
  (أ) حالة حية فعلية — Mapbox يعرف أن الطريق فارغ الآن.
  (ب) مجرد خانة 01:00 في الجدول — أي جدولاً أيضاً، لا حياً.

**كيف نفرّق:** نسأل عن **نفس الساعة صراحةً** (`depart_at` = الساعة الحالية
بالضبط) ونقارنها بالنداء بلا `depart_at`. إن تطابقتا، فـ«الآن» = خانة
الساعة الحالية — أي جدول. وإن اختلفتا، فثمة شيء حي فعلاً.

**لماذا هذا يهم:** لو كان (ب)، فلا يوجد «حي» في المنتج إطلاقاً، وكل
واجهة تعرض «حالة الطريق الآن» ستكون كاذبة. ولا بد أن نسمّي المنتج باسمه:
نمط أسبوعي نموذجي، لا حالة لحظية.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from zahma.config import get_settings

ROUTE = "3.1833,36.7167;3.0589,36.7705"
TZ = ZoneInfo("Africa/Algiers")


def call(token: str, extra: dict) -> dict | None:
    params = {
        "access_token": token,
        "annotations": "speed,duration",
        "overview": "false",
        **extra,
    }
    r = httpx.get(
        f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{ROUTE}",
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
        "hash": hashlib.sha256(
            json.dumps([round(s, 3) for s in speeds]).encode()
        ).hexdigest()[:16],
    }


def main() -> int:
    s = get_settings()
    now_local = datetime.now(TZ)
    print(f"الوقت المحلي الآن: {now_local:%Y-%m-%d %H:%M} ({now_local:%A})")
    print()

    cases: list[tuple[str, dict]] = [("بلا depart_at", {})]
    # نفس الساعة الحالية، صراحةً — بثلاث دقائق مختلفة داخل نفس الخانة.
    for offset in (0, -3, 3):
        t = (now_local + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M")
        cases.append((f"depart_at={t} (الآن)", {"depart_at": t}))
    # نفس الساعة بعد أسبوع — يختبر هل اليوم يؤثر داخل نفس الساعة.
    t_week = (now_local + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
    cases.append((f"نفس الساعة +7 أيام", {"depart_at": t_week}))
    # نفس الساعة في يوم آخر — الجمعة مقابل الاثنين.
    t_fri = (now_local + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M")
    cases.append((f"نفس الساعة +4 أيام", {"depart_at": t_fri}))

    res: list[tuple[str, dict | None]] = []
    for label, extra in cases:
        r = call(s.mapbox_token, extra)
        if r:
            print(
                f"  {label:34s} dur={r['duration']:>8.1f}  "
                f"typical={r['typical']:>8.1f}  hash={r['hash']}"
            )
        res.append((label, r))

    print()
    valid = [(l, r) for l, r in res if r]
    if len(valid) < 2:
        print("⇒ نداءات غير كافية للحكم.")
        return 0

    live = valid[0][1]
    same_slot = [r for l, r in valid[1:4] if r]
    hashes = {r["hash"] for r in same_slot}

    print(f"بصمات «الآن» مقابل «نفس الساعة صراحةً»: {len(hashes)}")
    if all(r["hash"] == live["hash"] for r in same_slot):
        print("⇒ **«الآن» = خانة الساعة الحالية في الجدول.**")
        print("   لا حالة حية: Mapbox يعيد الجدول نفسه، والفرق الذي")
        print("   رأيناه سابقاً كان فقط أن الليل أسرع من الذروة.")
        print()
        print("   الأثر على المنتج: لا يوجد «حي» إطلاقاً. كل رقم قبلي،")
        print("   ويجب أن نسمّيه كذلك: «نمط أسبوعي نموذجي»، لا «الآن».")
    else:
        print("⇒ «الآن» يختلف عن نفس الساعة صراحةً — قد توجد حالة حية.")
        print("   (يستحق فحصاً أعمق: قد تكون ضوضاء، أو حالة فعلية.)")

    # هل اليوم يؤثر داخل نفس الساعة؟
    same_hour = {r["hash"] for l, r in valid[4:] if r}
    if same_hour:
        print()
        print(f"بصمات نفس الساعة في أيام مختلفة: {len(same_hour)}")
        if len(same_hour) == 1:
            print("⇒ الساعة وحدها تحدّد النتيجة — اليوم لا يؤثر هنا.")
        else:
            print("⇒ اليوم يؤثر داخل نفس الساعة (جدول أسبوعي).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
