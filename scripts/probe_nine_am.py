"""قفزة 09:00 في منحنى الانطلاق — هل هي سرعة أم مصدر؟

**المقاس:** بعد تثبيت المسار، المنحنى من باب الزوار ← وسط الجزائر:

    08:30 = 21.5 د | 08:45 = 20.5 د | 09:00 = 24.0 د

قفزة +3.5 دقيقة (17%) بين خيارين متتاليين. والمسار مثبَّت، فليست
مشكلة توجيه. والسرعة وحدها كان أثرها 2.5–3.6% — أصغر بكثير.

**الفرضية:** تغيّر في تغطية الملفات أو في `basis` بين الشريحتين.
الشريحة 34 (08:30) فيها 4,428 مقطعاً، والشريحة 36 (09:00) فيها 3,849.

**القياس:** نطبع لكل شريحة عدد المقاطع بكل أساس، وعامل الطقس،
وعقوبة الأعطال، ومجموع السرعات.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from zahma.db import session_scope
from zahma.predict.engine import (
    bucket_15m,
    calendar_flags,
    day_type_of,
    estimate_on_path,
    incident_penalty_for,
    weather_factor_now,
)
from zahma.predict.router import route, speeds_at
from sqlalchemy import text

FROM = (36.7167, 3.1833)
TO = (36.7705, 3.0589)
BASE = datetime(2026, 12, 15, 6, 30, tzinfo=UTC)  # 07:30 محلياً


def main() -> int:
    path = route(*FROM, *TO, speeds=speeds_at(when=BASE, now=BASE))
    ids = list(path.seg_ids)

    print(f"المسار المثبَّت: {len(ids)} مقطعاً")
    print()
    print(f"{'الوقت':>6}  {'شريحة':>6}  {'دقيقة':>7}  {'طقس':>5}  {'عطل':>5}  الأساس")
    print("-" * 78)

    from zahma.predict.engine import local_now  # noqa: PLC0415

    for m in range(60, 121, 15):
        t = BASE + timedelta(minutes=m)  # 08:30 .. 09:30 UTC
        est = estimate_on_path(ids, when=t, now=BASE)
        b = bucket_15m(t)
        wf = weather_factor_now(BASE)
        pen, _ = incident_penalty_for(ids)
        basis = dict(est.basis_counts or {})
        print(
            f"{local_now(t):%H:%M}  {b:>6}  {est.duration_s / 60:>7.2f}  "
            f"{wf:>5.2f}  {pen:>5.2f}  {basis}"
        )

    print()
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT bucket_15m AS b, count(*) AS segs,
                       count(DISTINCT segment_id) AS u
                FROM speed_profiles
                WHERE day_type='WORKDAY' AND bucket_15m BETWEEN 32 AND 40
                GROUP BY 1 ORDER BY 1
                """
            )
        ).mappings().all()
        print("تغطية الملفات:")
        for r in rows:
            print(f"  {r['b']:2d}: {r['segs']:,} صفاً")

        print()
        print("تغطية مقاطع مسارنا:")
        for b in (34, 35, 36):
            n = s.execute(
                text(
                    """
                    SELECT count(*) FROM speed_profiles
                    WHERE day_type='WORKDAY' AND bucket_15m = :b
                      AND segment_id = ANY(:ids)
                    """
                ),
                {"b": b, "ids": ids},
            ).scalar()
            print(f"  {b}: {n} مقطعاً من {len(ids)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
