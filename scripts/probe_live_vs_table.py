"""هل الجمع «الحي» (بلا `depart_at`) يعطي شيئاً مختلفاً عن الجدول؟

**السؤال الذي يقرّر مصير الجمع المستمر كله:** إن كان الرد بلا `depart_at`
مطابقاً تماماً لرد `depart_at` عند الساعة الحالية، فالجمع كل 30 دقيقة
لا يضيف معلومة واحدة — نكرّر قراءة نفس الجدول.

وإن اختلف، فهناك مكوّن حي حقيقي، والجمع المستمر له قيمة.

**ولماذا هذا أهم سؤال الآن:** كل صفوفنا (761,372) طابعها الزمني مستقبلي،
أي أنها تنبؤات لا قياسات. إن كان الحي = الجدول، فالتطبيق يبيع جدولاً
ثابتاً — وهذا يجب أن يُقال بصراحة لا أن يُسمّى «قياسات حقيقية».
"""

from __future__ import annotations

import httpx

from zahma.config import get_settings

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"
COORDS = "3.1,36.74;2.84,36.71"  # pair 15
COORDS2 = "3.1833,36.7167;3.0589,36.7705"  # باب الزوار ← الوسط


def call(coords: str, depart_at: str | None) -> dict | None:
    s = get_settings()
    params = {
        "access_token": s.mapbox_token,
        "annotations": "speed,duration",
        "overview": "false",
    }
    if depart_at:
        params["depart_at"] = depart_at
    r = httpx.get(f"{BASE}/{coords}", params=params, timeout=30)
    if r.status_code >= 400:
        return {"error": f"HTTP {r.status_code}", "body": r.text[:160]}
    rt = r.json()["routes"][0]
    ann = rt["legs"][0]["annotation"]
    speeds = ann.get("speed") or []
    return {
        "duration": round(rt["duration"], 2),
        "n_edges": len(speeds),
        "speed_sum": round(sum(speeds), 3),
        "speed_hash": hash(tuple(round(v, 4) for v in speeds)),
    }


def main() -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now_local = datetime.now(ZoneInfo("Africa/Algiers"))
    this_hour = now_local.strftime("%Y-%m-%dT%H:00")
    today = now_local.strftime("%Y-%m-%d")

    for label, coords in (("pair 15", COORDS), ("باب الزوار ← الوسط", COORDS2)):
        print(f"══ {label}")
        print(f"   الآن المحلي: {now_local:%Y-%m-%d %H:%M}")

        live = call(coords, None)
        at_now = call(coords, this_hour)
        at_today_0300 = call(coords, f"{today}T03:00")
        at_today_1700 = call(coords, f"{today}T17:00")

        for name, res in (
            ("حي (بلا depart_at)", live),
            (f"depart_at={this_hour}", at_now),
            (f"depart_at={today}T03:00", at_today_0300),
            (f"depart_at={today}T17:00", at_today_1700),
        ):
            if res is None or "error" in res:
                print(f"   {name:28} {res}")
                continue
            print(
                f"   {name:28} dur={res['duration']:>9.2f}  "
                f"edges={res['n_edges']:>4}  hash={res['speed_hash']}"
            )

        if live and "error" not in live and at_now and "error" not in at_now:
            same = live["speed_hash"] == at_now["speed_hash"]
            print()
            if same:
                print("   ⇒ **الحي = الجدول حرفياً.** الجمع المتكرر لا يضيف شيئاً.")
            else:
                print("   ⇒ الحي يختلف عن الجدول. هناك مكوّن حي حقيقي.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
