"""محوّل TomTom Incidents — الأعطال والحوادث.

قيمته:
1. يفسّر الشذوذ: سرعة 15 كم/س على طريق سريع ليست زحمة، بل حادث.
2. يمنع التنبؤ على طريق مغلق.
3. يبني خريطة تكرار: أي مكان يختنق دائماً ⇒ عيب هندسي مروري.

الحصة: 2,500 طلب/شهر — نستخدم 80 طلباً يومياً (كل 18 دقيقة في النهار).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from zahma.config import get_settings
from zahma.collect.http import RetryingClient
from zahma.sources.base import Incident, SourceError, SourceResult, TrafficSource

BASE = "https://api.tomtom.com/traffic/services/5/incidentDetails"


class TomTomIncidentsSource(TrafficSource):
    name = "tomtom_incidents"
    monthly_quota = 2_500

    def __init__(self, timeout: float = 20.0):
        self.settings = get_settings()
        self.timeout = timeout

    def available(self) -> bool:
        return self.settings.has_tomtom

    def fetch(
        self,
        bbox: tuple[float, float, float, float] | None = None,
        language: str = "ar",
        category_filter: str | None = None,
    ) -> SourceResult:
        """يجلب الأعطال في نطاق جغرافي.

        bbox بصيغة (minLon, minLat, maxLon, maxLat) كما يطلب TomTom.
        """
        from zahma.config import ALGIERS_BBOX

        now = datetime.now(UTC)

        if not self.available():
            return SourceResult(
                source=self.name, ok=False, fetched_at=now, error="TOMTOM_KEY missing"
            )

        if bbox is None:
            s, w, n, e = ALGIERS_BBOX
            bbox = (w, s, e, n)

        params: dict[str, Any] = {
            "key": self.settings.tomtom_key,
            "bbox": ",".join(f"{v:.5f}" for v in bbox),
            "language": language,
            "timeValidityFilter": "present",
            "fields": (
                "{incidents{type,geometry{type,coordinates},"
                "properties{id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},"
                "startTime,endTime,from,to,length,delay,roadNumbers,aci}}}"
            ),
        }
        if category_filter:
            params["categoryFilter"] = category_filter

        try:
            with RetryingClient(timeout=self.timeout) as client:
                r = client.get(BASE, params=params)
        except Exception as e:  # noqa: BLE001
            return SourceResult(source=self.name, ok=False, fetched_at=now, error=str(e))

        if r.status_code == 429:
            raise SourceError("quota exceeded", quota_exhausted=True)
        if r.status_code >= 400:
            return SourceResult(
                source=self.name, ok=False, fetched_at=now,
                error=f"HTTP {r.status_code}: {r.text[:200]}",
            )

        raw = r.json().get("incidents") or []
        incidents: list[Incident] = []
        for item in raw:
            props = item.get("properties") or {}
            events = props.get("events") or []
            ev = events[0] if events else {}
            geom = item.get("geometry") or {}
            coords = geom.get("coordinates") or []

            lat = lon = None
            wkt = None
            if geom.get("type") == "Point" and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
                wkt = f"POINT({lon} {lat})"
            elif geom.get("type") == "LineString" and len(coords) >= 2:
                lat, lon = coords[0][1], coords[0][0]
                wkt = "LINESTRING(" + ",".join(f"{c[0]} {c[1]}" for c in coords) + ")"

            incidents.append(
                Incident(
                    source=self.name,
                    external_id=str(props.get("id", "")),
                    ts_utc=now,
                    category=props.get("iconCategory"),
                    category_name=self._category_name(props.get("iconCategory")),
                    severity=ev.get("severity"),
                    magnitude=props.get("magnitudeOfDelay"),
                    delay_s=props.get("delay"),
                    length_m=props.get("length"),
                    description=ev.get("description"),
                    from_desc=props.get("from"),
                    to_desc=props.get("to"),
                    road_name=(props.get("roadNumbers") or [None])[0],
                    lat=lat,
                    lon=lon,
                    geometry_wkt=wkt,
                )
            )

        return SourceResult(
            source=self.name,
            ok=True,
            fetched_at=now,
            requests_used=1,
            incidents=incidents,
            raw_meta={"count": len(incidents), "bbox": bbox},
        )

    @staticmethod
    def _category_name(cat: int | None) -> str:
        return {
            0: "unknown", 1: "accident", 2: "fog", 3: "dangerous_conditions",
            4: "rain", 5: "ice", 6: "jam", 7: "lane_closed", 8: "road_closed",
            9: "road_works", 10: "wind", 11: "flooding", 14: "broken_down_vehicle",
        }.get(cat, "other") if cat is not None else "unknown"

    def probe(self) -> dict[str, Any]:
        """هل توجد أعطال في العاصمة الآن؟ تحقق سريع من التغطية."""
        try:
            res = self.fetch()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        if not res.ok:
            return {"ok": False, "error": res.error}
        cats: dict[str, int] = {}
        for i in res.incidents:
            cats[i.category_name or "unknown"] = cats.get(i.category_name or "unknown", 0) + 1
        return {
            "ok": True,
            "count": len(res.incidents),
            "by_category": cats,
            "sample": [
                {"cat": i.category_name, "road": i.road_name, "desc": (i.description or "")[:60]}
                for i in res.incidents[:5]
            ],
        }
