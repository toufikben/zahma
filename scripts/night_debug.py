"""تشخيص فشل الطلبات الليلية — نرى الرد الحقيقي لا نخمّنه."""

from __future__ import annotations

import httpx
from sqlalchemy import text

from zahma.config import get_settings
from zahma.db import session_scope

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"


def main() -> int:
    s = get_settings()
    print(f"token len={len(s.mapbox_token or '')}")

    with session_scope() as ss:
        r = ss.execute(
            text(
                """
                SELECT pair_id, ST_Y(from_pt) flat, ST_X(from_pt) flon,
                       ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                FROM od_pairs WHERE active ORDER BY weight DESC LIMIT 1
                """
            )
        ).mappings().one()

    coords = f"{r['flon']},{r['flat']};{r['tlon']},{r['tlat']}"
    print(f"coords: {coords}")

    for depart in ("2026-12-02T03:00", "2026-12-02T08:00", None):
        params = {
            "access_token": s.mapbox_token,
            "annotations": "speed",
            "overview": "none",
        }
        if depart:
            params["depart_at"] = depart
        try:
            resp = httpx.get(f"{BASE}/{coords}", params=params, timeout=25)
            print(f"\ndepart={depart}  status={resp.status_code}")
            print(resp.text[:300])
        except httpx.HTTPError as e:
            print(f"\ndepart={depart}  NET ERROR {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
