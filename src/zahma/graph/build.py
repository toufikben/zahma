"""بناء شبكة المقاطع من OSM — بمعرّفات العقد الحقيقية.

القرار المعماري الأهم في هذا الملف:
نعتمد على `u` و `v` (معرّفات عقد OSM) لربط الحواف، لا على تقريب
الإحداثيات. التقريب كان يُنتج 2413 مكوّناً منفصلاً لأن نقطتي
التقاء لا تتطابقان دائماً بعد التقريب.

بمعرّفات العقد، الشبكة متصلة كما هي في الواقع — وهذا شرط لأي توجيه.

المخرجات:
    data/processed/segments.parquet  — المقاطع (مع u/v/geom/importance)
    data/processed/network_summary.json
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString

from zahma.config import DATA_PROCESSED
from zahma.graph.extract import extract

ROAD_CLASSES = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link", "tertiary",
    "tertiary_link", "residential", "unclassified", "living_street",
    "service",
}

# الطرق التي نقيسها فعلياً — الشريانية وما فوق.
# الشوارع المحلية موجودة في الشبكة للترابط والتوجيه فقط.
MEASURABLE = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
}

CLASS_WEIGHT = {
    "motorway": 1.0, "trunk": 0.9, "primary": 0.75,
    "secondary": 0.5, "tertiary": 0.3,
    "residential": 0.08, "unclassified": 0.06,
    "living_street": 0.04, "service": 0.02,
}

DEFAULT_SPEED = {
    "motorway": 110, "trunk": 90, "primary": 60, "secondary": 50,
    "tertiary": 40, "residential": 30, "unclassified": 30,
    "living_street": 20, "service": 20,
}


def _first(v):
    if isinstance(v, (list, tuple, np.ndarray)):
        return v[0] if len(v) else None
    return v


def _clean(hw: str) -> str:
    return str(hw).replace("_link", "")


def _parse_speed(v) -> float | None:
    v = _first(v)
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("none", "signals", "walk", "nan", ""):
        return None
    digits = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    if not digits:
        return None
    try:
        val = float(digits)
    except ValueError:
        return None
    if "mph" in s:
        val *= 1.60934
    return val if 5 <= val <= 160 else None


def _line(g):
    if isinstance(g, LineString):
        return g
    if isinstance(g, MultiLineString):
        parts = sorted(g.geoms, key=lambda x: x.length, reverse=True)
        return parts[0] if parts else None
    return None


def build_segments() -> gpd.GeoDataFrame:
    nodes, edges = extract()
    print(f"[build] nodes={len(nodes):,} edges={len(edges):,}")

    e = edges.copy()
    e["highway"] = e["highway"].apply(_first)
    e = e[e["highway"].notna()].copy()
    e["road_class"] = e["highway"].apply(_clean)
    e = e[e["road_class"].isin(ROAD_CLASSES)].copy()

    for col in ("access", "motor_vehicle", "vehicle"):
        if col in e.columns:
            bad = e[col].apply(_first).isin(["no", "private"])
            e = e[~bad].copy()

    e["geometry"] = e["geometry"].apply(_line)
    e = e[e["geometry"].notna()].copy()

    # الطول: من pyrosm إن وُجد، وإلا حساب هندسي
    e_m = e.to_crs(32631)
    e["length_m"] = e_m.geometry.length.round(1)

    # لا نحذف المقاطع القصيرة.
    # السبب: وصلات التقاطع (junction connectors) طولها 1–5 متر، وهي التي
    # تربط الطرق ببعضها. حذفها كان يفتّت الشبكة إلى 38% متصلة فقط.
    # بعد الإبقاء عليها: 99% متصلة. لا توجد مقاطع بطول صفر فعلياً.
    e = e[e["length_m"] > 0.1].copy()

    e["speed_free_kmh"] = e.apply(
        lambda r: _parse_speed(r.get("maxspeed"))
        or DEFAULT_SPEED.get(r["road_class"], 40),
        axis=1,
    )
    e["travel_time_free_s"] = (e["length_m"] / (e["speed_free_kmh"] / 3.6)).round(1)

    e["u"] = e["u"].astype("int64")
    e["v"] = e["v"].astype("int64")

    # الاتجاه: pyrosm يُخرج كل طريق مرة واحدة. `oneway` تخبرنا إن كان
    # مسموحاً بالسير في الاتجاه المعاكس أيضاً. نطبّع إلى:
    #   yes  => اتجاه واحد فقط (u→v)
    #   -1   => اتجاه واحد معاكس (v→u)
    #   no/None => اتجاهان
    if "oneway" in e.columns:
        ow = e["oneway"].apply(_first)
        ow = ow.where(ow.notna(), "no").astype(str).str.lower().str.strip()
        ow = ow.replace({"nan": "no", "none": "no", "false": "no", "": "no", "true": "yes"})
        e["oneway"] = ow
    else:
        e["oneway"] = "no"

    # ترقيم ثابت ومرتّب (حتى تبقى المعرّفات مستقرة بين التشغيلات)
    e = e.sort_values(["u", "v", "road_class"]).reset_index(drop=True)
    e["seg_id"] = np.arange(1, len(e) + 1)

    keep = [
        "seg_id", "u", "v", "name", "road_class", "length_m",
        "speed_free_kmh", "travel_time_free_s", "oneway", "geometry",
    ]
    out = e[[c for c in keep if c in e.columns]].copy()
    out["measurable"] = out["road_class"].isin(MEASURABLE)
    print(
        f"[build] {len(out):,} segments, {out['length_m'].sum()/1000:.1f} km "
        f"({int(out['measurable'].sum()):,} measurable)"
    )
    return gpd.GeoDataFrame(out, crs="EPSG:4326")


def structural_importance(gdf: gpd.GeoDataFrame, k: int = 300) -> pd.Series:
    """Betweenness على رسم العقد الحقيقية — متصل، فالأرقام ذات معنى."""
    G = nx.Graph()
    for r in gdf.itertuples():
        G.add_edge(int(r.u), int(r.v), weight=max(r.travel_time_free_s, 1.0))

    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    print(
        f"[build] graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges, "
        f"{len(comps)} components, largest {len(comps[0])/G.number_of_nodes()*100:.1f}%"
    )

    print(f"[build] betweenness (k={k}) ...")
    bc = nx.betweenness_centrality(G, k=min(k, G.number_of_nodes()), weight="weight", seed=42)

    vals = np.array([(bc.get(int(r.u), 0.0) + bc.get(int(r.v), 0.0)) / 2.0 for r in gdf.itertuples()])
    mx = vals.max() if len(vals) else 0.0
    return pd.Series(vals / mx if mx > 0 else vals, index=gdf.index, name="betweenness")


def build(out_dir: Path = DATA_PROCESSED) -> gpd.GeoDataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    gdf = build_segments()

    gdf["betweenness"] = structural_importance(gdf)
    gdf["class_weight"] = gdf["road_class"].map(CLASS_WEIGHT).fillna(0.2)
    gdf["importance"] = (
        gdf["betweenness"] * 0.6 + gdf["class_weight"] * 0.4
    ) * np.log1p(gdf["length_m"] / 100.0)
    gdf["importance"] = gdf["importance"] / gdf["importance"].max()

    # المكوّن المتصل الأكبر — التوجيه يعمل داخله فقط.
    # الجزر المعزولة (ضواحٍ مقطوعة بحدود النطاق) تُعلَّم لاستبعادها.
    G = nx.Graph()
    for r in gdf.itertuples():
        G.add_edge(int(r.u), int(r.v))
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    main = comps[0]
    gdf["in_main"] = [int(u) in main and int(v) in main for u, v in zip(gdf["u"], gdf["v"], strict=False)]
    print(f"[build] main component: {len(main):,} nodes, {int(gdf['in_main'].sum()):,} segments")

    gdf = gdf.sort_values("importance", ascending=False).reset_index(drop=True)
    gdf["rank"] = np.arange(1, len(gdf) + 1)
    gdf = gdf.set_index("seg_id", drop=False)

    gdf.to_parquet(out_dir / "segments.parquet")

    summary = {
        "segments": int(len(gdf)),
        "measurable": int(gdf["measurable"].sum()),
        "in_main_component": int(gdf["in_main"].sum()),
        "total_km": round(float(gdf["length_m"].sum() / 1000), 1),
        "by_class": {k: int(v) for k, v in gdf["road_class"].value_counts().items()},
        "top15": [
            {
                "seg_id": int(r.seg_id),
                "name": r.name if isinstance(r.name, str) else "",
                "road_class": r.road_class,
                "importance": round(float(r.importance), 4),
                "length_m": float(r.length_m),
                "betweenness": round(float(r.betweenness), 4),
            }
            for r in gdf.head(15).itertuples()
        ],
    }
    (out_dir / "network_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[build] wrote {len(gdf):,} segments")
    return gdf


if __name__ == "__main__":
    build()
