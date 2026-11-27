"""هل اختلاف المقطع بين تاريخين سببه المصدر أم إسقاطنا؟

**المعطيات:**
- المسار pair=15 عند 23:00: `duration` ثابت 1632.8 ثانية على 6 تواريخ.
- لكن المقطع 47490 (12.9 م، secondary) أعطى 9.92 في 2026-11-29 و33.82
  في 2026-12-06 — نفس يوم الأسبوع، نفس الساعة.

**الفرضيتان:**
1. المصدر يتغير ⇒ ادعاء «الفائت يُملأ» خاطئ.
2. إسقاطنا يتغير (هندسة مختلفة ⇒ حافة مختلفة تُنسب للمقطع) ⇒ المصدر
   ثابت، والعيب عندنا.

هذا السكربت يميّز بينهما: يجلب الاستجابة كاملة ويقارن عدد الحواف
وإحصاءات السرعة، لا `duration` فقط.
"""

from __future__ import annotations

import httpx

from zahma.config import get_settings

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"
COORDS = "3.1,36.74;2.84,36.71"


def probe(depart_at: str) -> dict:
    s = get_settings()
    r = httpx.get(
        f"{BASE}/{COORDS}",
        params={
            "access_token": s.mapbox_token,
            "annotations": "speed,duration,distance",
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
            "depart_at": depart_at,
        },
        timeout=30,
    )
    r.raise_for_status()
    route = r.json()["routes"][0]
    ann = route["legs"][0]["annotation"]
    coords = route["geometry"]["coordinates"]
    speeds = ann.get("speed") or []
    durs = ann.get("duration") or []
    dists = ann.get("distance") or []
    return {
        "duration": route["duration"],
        "distance": route["distance"],
        "n_coords": len(coords),
        "n_edges": len(durs),
        "sum_dur": sum(durs),
        "sum_dist": sum(dists),
        "sum_speed": sum(speeds),
        "first_coord": tuple(round(c, 6) for c in coords[0]),
        "mid_coord": tuple(round(c, 6) for c in coords[len(coords) // 2]),
        "speeds_hash": hash(tuple(round(s, 4) for s in speeds)),
    }


def main() -> int:
    a = probe("2026-11-29T23:00")
    b = probe("2026-12-06T23:00")

    print(f"{'':22} {'2026-11-29':>14} {'2026-12-06':>14}  same?")
    for k in (
        "duration", "distance", "n_coords", "n_edges",
        "sum_dur", "sum_dist", "sum_speed", "first_coord", "mid_coord",
        "speeds_hash",
    ):
        va, vb = a[k], b[k]
        same = "YES" if va == vb else "NO"
        print(f"{k:22} {str(va):>14} {str(vb):>14}  {same}")
    print()
    if a["speeds_hash"] != b["speeds_hash"]:
        print("⇒ توزيع السرعات على الحواف يختلف بين التاريخين.")
        print("  إن كان duration متساوياً، فالمصدر يعيد نفس المجموع بتوزيع مختلف")
        print("  ⇒ الإسقاط على مقطع بعينه غير مستقر، لا الجدول.")
    else:
        print("⇒ السرعات متطابقة حرفياً. الاختلاف في القاعدة إذن من كود الإسقاط/التخزين.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
