"""اختبار TomTom بنقاط على الطرق فعلياً — مأخوذة من شبكتنا.

الفشل السابق: «Point too far from nearest existing segment» لكل النقاط
الثلاث. السبب ليس أن TomTom لا يغطّي الجزائر، بل أن النقاط التي اخترتها
(مراكز أحياء) تبعد مئات الأمتار عن أي طريق في قاعدة TomTom.

الحل: نسأل شبكتنا عن إحداثيات **منتصف** مقاطع motorway/trunk/primary
الحقيقية، ونستخدمها. هذه نقاط على الأسفلت بالضبط.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from zahma.config import get_settings
from zahma.db import session_scope

ALGIERS = ZoneInfo("Africa/Algiers")
FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"


def pick_points(n: int = 6) -> list[tuple[str, float, float]]:
    """منتصف مقاطع رئيسية حقيقية من شبكتنا — نقاط على الأسفلت."""
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT name, road_class,
                       ST_Y(ST_LineInterpolatePoint(geom, 0.5)) AS lat,
                       ST_X(ST_LineInterpolatePoint(geom, 0.5)) AS lon
                FROM segments
                WHERE road_class IN ('motorway', 'trunk', 'primary')
                  AND length_m > 400
                  AND name IS NOT NULL
                ORDER BY length_m DESC
                LIMIT :n
                """
            ),
            {"n": n},
        ).all()
    return [(r[0][:24], float(r[2]), float(r[3])) for r in rows]


def fetch(client, key, lat, lon):
    try:
        r = client.get(
            FLOW_URL,
            params={"key": key, "point": f"{lat},{lon}", "unit": "KMPH"},
        )
    except httpx.HTTPError as e:
        return {"error": f"net: {e}"}
    if r.status_code >= 400:
        return {"error": f"HTTP {r.status_code}: {r.text[:120]}"}
    d = r.json().get("flowSegmentData") or {}
    return {
        "current": d.get("currentSpeed"),
        "free": d.get("freeFlowSpeed"),
        "confidence": d.get("confidence"),
        "frc": d.get("frc"),
        "closure": d.get("roadClosure"),
    }


def main() -> int:
    s = get_settings()
    if not getattr(s, "tomtom_key", ""):
        print("TOMTOM_KEY missing")
        return 1

    pts = pick_points(6)
    print(f"الآن: {datetime.now(ALGIERS):%Y-%m-%d %H:%M:%S %a}")
    print(f"نقاط على مقاطع حقيقية: {len(pts)}\n")

    for name, lat, lon in pts:
        print(f"   {name:<24} {lat:.5f},{lon:.5f}")

    print("\n── جولة 1")
    r1 = {}
    with httpx.Client(timeout=20.0) as client:
        for name, lat, lon in pts:
            res = fetch(client, s.tomtom_key, lat, lon)
            r1[name] = res
            if "error" in res:
                print(f"   {name:<24} ✗ {res['error'][:100]}")
            else:
                print(
                    f"   {name:<24} حالي {res['current']:>5} كم/س  "
                    f"حر {res['free']:>5}  ثقة {res['confidence']}  frc {res['frc']}"
                )
            time.sleep(1.2)

    ok = [n for n, v in r1.items() if "error" not in v]
    if not ok:
        print("\n✗ لا نقطة نجحت — TomTom لا يغطّي هذه النقاط")
        return 1

    print(f"\n✓ {len(ok)}/{len(pts)} نقطة نجحت — تغطية موجودة")
    print("\n── انتظار 90 ثانية ثم إعادة القياس (هل يتغيّر؟)")
    time.sleep(90)

    print("\n── جولة 2")
    changed = 0
    with httpx.Client(timeout=20.0) as client:
        for name in ok:
            res = fetch(client, s.tomtom_key, r1[name]["free"] and pts[[p[0] for p in pts].index(name)][1], pts[[p[0] for p in pts].index(name)][2])
            if "error" in res:
                print(f"   {name:<24} ✗ {res['error'][:80]}")
                continue
            a = r1[name]["current"]
            b = res["current"]
            d = b - a
            if abs(d) >= 2:
                changed += 1
            print(
                f"   {name:<24} {a:>5} → {b:>5} كم/س  "
                f"({d:+5.0f})  {'متغيّر' if abs(d) >= 2 else 'ثابت'}"
            )
            time.sleep(1.2)

    print()
    if changed:
        print(f"✓ {changed} مقطعاً تغيّر فعلياً — TomTom يملك حركة حية")
        return 0
    print("! كل المقاطع ثابتة — يرجّح جدولاً نموذجياً أيضاً (يحتاج تحققاً بيومين)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
