"""اختيار المحاور وأزواج الانطلاق/الوصول — بلا API.

هذه الخطوة تحلّ محل الفكرة القديمة «اختر 3 طرق يدوياً».
نستخرج المحاور من الأهمية البنيوية، ثم نبني أزواج O-D تغطي المدينة.

المخرجات:
    data/processed/corridors.json    — أفضل 20 محوراً
    data/processed/od_pairs.json     — ~200 زوج انطلاق/وصول
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from zahma.config import ALGIERS_BBOX, DATA_PROCESSED

# نقاط جذب رئيسية في العاصمة — تُخدم كأطراف لأزواج O-D.
# مختارة يدوياً من التخطيط الحضري (جامعات، أسواق، محطات، أحياء كبرى).
HUBS = [
    # الاسم، lat، lon، وزن
    ("وسط العاصمة - ساحة أودان", 36.7705, 3.0589, 1.0),
    ("باب الزوار", 36.7167, 3.1833, 0.9),
    ("الحراش", 36.7200, 3.1400, 0.9),
    ("بئر مراد رايس", 36.7500, 3.0500, 0.8),
    ("حسين داي", 36.7400, 3.1000, 0.85),
    ("باب الوادي", 36.7900, 3.0500, 0.8),
    ("القبة", 36.7900, 3.0700, 0.75),
    ("بوروبة", 36.7900, 3.1100, 0.7),
    ("برج الكيفان", 36.7500, 3.2000, 0.75),
    ("الدار البيضاء", 36.7300, 3.2100, 0.7),
    ("عين النعجة", 36.7700, 3.2000, 0.6),
    ("الرويبة", 36.7300, 3.2800, 0.65),
    ("الرغاية", 36.7300, 3.3400, 0.6),
    ("براقي", 36.7100, 3.1300, 0.7),
    ("سيدي امحمد", 36.7600, 3.0500, 0.8),
    ("الأبيار", 36.7700, 3.0300, 0.75),
    ("بئر خادم", 36.7100, 3.0300, 0.65),
    ("بن عكنون", 36.7800, 3.0100, 0.6),
    ("دالي إبراهيم", 36.7500, 2.9800, 0.65),
    ("زرالدة", 36.7100, 2.8400, 0.6),
    ("سطاوالي", 36.7600, 2.8900, 0.55),
    ("سيدي فرج", 36.7900, 2.8700, 0.5),
    ("الشراقة", 36.7700, 2.9500, 0.6),
    ("عين البنيان", 36.8000, 2.9200, 0.5),
    ("جامعة هواري بومدين (USTHB)", 36.7130, 3.1650, 0.85),
    ("مطار هواري بومدين", 36.6910, 3.2150, 0.7),
    ("ميناء الجزائر", 36.7800, 3.0700, 0.7),
    ("أولاد فايت", 36.7400, 2.9600, 0.6),
    ("بئر توتة", 36.6900, 3.0200, 0.5),
    ("السواقي", 36.7300, 3.1500, 0.5),
]


def pick_corridors(segments: gpd.GeoDataFrame, n: int = 20) -> list[dict]:
    """يختار المحاور الأعلى أهمية — موزّعة على أصناف الطرق.

    لماذا التوزيع لا الترتيب المطلق:
    بينما الطرق السريعة تحصل على أعلى betweenness دائماً، الزحمة اليومية
    التي تهم السائق تحدث على الشريانية الحضرية (primary/secondary).
    لو أخذنا أعلى 20 مطلقاً، لكانت كلها motorway — ولما قسنا وسط المدينة.

    التوزيع: 8 motorway/trunk + 8 primary + 4 secondary = 20.
    """
    pool = segments
    if "measurable" in pool.columns:
        pool = pool[pool["measurable"]]
    if "in_main" in pool.columns:
        pool = pool[pool["in_main"]]

    named = pool[pool["name"].notna()].copy()

    def _groups(sub: pd.DataFrame) -> pd.DataFrame:
        if sub.empty:
            return pd.DataFrame()
        g = (
            sub.groupby(["name", "road_class"])
            .agg(
                seg_count=("seg_id", "size"),
                total_km=("length_m", lambda s: round(s.sum() / 1000, 2)),
                mean_importance=("importance", "mean"),
                max_importance=("importance", "max"),
                mean_betweenness=("betweenness", "mean"),
            )
            .reset_index()
        )
        return g[g["seg_count"] >= 3]

    plan = [
        (["motorway", "trunk"], 8),
        (["primary"], 8),
        (["secondary"], 4),
    ]

    chosen: list[pd.Series] = []
    used_names: set[str] = set()
    for classes, quota in plan:
        g = _groups(named[named["road_class"].isin(classes)])
        if g.empty:
            continue
        g = g.sort_values("max_importance", ascending=False)
        taken = 0
        for r in g.itertuples():
            if taken >= quota:
                break
            if r.name in used_names:
                continue
            used_names.add(r.name)
            chosen.append(r)
            taken += 1

    out = []
    for i, r in enumerate(chosen, 1):
        subs = named[(named["name"] == r.name) & (named["road_class"] == r.road_class)]
        c = subs.geometry.union_all().centroid
        out.append(
            {
                "corridor_id": i,
                "name": r.name,
                "road_class": r.road_class,
                "seg_count": int(r.seg_count),
                "total_km": float(r.total_km),
                "importance": round(float(r.max_importance), 4),
                "betweenness": round(float(r.mean_betweenness), 4),
                "centroid_lat": round(c.y, 5),
                "centroid_lon": round(c.x, 5),
                "seg_ids": [int(x) for x in subs["seg_id"].tolist()],
            }
        )
    return out


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_od_pairs(max_pairs: int = 200, min_km: float = 5.0, max_km: float = 30.0) -> list[dict]:
    """يبني أزواج انطلاق/وصول مغطية للمدينة.

    الاستراتيجية:
    1. كل زوج بين نقاط الجذب (30 نقطة) مع مسافة معقولة.
    2. ترتيب حسب الوزن المركب (أهمية الطرفين).
    3. اختيار موزّع جغرافياً حتى لا تتركز كل الأزواج في الوسط.

    الحد الأقصى 30 كم يعكس واقع العاصمة: أبعد رحلة يومية نموذجية.
    """
    cands = []
    for i, (n1, la1, lo1, w1) in enumerate(HUBS):
        for j, (n2, la2, lo2, w2) in enumerate(HUBS):
            if j <= i:
                continue
            d = _haversine_km(la1, lo1, la2, lo2)
            if d < min_km or d > max_km:
                continue
            cands.append(
                {
                    "from_name": n1,
                    "from_lat": la1,
                    "from_lon": lo1,
                    "to_name": n2,
                    "to_lat": la2,
                    "to_lon": lo2,
                    "crow_km": round(d, 2),
                    "weight": round((w1 + w2) / 2 * (1 + d / max_km), 4),
                }
            )

    df = pd.DataFrame(cands).sort_values("weight", ascending=False).reset_index(drop=True)

    # توزيع: لا نأخذ كل شيء من الوسط. نأخذ الأفضل ثم نضيف تنويعاً.
    picked, seen_pairs, per_hub = [], set(), {}
    for r in df.itertuples():
        if len(picked) >= max_pairs:
            break
        key = tuple(sorted([r.from_name, r.to_name]))
        if key in seen_pairs:
            continue
        # سقف 18 زوجاً لكل نقطة حتى لا تهيمن نقطة واحدة
        if per_hub.get(r.from_name, 0) >= 18 or per_hub.get(r.to_name, 0) >= 18:
            continue
        seen_pairs.add(key)
        per_hub[r.from_name] = per_hub.get(r.from_name, 0) + 1
        per_hub[r.to_name] = per_hub.get(r.to_name, 0) + 1
        picked.append(
            {
                "pair_id": len(picked) + 1,
                "from_name": r.from_name,
                "from": [r.from_lat, r.from_lon],
                "to_name": r.to_name,
                "to": [r.to_lat, r.to_lon],
                "crow_km": r.crow_km,
                "weight": float(r.weight),
            }
        )

    return picked


def run() -> dict:
    seg_path = DATA_PROCESSED / "segments.parquet"
    if not seg_path.exists():
        raise FileNotFoundError(f"Run build first: {seg_path}")

    segments = gpd.read_parquet(seg_path)
    corridors = pick_corridors(segments)
    pairs = build_od_pairs()

    (DATA_PROCESSED / "corridors.json").write_text(
        json.dumps(corridors, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DATA_PROCESSED / "od_pairs.json").write_text(
        json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[corridors] {len(corridors)} corridors")
    for c in corridors[:8]:
        print(f"  {c['corridor_id']:>2}. {c['name'][:42]:<42} {c['road_class']:<10} "
              f"{c['total_km']:>6.1f} km  imp={c['importance']}")

    print(f"\n[od] {len(pairs)} pairs")
    for p in pairs[:5]:
        print(f"  {p['from_name'][:28]:<28} -> {p['to_name'][:28]:<28} {p['crow_km']} km")

    return {"corridors": corridors, "pairs": pairs}


if __name__ == "__main__":
    run()
