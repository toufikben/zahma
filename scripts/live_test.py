"""هل يوجد قياس حي فعلاً، أم أن Mapbox يقدّم «أسبوعاً نموذجياً» فقط؟

**الاكتشاف الذي فرض هذا السكربت:** جمعنا 7 أيام عبر `depart_at`. النتيجة:
كل يوم اثنين مطابق تماماً لكل يوم اثنين آخر (فرق 0.00 كم/س)، وكل ثلاثاء
مطابق لكل ثلاثاء (0.00). أي أن `depart_at` لا يعطي تنبؤاً — يعطي **نمطاً
أسبوعياً نموذجياً** ثابتاً يعيد نفسه.

هذا يعني أن «دقة 0.1%» التي قِسناها كانت تسرّباً كاملاً: النموذج تدرّب
على نفس القيم التي قِيس عليها، لأن كل يوم ثلاثاء هو نفس البيانات.

السؤال الحاسم للمنتج: هل يوجد **قياس حي** يمكن تمييزه عن النمط؟
إذا لا، فنحن لا نبيع تنبؤاً — نبيع إعادة بيع نمط Mapbox، وهذا ليس دفاعاً
تنافسياً ولا يستحق اشتراكاً.

الطريقة: نطلب نفس المسار مرتين — مرة بلا `depart_at` (يعني «الآن»)،
ومرة بـ`depart_at` للساعة الحالية بالضبط. إن كانا متطابقين، فلا قياس حي.
ثم نكرّر بعد دقائق: إن تغيّر الأول وبقي الثاني ثابتاً، فالقياس الحي موجود.

التشغيل: python scripts/live_test.py
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from zahma.config import get_settings

ALGIERS = ZoneInfo("Africa/Algiers")
BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"

# ثلاثة محاور حقيقية في العاصمة — باب الزوار، الحراش، زرالدة.
PAIRS = [
    ("BabaZouar->Centre", (3.1833, 36.7167), (3.0589, 36.7705)),
    ("ElHarrach->Centre", (3.1400, 36.7200), (3.0589, 36.7705)),
    ("Zeralda->Centre", (2.8400, 36.7100), (3.0589, 36.7705)),
]


def fetch(client: httpx.Client, token: str, a, b, depart_at: str | None) -> dict:
    params = {
        "access_token": token,
        "overview": "false",
        "annotations": "duration",
    }
    if depart_at:
        params["depart_at"] = depart_at
    r = client.get(
        f"{BASE}/{a[0]},{a[1]};{b[0]},{b[1]}", params=params
    )
    r.raise_for_status()
    route = r.json()["routes"][0]
    return {
        "duration": route["duration"],
        "duration_typical": route.get("duration_typical"),
        "distance": route["distance"],
    }


def main() -> int:
    s = get_settings()
    if not s.has_mapbox:
        print("MAPBOX_TOKEN missing")
        return 1

    now = datetime.now(ALGIERS)
    hour_stamp = now.strftime("%Y-%m-%dT%H:00")
    print(f"الآن (الجزائر): {now:%Y-%m-%d %H:%M} {now:%a}")
    print(f"depart_at المستخدم للمقارنة: {hour_stamp}\n")

    print(f"{'المحور':<20} {'نمط (depart_at)':>16} {'حي (بلا)':>10} {'فرق':>8}")
    print("─" * 60)

    with httpx.Client(timeout=25.0) as client:
        for name, a, b in PAIRS:
            pattern = fetch(client, s.mapbox_token, a, b, hour_stamp)
            live = fetch(client, s.mapbox_token, a, b, None)
            d_pat = pattern["duration"]
            d_live = live["duration"]
            diff_pct = (d_live - d_pat) / d_pat * 100
            print(
                f"{name:<20} {d_pat:>14.0f}s {d_live:>9.0f}s {diff_pct:>+7.1f}%"
            )
            time.sleep(0.4)

    print("\n── انتظار 60 ثانية ثم إعادة القياس (هل يتغيّر الحي؟)")
    time.sleep(60)

    with httpx.Client(timeout=25.0) as client:
        for name, a, b in PAIRS:
            pattern = fetch(client, s.mapbox_token, a, b, hour_stamp)
            live = fetch(client, s.mapbox_token, a, b, None)
            print(
                f"{name:<20} نمط {pattern['duration']:>7.0f}s  "
                f"حي {live['duration']:>7.0f}s  "
                f"typical={live.get('duration_typical')}"
            )
            time.sleep(0.4)

    print(
        "\nتفسير: إن تساوى «حي» و«نمط» في القياسين، فلا قياس حي — "
        "Mapbox يعيد أسبوعاً نموذجياً فقط للجزائر."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
