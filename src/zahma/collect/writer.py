"""كاتب قاعدة البيانات — إدراج idempotent لكل أنواع القياسات.

القاعدة: إعادة المحاولة يجب ألا تكرر ولا تُفسد.
كل إدراج يستخدم ON CONFLICT DO NOTHING بمفتاح طبيعي.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from zahma.db import session_scope
from zahma.sources.base import (
    Incident,
    RouteSample,
    SegmentSample,
    SourceResult,
    ts_bucket,
)


def _b(ts: datetime, minutes: int = 5) -> datetime:
    return ts_bucket(ts, minutes)


def write_segment_samples(samples: list[SegmentSample], bucket_min: int = 5) -> int:
    if not samples:
        return 0
    rows = []
    for s in samples:
        if s.segment_id is None or s.segment_id <= 0:
            continue
        b = _b(s.ts_utc, bucket_min)
        ratio = None
        if s.speed_kmh and s.freeflow_kmh:
            ratio = round(s.speed_kmh / s.freeflow_kmh, 4)
        rows.append(
            {
                "segment_id": s.segment_id,
                "source": s.source,
                "ts_utc": s.ts_utc,
                "ts_bucket": b,
                "speed_kmh": s.speed_kmh,
                "freeflow_kmh": s.freeflow_kmh,
                "travel_time_s": s.travel_time_s,
                "confidence": s.confidence,
                "ratio": ratio,
                "raw_ref": s.raw_ref,
            }
        )
    if not rows:
        return 0

    sql = text(
        """
        INSERT INTO samples
          (segment_id, source, ts_utc, ts_bucket, speed_kmh, freeflow_kmh,
           travel_time_s, confidence, ratio, raw_ref)
        VALUES
          (:segment_id, :source, :ts_utc, :ts_bucket, :speed_kmh, :freeflow_kmh,
           :travel_time_s, :confidence, :ratio, :raw_ref)
        ON CONFLICT (segment_id, source, ts_bucket) DO NOTHING
        """
    )
    with session_scope() as s:
        s.execute(sql, rows)
    return len(rows)


def write_route_samples(samples: list[RouteSample], bucket_min: int = 5) -> int:
    if not samples:
        return 0
    rows = []
    for r in samples:
        b = _b(r.ts_utc, bucket_min)
        rows.append(
            {
                "pair_id": r.pair_id,
                "source": r.source,
                "ts_utc": r.ts_utc,
                "ts_bucket": b,
                "duration_s": r.duration_s,
                "duration_free_s": r.duration_free_s,
                "distance_m": r.distance_m,
                "delay_ratio": r.delay_ratio,
                "confidence": r.confidence,
                "geometry": r.geometry_wkt,
            }
        )
    sql = text(
        """
        INSERT INTO route_samples
          (pair_id, source, ts_utc, ts_bucket, duration_s, duration_free_s,
           distance_m, delay_ratio, confidence, geometry)
        VALUES
          (:pair_id, :source, :ts_utc, :ts_bucket, :duration_s, :duration_free_s,
           :distance_m, :delay_ratio, :confidence,
           ST_GeomFromText(CAST(:geometry AS text), 4326))
        ON CONFLICT (pair_id, source, ts_bucket) DO NOTHING
        """
    )
    with session_scope() as s:
        s.execute(sql, rows)
    return len(rows)


def write_incidents(incidents: list[Incident]) -> int:
    if not incidents:
        return 0
    rows = []
    for i in incidents:
        rows.append(
            {
                "source": i.source,
                "external_id": i.external_id,
                "ts_utc": i.ts_utc,
                "category": i.category,
                "category_name": i.category_name,
                "severity": i.severity,
                "magnitude": i.magnitude,
                "delay_s": i.delay_s,
                "length_m": i.length_m,
                "description": i.description,
                "from_desc": i.from_desc,
                "to_desc": i.to_desc,
                "road_name": i.road_name,
                "geometry": i.geometry_wkt,
            }
        )
    sql = text(
        """
        INSERT INTO incidents
          (source, external_id, ts_utc, category, category_name, severity,
           magnitude, delay_s, length_m, description, from_desc, to_desc,
           road_name, geom)
        VALUES
          (:source, :external_id, :ts_utc, :category, :category_name, :severity,
           :magnitude, :delay_s, :length_m, :description, :from_desc, :to_desc,
           :road_name,
           ST_GeomFromText(CAST(:geometry AS text), 4326))
        ON CONFLICT (source, external_id, ts_utc) DO NOTHING
        """
    )
    with session_scope() as s:
        s.execute(sql, rows)
    return len(rows)


def link_incidents_to_segments() -> int:
    """يربط كل عطل بأقرب مقطع — يفتح الباب لتفسير الشذوذ.

    نستخدم مسافة هندسية مع حد أقصى 60 متراً، وإلا يبقى غير مربوط.
    """
    sql = text(
        """
        UPDATE incidents i
        SET segment_id = (
            SELECT s.seg_id
            FROM segments s
            WHERE ST_DWithin(s.geom::geography, i.geom::geography, 60)
            ORDER BY s.geom <-> i.geom
            LIMIT 1
        )
        WHERE i.segment_id IS NULL AND i.geom IS NOT NULL
        """
    )
    with session_scope() as sess:
        res = sess.execute(sql)
    return res.rowcount or 0


def write_result(result: SourceResult) -> dict[str, int]:
    """يكتب كل ما في نتيجة مصدر واحد. يربط المقاطع المجهولة أولاً."""
    out = {"segments": 0, "routes": 0, "incidents": 0}

    if result.segment_samples:
        out["segments"] = write_segment_samples(result.segment_samples)
    if result.route_samples:
        out["routes"] = write_route_samples(result.route_samples)
    if result.incidents:
        out["incidents"] = write_incidents(result.incidents)
        link_incidents_to_segments()
    return out


def touch_health(
    source: str,
    ok: bool,
    error: str | None = None,
    requests: int = 0,
    quota_exhausted: bool = False,
) -> None:
    """يحدّث صحة المصدر واستهلاك الحصة."""
    now = datetime.now(UTC)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    with session_scope() as s:
        s.execute(
            text(
                """
                INSERT INTO source_health (source, last_ok_ts, last_error_ts, last_error,
                                           consecutive_failures, circuit_open, updated_at)
                VALUES (:src, :ok_ts, :err_ts, :err, :fails, :circuit, now())
                ON CONFLICT (source) DO UPDATE SET
                    last_ok_ts = COALESCE(EXCLUDED.last_ok_ts, source_health.last_ok_ts),
                    last_error_ts = COALESCE(EXCLUDED.last_error_ts, source_health.last_error_ts),
                    last_error = COALESCE(EXCLUDED.last_error, source_health.last_error),
                    consecutive_failures = CASE WHEN :ok THEN 0
                        ELSE source_health.consecutive_failures + 1 END,
                    circuit_open = :circuit,
                    updated_at = now()
                """
            ),
            {
                "src": source,
                "ok_ts": now if ok else None,
                "err_ts": None if ok else now,
                "err": error,
                "fails": 0 if ok else 1,
                "circuit": quota_exhausted,
                "ok": ok,
            },
        )

        if requests:
            s.execute(
                text(
                    """
                    INSERT INTO quota_usage (source, month_utc, used)
                    VALUES (:src, :m, :n)
                    ON CONFLICT (source, month_utc) DO UPDATE
                    SET used = quota_usage.used + EXCLUDED.used
                    """
                ),
                {"src": source, "m": month.date(), "n": requests},
            )


def record_gap(source: str, from_ts: datetime, to_ts: datetime, reason: str) -> None:
    """تسجيل فجوة صراحة — النموذج يتجاهلها ولا يخترعها."""
    with session_scope() as s:
        s.execute(
            text(
                """
                INSERT INTO collection_gaps (source, from_ts, to_ts, reason)
                VALUES (:src, :f, :t, :r)
                """
            ),
            {"src": source, "f": from_ts, "t": to_ts, "r": reason},
        )


def quota_used(source: str) -> int:
    with session_scope() as s:
        v = s.execute(
            text(
                "SELECT used FROM quota_usage "
                "WHERE source = :s AND month_utc = date_trunc('month', now())::date"
            ),
            {"s": source},
        ).scalar()
    return int(v or 0)


def write_weather(meta: dict, ts: datetime | None = None) -> None:
    """يخزّن رصد الطقس — عامل تصحيح في النموذج."""
    from zahma.sources.base import ts_bucket as _tb

    ts = ts or datetime.now(UTC)
    b = _tb(ts, 30)
    with session_scope() as s:
        s.execute(
            text(
                """
                INSERT INTO weather_obs
                  (ts_utc, ts_bucket, temp_c, precip_mm, rain_mm, weather_code,
                   wind_kmh, visibility_m, factor)
                VALUES (:ts, :b, :t, :p, :r, :wc, :w, :v, :f)
                ON CONFLICT (ts_bucket) DO NOTHING
                """
            ),
            {
                "ts": ts,
                "b": b,
                "t": meta.get("temp_c"),
                "p": meta.get("precip_mm"),
                "r": meta.get("rain_mm"),
                "wc": meta.get("weather_code"),
                "w": meta.get("wind_kmh"),
                "v": meta.get("visibility_m"),
                "f": meta.get("factor", 1.0),
            },
        )


def counts() -> dict[str, Any]:
    """عدّادات فعلية — أساس تقرير التحقق."""
    with session_scope() as s:
        row = s.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM segments) AS segments,
                  (SELECT COUNT(*) FROM samples) AS samples,
                  (SELECT COUNT(*) FROM route_samples) AS routes,
                  (SELECT COUNT(*) FROM incidents) AS incidents,
                  (SELECT COUNT(*) FROM collection_gaps) AS gaps,
                  (SELECT COUNT(DISTINCT segment_id) FROM samples) AS segs_measured
                """
            )
        ).mappings().one()
    return dict(row)
