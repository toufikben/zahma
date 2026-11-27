"""تحقيق: هل الجدول ثابت حقاً، أم أن القياسات تختلف بين نفس يوم الأسبوع؟

**لماذا هذا الملف:** ادّعينا «الفائت يُملأ» بناءً على أن `depart_at`
يعيد نفس الرقم بعد سنة. لكن استعلاماً على القاعدة كشف استثناءات:

    segment 47490، الأحد 23:00
      2026-11-29 → 9.92 كم/س
      2026-12-06 → 33.82 كم/س     ← فرق 23.9

لو كان هذا حقيقياً فالادعاء خاطئ: الجدول يتغير، والملء يعيد شيئاً
مختلفاً، والخادم 24/7 يعود ضرورة.

**السؤال الدقيق:** هل الاختلاف في *الجدول* أم في *ما قسناه*؟ الفرق
حاسم: الأول يعني أن المصدر يتغير، والثاني يعني أن طريقة قياسنا هي
المتغيرة.
"""

from __future__ import annotations

import httpx

from zahma.config import get_settings

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"
# pair 15: من 36.74,3.10 إلى 36.71,2.84 — يمر بشارع حسيبة بن بوعلي
COORDS = "3.1,36.74;2.84,36.71"


def fetch(depart_at: str) -> dict | None:
    s = get_settings()
    r = httpx.get(
        f"{BASE}/{COORDS}",
        params={
            "access_token": s.mapbox_token,
            "annotations": "speed,duration",
            "overview": "false",
            "depart_at": depart_at,
        },
        timeout=30,
    )
    if r.status_code >= 400:
        return {"error": f"HTTP {r.status_code}", "body": r.text[:120]}
    rt = r.json()["routes"][0]
    return {"duration": rt["duration"], "distance": rt["distance"]}


def main() -> int:
    print("pair 15 — نفس الزوج، نفس الساعة 23:00، تواريخ مختلفة")
    print()
    results = {}
    for d in (
        "2026-11-15T23:00",
        "2026-11-22T23:00",
        "2026-11-29T23:00",
        "2026-12-06T23:00",
        "2026-12-13T23:00",
        "2027-01-03T23:00",
    ):
        r = fetch(d)
        results[d] = r
        if r and "error" in r:
            print(f"  {d}  {r['error']}")
        elif r:
            print(f"  {d}  dur={r['duration']:.1f}s  dist={r['distance']:.0f}m")
    print()

    durs = [r["duration"] for r in results.values() if r and "duration" in r]
    if durs:
        print(f"المدى: {max(durs) - min(durs):.1f} ثانية على {len(durs)} تواريخ")
        if max(durs) - min(durs) < 1.0:
            print("⇒ الجدول ثابت تماماً. الاختلاف في القاعدة كان في قياسنا لا في المصدر.")
        else:
            print("⇒ الجدول يتغير فعلاً. الادعاء بحاجة تصحيح.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
