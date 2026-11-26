"""استخراج الشبكة من PBF — يحفظ العقد والحواف بمعرّفات OSM الحقيقية.

لماذا هذا منفصل عن build:
قراءة PBF تستغرق ~3 دقائق. نفصلها مرة واحدة، ونحفظ:
- nodes.parquet : id, lon, lat
- edges.parquet : u, v, geometry, maxspeed, highway, ...

الاعتماد على معرّفات u/v (لا على إحداثيات مقرّبة) هو ما يجعل الشبكة
متصلة. هذا الفرق بين رسم بـ2413 قطعة ورسم واحد.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyrosm

from zahma.config import ALGIERS_BBOX, DATA_PROCESSED, DATA_RAW

PBF = DATA_RAW / "algeria-latest.osm.pbf"
BBOX = [ALGIERS_BBOX[1], ALGIERS_BBOX[0], ALGIERS_BBOX[3], ALGIERS_BBOX[2]]

NODES_OUT = DATA_PROCESSED / "osm_nodes.parquet"
EDGES_OUT = DATA_PROCESSED / "osm_edges.parquet"


def extract(force: bool = False) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    if NODES_OUT.exists() and EDGES_OUT.exists() and not force:
        print("[extract] using cached nodes/edges")
        return pd.read_parquet(NODES_OUT), gpd.read_parquet(EDGES_OUT)

    if not PBF.exists():
        raise FileNotFoundError(PBF)

    print(f"[extract] reading {PBF.name} (~3 min) ...", flush=True)
    osm = pyrosm.OSM(str(PBF), bounding_box=BBOX)
    nodes, edges = osm.get_network(network_type="driving", nodes=True)
    if nodes is None or edges is None:
        raise RuntimeError("pyrosm returned no network")

    print(f"[extract] nodes={len(nodes):,} edges={len(edges):,}", flush=True)

    nodes_out = nodes[["id", "lon", "lat"]].copy()
    keep = [
        "u", "v", "highway", "name", "maxspeed", "oneway", "lanes",
        "access", "motor_vehicle", "vehicle", "bridge", "tunnel",
        "geometry", "length",
    ]
    cols = [c for c in keep if c in edges.columns]
    edges_out = edges[cols].copy()

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    nodes_out.to_parquet(NODES_OUT)
    edges_out.to_parquet(EDGES_OUT)
    print(f"[extract] wrote {NODES_OUT.name}, {EDGES_OUT.name}", flush=True)
    return nodes_out, edges_out


if __name__ == "__main__":
    extract(force="--force" in sys.argv)
