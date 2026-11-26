"""تحميل الشبكة إلى قاعدة البيانات — من parquet/JSON إلى Postgres.

هذه الخطوة تجعل الشبكة متاحة لكل الطبقات: المجمّع، النموذج، الخادم.
تُنفَّذ مرة واحدة بعد build، وتُعاد عند تحديث OSM.

نحمل **كل** المقاطع (249 ألف) لا الشريانية فقط، لأن التوجيه يحتاج
الشوارع المحلية للترابط. عمود `measurable` يفصل ما نقيسه عما نستخدمه للتوجيه.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from sqlalchemy import text

from zahma.config import DATA_PROCESSED
from zahma.db import session_scope


def _opt_str(v) -> str | None:
    return v if isinstance(v, str) and v.strip() else None


def load_segments(batch: int = 5000) -> int:
    path = DATA_PROCESSED / "segments.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Run 'build-network' first: {path}")

    gdf = gpd.read_parquet(path)
    print(f"[load] {len(gdf):,} segments in parquet")

    rows = []
    for r in gdf.itertuples():
        rows.append(
            {
                "seg_id": int(r.seg_id),
                "u": int(r.u),
                "v": int(r.v),
                "name": _opt_str(getattr(r, "name", None)),
                "road_class": str(r.road_class),
                "length_m": float(r.length_m),
                "speed_free_kmh": float(r.speed_free_kmh),
                "travel_time_free_s": float(r.travel_time_free_s),
                "betweenness": float(getattr(r, "betweenness", 0.0) or 0.0),
                "importance": float(getattr(r, "importance", 0.0) or 0.0),
                "rank": int(getattr(r, "rank", 0) or 0),
                "measurable": bool(getattr(r, "measurable", False)),
                "in_main": bool(getattr(r, "in_main", False)),
                "oneway": _opt_str(getattr(r, "oneway", None)) or "no",
                "geom": r.geometry.wkt,
            }
        )

    sql = text(
        """
        INSERT INTO segments
          (seg_id, u, v, name, road_class, length_m, speed_free_kmh,
           travel_time_free_s, betweenness, importance, rank, measurable, in_main,
           oneway, geom)
        VALUES
          (:seg_id, :u, :v, :name, :road_class, :length_m, :speed_free_kmh,
           :travel_time_free_s, :betweenness, :importance, :rank, :measurable, :in_main,
           :oneway, ST_GeomFromText(CAST(:geom AS text), 4326))
        """
    )

    with session_scope() as s:
        s.execute(text("TRUNCATE segments CASCADE"))
        for i in range(0, len(rows), batch):
            s.execute(sql, rows[i : i + batch])
            print(f"  {min(i + batch, len(rows)):,}/{len(rows):,}", end="\r")
    print(f"\n[load] segments loaded: {len(rows):,}")
    return len(rows)


def load_corridors() -> int:
    path = DATA_PROCESSED / "corridors.json"
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))

    with session_scope() as s:
        s.execute(text("TRUNCATE corridors CASCADE"))
        sql = text(
            """
            INSERT INTO corridors
              (corridor_id, name, road_class, seg_count, total_km, importance,
               betweenness, centroid, seg_ids)
            VALUES
              (:corridor_id, :name, :road_class, :seg_count, :total_km, :importance,
               :betweenness, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :seg_ids)
            """
        )
        for c in data:
            s.execute(
                sql,
                {
                    "corridor_id": c["corridor_id"],
                    "name": c["name"],
                    "road_class": c["road_class"],
                    "seg_count": c["seg_count"],
                    "total_km": c["total_km"],
                    "importance": c["importance"],
                    "betweenness": c["betweenness"],
                    "lon": c["centroid_lon"],
                    "lat": c["centroid_lat"],
                    "seg_ids": c["seg_ids"],
                },
            )
    print(f"[load] corridors loaded: {len(data)}")
    return len(data)


def load_od_pairs() -> int:
    path = DATA_PROCESSED / "od_pairs.json"
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))

    with session_scope() as s:
        s.execute(text("TRUNCATE od_pairs CASCADE"))
        sql = text(
            """
            INSERT INTO od_pairs
              (pair_id, from_name, from_pt, to_name, to_pt, crow_km, weight)
            VALUES
              (:pair_id, :from_name, ST_SetSRID(ST_MakePoint(:from_lon, :from_lat), 4326),
               :to_name, ST_SetSRID(ST_MakePoint(:to_lon, :to_lat), 4326),
               :crow_km, :weight)
            """
        )
        for p in data:
            s.execute(
                sql,
                {
                    "pair_id": p["pair_id"],
                    "from_name": p["from_name"],
                    "from_lat": p["from"][0],
                    "from_lon": p["from"][1],
                    "to_name": p["to_name"],
                    "to_lat": p["to"][0],
                    "to_lon": p["to"][1],
                    "crow_km": p["crow_km"],
                    "weight": p["weight"],
                },
            )
    print(f"[load] od_pairs loaded: {len(data)}")
    return len(data)


def run() -> dict:
    return {
        "segments": load_segments(),
        "corridors": load_corridors(),
        "od_pairs": load_od_pairs(),
    }


if __name__ == "__main__":
    run()
