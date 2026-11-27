"""أين يوجد annotation فعلاً؟ وهل يحمل سرعات ليلية؟"""

from __future__ import annotations

import httpx
from sqlalchemy import text

from zahma.config import get_settings
from zahma.db import session_scope

BASE = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"


def main() -> int:
    s = get_settings()
    with session_scope() as ss:
        r = ss.execute(
            text(
                """
                SELECT ST_Y(from_pt) flat, ST_X(from_pt) flon,
                       ST_Y(to_pt) tlat, ST_X(to_pt) tlon
                FROM od_pairs WHERE active ORDER BY weight DESC LIMIT 1
                """
            )
        ).mappings().one()

    coords = f"{r['flon']},{r['flat']};{r['tlon']},{r['tlat']}"

    for depart in ("2026-12-02T03:00", "2026-12-02T08:00", "2026-12-02T17:00"):
        resp = httpx.get(
            f"{BASE}/{coords}",
            params={
                "access_token": s.mapbox_token,
                "depart_at": depart,
                "annotations": "speed,duration,distance",
                "overview": "false",
            },
            timeout=25,
        )
        print(f"\n=== depart={depart}  status={resp.status_code}")
        d = resp.json()
        if "routes" not in d:
            print(f"  KEYS: {sorted(d.keys())}")
            print(f"  BODY: {str(d)[:400]}")
            continue
        rt = (d.get("routes") or [{}])[0]
        legs = rt.get("legs") or []
        print(f"  legs={len(legs)}")
        print(f"  duration={rt.get('duration')}  typical={rt.get('duration_typical')}")

        all_spd: list[float] = []
        for i, leg in enumerate(legs):
            ann = leg.get("annotation") or {}
            spd = ann.get("speed") or []
            dur = ann.get("duration") or []
            dist = ann.get("distance") or []
            cong = ann.get("congestion") or []
            print(
                f"  leg{i}: speed n={len(spd)} dur n={len(dur)} "
                f"dist n={len(dist)} cong n={len(cong)}"
            )
            if spd:
                nz = [v for v in spd if v]
                print(f"    speed raw sample={spd[:5]}  nonzero={len(nz)}/{len(spd)}")
                if nz:
                    print(f"    speed m/s min={min(nz):.2f} max={max(nz):.2f}")
                    all_spd.extend(nz)
            if cong:
                uniq = {}
                for c in cong:
                    uniq[c] = uniq.get(c, 0) + 1
                print(f"    congestion: {uniq}")

        if all_spd:
            kmh = [v * 3.6 for v in all_spd]
            print(
                f"  ⇒ متوسط السرعة {sum(kmh)/len(kmh):.1f} كم/س "
                f"(n={len(kmh)})"
            )
        else:
            print("  ⇒ لا سرعات")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
