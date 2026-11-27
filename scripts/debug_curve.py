from datetime import datetime, timedelta, UTC

from zahma.predict.engine import (
    bucket_15m,
    calendar_flags,
    day_type_of,
    fetch_class_speeds_bulk,
    fetch_profile_speeds_bulk,
    estimate_route,
)

when = datetime(2026, 11, 29, 6, 30, tzinfo=UTC)  # 07:30 محلي

print("bucket  profiles  classes  duration")
for i in range(7):
    t = when + timedelta(minutes=30 * i)
    b = bucket_15m(t)
    dt = day_type_of(t)
    fl = calendar_flags(t)
    prof = fetch_profile_speeds_bulk(b, dt, fl)
    cls = fetch_class_speeds_bulk(b, dt, fl)
    est = estimate_route(36.7167, 3.1833, 36.7705, 3.0589, when=t, now=when)
    local = t.strftime("%H:%M")
    print(
        f"{local}  b={b:3}  prof={len(prof):5}  cls={len(cls):2}  "
        f"{est.duration_s / 60:5.1f} min  {est.basis_counts}"
    )
