"""المجمّع — الحلقة التي تجمع من المصادر وتكتب في قاعدة البيانات.

التصميم:
1. يحدّد ما يجب جمعه الآن (ذروة/غير ذروة).
2. ينادي المصادر.
3. يكتب في قاعدة البيانات مباشرة (إن نجح) أو في الطابور (إن فشل).
4. يسجّل الفجوات عند الفشل الكامل.
5. يرسل نبضة.

التشغيل: على سحابة 24/7، لا على حاسوب مطوّر.
"""

from __future__ import annotations

import signal
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from zahma.collect import queue
from zahma.collect.writer import (
    record_gap,
    touch_health,
    write_result,
)
from zahma.config import get_settings
from zahma.db import session_scope
from zahma.sources.base import SourceError, SourceResult, TrafficSource
from zahma.sources.mapbox import MapboxSource
from zahma.sources.mock import MockSource
from zahma.sources.tomtom_flow import TomTomFlowSource
from zahma.sources.tomtom_incidents import TomTomIncidentsSource
from zahma.sources.weather import WeatherSource

TZ = ZoneInfo("Africa/Algiers")

# أوقات الذروة بتوقيت الجزائر
PEAK_HOURS = {(7, 9), (16, 19)}


def is_peak(now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    local = now.astimezone(TZ)
    if local.weekday() == 4:  # الجمعة
        return 16 <= local.hour <= 19
    for a, b in PEAK_HOURS:
        if a <= local.hour < b:
            return True
    return False


def day_type(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    local = now.astimezone(TZ)
    wd = local.weekday()  # 0=الإثنين
    if wd == 4:
        return "FRIDAY"
    if wd == 5:
        return "SATURDAY"
    return "WORKDAY"


class Collector:
    """يدير دورة جمع واحدة ويسجّل كل نتيجة."""

    def __init__(self, dry_run: bool = False):
        self.settings = get_settings()
        self.dry_run = dry_run
        self.sources: dict[str, TrafficSource] = {}
        self.stats: dict[str, dict] = {}

    # ---------- تحميل ما نحتاجه من قاعدة البيانات ----------

    def _load_pairs(self, limit: int | None = None) -> list[dict]:
        sql = "SELECT pair_id, from_name, to_name, crow_km FROM od_pairs WHERE active ORDER BY weight DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        sql += ";"
        with session_scope() as s:
            rows = s.execute(text(sql)).mappings().all()
            coords = s.execute(
                text(
                    "SELECT pair_id, ST_Y(from_pt) flat, ST_X(from_pt) flon, "
                    "ST_Y(to_pt) tlat, ST_X(to_pt) tlon FROM od_pairs WHERE active"
                )
            ).mappings().all()
        cmap = {r["pair_id"]: r for r in coords}
        out = []
        for r in rows:
            c = cmap[r["pair_id"]]
            out.append(
                {
                    "pair_id": r["pair_id"],
                    "from_name": r["from_name"],
                    "to_name": r["to_name"],
                    "from": [c["flat"], c["flon"]],
                    "to": [c["tlat"], c["tlon"]],
                    "crow_km": float(r["crow_km"]),
                }
            )
        return out

    def _load_corridor_points(self, n_corridors: int = 6, per: int = 1) -> list[dict]:
        """نقاط على أفضل المحاور — للعمق عبر TomTom Flow.

        نأخذ منتصف كل مقطع في المحاور الأعلى أهمية.
        """
        sql = text(
            """
            SELECT s.seg_id, ST_Y(ST_LineInterpolatePoint(s.geom, 0.5)) AS lat,
                   ST_X(ST_LineInterpolatePoint(s.geom, 0.5)) AS lon,
                   s.importance
            FROM segments s
            WHERE s.seg_id IN (
                SELECT unnest(seg_ids) FROM corridors ORDER BY importance DESC LIMIT :n
            )
            ORDER BY s.importance DESC
            LIMIT :k
            """
        )
        with session_scope() as sess:
            rows = sess.execute(sql, {"n": n_corridors, "k": n_corridors * per}).mappings().all()
        return [{"segment_id": r["seg_id"], "lat": r["lat"], "lon": r["lon"]} for r in rows]

    def _load_segments(self, limit: int = 60) -> list[dict]:
        sql = text(
            "SELECT seg_id, speed_free_kmh, length_m FROM segments "
            "ORDER BY importance DESC LIMIT :k"
        )
        with session_scope() as s:
            rows = s.execute(sql, {"k": limit}).mappings().all()
        return [dict(r) for r in rows]

    # ---------- إدارة حصص ----------

    def _quota_ok(self, source: TrafficSource, planned: int) -> bool:
        """هل نستطيع استهلاك `planned` طلباً دون تجاوز الحد الآمن؟"""
        if source.monthly_quota <= 0:
            return True
        from zahma.collect.writer import quota_used

        used = quota_used(source.name)
        cap = int(source.monthly_quota * self.settings.quota_soft_limit)
        return used + planned <= cap

    # ---------- دورة واحدة ----------

    def run_once(self, mode: str = "auto") -> dict[str, dict]:
        now = datetime.now(UTC)
        peak = is_peak(now)
        self.stats = {}

        # --- 1. الطقس (مجاني، بلا حصة) ---
        if self.settings.weather_enabled:
            self._run_source(WeatherSource(), lambda: WeatherSource().fetch())

        # --- 2. المسح الواسع عبر Mapbox ---
        if self.settings.has_mapbox:
            pairs = self._load_pairs(limit=200 if peak else 60)
            n = 200 if peak else 60
            if not self._quota_ok(MapboxSource(), n):
                self.stats["mapbox"] = {"ok": False, "skipped": "quota"}
            else:
                self._run_source(MapboxSource(), lambda m: m.fetch(pairs=pairs))

        # --- 3. العمق عبر TomTom Flow ---
        if self.settings.has_tomtom and peak:
            pts = self._load_corridor_points(n_corridors=6, per=1)
            if not self._quota_ok(TomTomFlowSource(), len(pts)):
                self.stats["tomtom_flow"] = {"ok": False, "skipped": "quota"}
            else:
                self._run_source(TomTomFlowSource(), lambda t: t.fetch(points=pts))

        # --- 4. الأعطال (رخيص، مرة كل ~18 دقيقة) ---
        if self.settings.has_tomtom:
            last = queue.get_heartbeat("incidents_last")
            due = True
            if last:
                try:
                    due = (now - datetime.fromisoformat(last["ts"])) >= timedelta(minutes=18)
                except Exception:  # noqa: BLE001
                    due = True
            if due and self._quota_ok(TomTomIncidentsSource(), 1):
                self._run_source(TomTomIncidentsSource(), lambda i: i.fetch())
                queue.heartbeat("incidents_last")

        return self.stats

    def _run_source(self, source: TrafficSource, fn) -> None:
        name = source.name
        t0 = time.time()
        try:
            result: SourceResult = fn()
        except SourceError as e:
            self.stats[name] = {"ok": False, "error": str(e), "quota": e.quota_exhausted}
            touch_health(name, ok=False, error=str(e), quota_exhausted=e.quota_exhausted)
            return
        except Exception as e:  # noqa: BLE001
            self.stats[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            touch_health(name, ok=False, error=str(e)[:500])
            return

        elapsed = round(time.time() - t0, 2)

        if not result.ok:
            self.stats[name] = {
                "ok": False, "error": result.error,
                "secs": elapsed, "req": result.requests_used,
            }
            touch_health(name, ok=False, error=result.error, requests=result.requests_used)
            if result.requests_used:
                record_gap(name, result.fetched_at - timedelta(minutes=5), result.fetched_at, result.error or "failed")
            return

        # كتابة
        written = {"segments": 0, "routes": 0, "incidents": 0}
        if not self.dry_run:
            try:
                if result.segment_samples or result.route_samples or result.incidents:
                    written = write_result(result)
                if name == "weather" and result.raw_meta:
                    from zahma.collect.writer import write_weather

                    write_weather(result.raw_meta, result.fetched_at)
            except Exception as e:  # noqa: BLE001
                # فشل الكتابة ⇒ نضعه في الطابور حتى لا يُفقد
                error = f"{type(e).__name__}: {e}"
                queue.push(name, "result", {"error": error, "meta": result.raw_meta})
                self.stats[name] = {"ok": False, "error": error, "queued": True}
                touch_health(name, ok=False, error=error)
                return

        self.stats[name] = {
            "ok": True,
            "secs": elapsed,
            "req": result.requests_used,
            "segments": written.get("segments", 0),
            "routes": written.get("routes", 0),
            "incidents": written.get("incidents", 0),
            "records": result.total_records,
        }
        touch_health(name, ok=True, requests=result.requests_used)
        queue.heartbeat(f"last_ok_{name}", str(result.total_records))


def run_forever(once: bool = False) -> None:
    s = get_settings()
    stopping = {"flag": False}

    def _stop(signum, frame):  # noqa: ARG001
        stopping["flag"] = True

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except Exception:  # noqa: BLE001
        pass

    collector = Collector()
    cycle = 0
    print(f"[collector] starting (peak={is_peak()}, day={day_type()})", flush=True)

    while not stopping["flag"]:
        cycle += 1
        peak = is_peak()
        interval = (
            s.scan_interval_peak_min if peak else s.scan_interval_offpeak_min
        )
        try:
            stats = collector.run_once()
            ok = sum(1 for v in stats.values() if v.get("ok"))
            print(
                f"[{datetime.now(UTC).isoformat(timespec='seconds')}] "
                f"cycle {cycle} peak={peak} ok={ok}/{len(stats)} {stats}",
                flush=True,
            )
            queue.heartbeat("collector_cycle", str(cycle))
        except Exception:  # noqa: BLE001
            traceback.print_exc()

        if once:
            break

        for _ in range(int(interval * 60 / 5)):
            if stopping["flag"]:
                break
            time.sleep(5)

    print("[collector] stopped", flush=True)
