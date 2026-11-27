"""هل يوجد ما يُجمع ليلاً؟ اختبار لا افتراض.

**السؤال:** المستخدم قال إن الزحمة بعد منتصف الليل نادرة في الجزائر إلا
رمضان والمواسم. فهل نجمع ليلاً أم نوقف الجمع؟

**لكن السؤال الأول ليس «هل الزحمة موجودة» بل «هل المصدر يعطي رقماً
مختلفاً ليلاً أصلاً».** لو أعطى Mapbox نفس الرقم لساعة 03:00 و08:00،
فلا فائدة من جمع الليل — لا لأن الليل هادئ، بل لأن المصدر لا يعرف.

**الاختبار:** نسأل 4 ساعات ليلية (23:00، 01:00، 03:00، 04:30) على نفس
20 زوجاً، ونقارن بساعات النهار المعروفة. القياس هنا **مباشر من API**،
لا من قاعدة بياناتنا — لأن قاعدتنا لا تحتوي ليلاً بعد.

**ما نبحث عنه:**
- سرعة أعلى بكثير ليلاً ⇒ المصدر يميّز الليل فعلاً، والجمع الليلي مفيد.
- سرعة مساوية للنهار ⇒ المصدر يوزّع نفس الجدول، والجمع الليلي بلا قيمة.

التشغيل: python scripts/night_probe.py
"""

from __future__ import annotations

import time

import httpx
from sqlalchemy import text

from zahma.config import get_settings
from zahma.db import session_scope

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"

# ساعات ليلية مفصّلة + مرجعان نهاريان
HOURS = [
    ("21:00", "مساء"),
    ("22:30", "ليل"),
    ("23:59", "ليل"),
    ("01:00", "ليل"),
    ("02:00", "ليل"),
    ("03:00", "ليل"),
    ("04:00", "ليل"),
    ("05:00", "فجر"),
    ("06:00", "فجر"),
    ("08:00", "نهار"),
    ("17:00", "نهار"),
]

DAY = "2026-12-02"  # يوم عمل، متاح للتحقق من قاعدتنا


def load_pairs(limit: int = 20) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT pair_id,
                       ST_Y(from_pt) flat, ST_X(from_pt) flon,
                       ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                FROM od_pairs WHERE active
                ORDER BY weight DESC LIMIT :n
                """
            ),
            {"n": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def probe(client: httpx.Client, token: str, pair: dict, depart: str) -> dict | None:
    """مدة الرحلة من Directions مع annotation للسرعات."""
    coords = f"{pair['flon']},{pair['flat']};{pair['tlon']},{pair['tlat']}"
    try:
        r = client.get(
            f"{BASE}/{coords}",
            params={
                "access_token": token,
                "depart_at": depart,
                "annotations": "speed,duration,distance",
                "overview": "false",
            },
        )
    except httpx.HTTPError:
        return None
    if r.status_code >= 400:
        return {"error": r.status_code}
    data = r.json()
    routes = data.get("routes") or []
    if not routes:
        return None
    rt = routes[0]
    # annotation موجود داخل legs[] لا في جذر المسار. كان يُقرأ من الجذر
    # فيرجع قائماً دائماً، فطُبعت السرعة صفراً بينما البيانات موجودة.
    speeds: list[float] = []
    n_edges = 0
    for leg in rt.get("legs") or []:
        ann = leg.get("annotation") or {}
        raw = ann.get("speed") or []
        n_edges += len(raw)
        # وحدات Mapbox: m/s. الصفر يعني «لا بيانات» لا «متوقف».
        speeds.extend(s * 3.6 for s in raw if s is not None and s > 0)
    return {
        "duration_s": float(rt.get("duration", 0)),
        "distance_m": float(rt.get("distance", 0)),
        "n_edges": n_edges,
        "mean_kmh": sum(speeds) / len(speeds) if speeds else None,
    }


def main() -> int:
    s = get_settings()
    if not s.has_mapbox:
        print("MAPBOX_TOKEN missing")
        return 1

    pairs = load_pairs(20)
    print(f"أزواج: {len(pairs)}   اليوم: {DAY}\n")

    results: dict[str, dict] = {}
    with httpx.Client(timeout=25.0) as client:
        for hh, kind in HOURS:
            depart = f"{DAY}T{hh}"
            durs: list[float] = []
            speeds: list[float] = []
            errs = 0
            for p in pairs:
                r = probe(client, s.mapbox_token, p, depart)
                if not r or "error" in r:
                    errs += 1
                    continue
                durs.append(r["duration_s"])
                if r["mean_kmh"]:
                    speeds.append(r["mean_kmh"])
                time.sleep(0.22)

            if not durs:
                print(f"   {hh} {kind}  ✗ كل الطلبات فشلت ({errs})")
                continue
            results[hh] = {
                "kind": kind,
                "dur": sum(durs) / len(durs),
                "spd": sum(speeds) / len(speeds) if speeds else 0.0,
                "n": len(durs),
                "errs": errs,
            }
            print(
                f"   {hh} {kind:<4}  مسارات {len(durs):>2}  "
                f"متوسط المدة {results[hh]['dur']/60:>5.2f} د  "
                f"متوسط السرعة {results[hh]['spd']:>5.1f} كم/س"
            )

    if not results:
        print("\nلا نتائج")
        return 1

    # المقارنة الحاسمة: أسرع ساعة ليلية مقابل ساعة النهار المرجعية
    night = [v for v in results.values() if v["kind"] == "ليل"]
    day = [v for v in results.values() if v["kind"] == "نهار"]

    print("\n── الحكم")
    if night and day:
        n_max = max(v["spd"] for v in night)
        d_min = min(v["spd"] for v in day)
        n_dur = min(v["dur"] for v in night)
        d_dur = max(v["dur"] for v in day)
        print(f"   أسرع ليل: {n_max:.1f} كم/س   أبطأ نهار: {d_min:.1f} كم/س")
        print(f"   أقصر مدة ليل: {n_dur/60:.2f} د   أطول مدة نهار: {d_dur/60:.2f} د")
        gain = (d_dur - n_dur) / d_dur * 100
        print(f"   الليل أسرع بـ {gain:+.1f}% في المدة")

        if gain > 15:
            print("\n   ✓ المصدر يميّز الليل بوضوح — الجمع الليلي يعطي معلومة حقيقية.")
            print("     لكن الفرق نفسه هو سبب كفاية ساعات قليلة ليلاً:")
            print("     المنحنى مسطّح، فلا نحتاج 17 ساعة جمع.")
            return 0
        if gain > 5:
            print("\n   ~ فرق معتدل. جمع ليلي مخفّف (كل 2-3 ساعات) يكفي.")
            return 0
        print("\n   ✗ لا فرق جوهري بين الليل والنهار.")
        print("     المصدر يوزّع نفس الجدول، فالجمع الليلي بلا قيمة.")
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
