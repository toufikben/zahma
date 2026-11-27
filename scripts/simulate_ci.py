"""محاكاة ظروف CI: 5 أيام، خطوة 60 دقيقة، 400 مقطع.

الغرض: إعادة إنتاج المنحنى المتذبذب الذي ظهر في CI ثم إثبات أن
الاستيفاء الخطي أصلحه. هذا ليس اختباراً — أداة تشخيص.

الاستخدام: python scripts/simulate_ci.py
"""

from __future__ import annotations

import sys

from datetime import UTC, datetime, timedelta

from zahma.collect.mockfill import fill
from zahma.db import session_scope
from zahma.predict.engine import bucket_15m, departure_curve, estimate_route
from zahma.predict.profiles import rebuild, rebuild_class_profiles

from sqlalchemy import text


def reset() -> None:
    with session_scope() as s:
        s.execute(
            text(
                "TRUNCATE samples, route_samples, speed_profiles, "
                "class_profiles, incidents CASCADE"
            )
        )


def main() -> int:
    print("── إعادة ضبط + ملء بظروف CI (5 أيام، 60 دقيقة، 400 مقطع)")
    reset()
    fill(days=5, step_min=60, n_segments=400, n_pairs=40)
    rebuild()
    rebuild_class_profiles()

    when = datetime(2026, 11, 29, 6, 30, tzinfo=UTC)  # 07:30 محلي
    print("\n── منحنى الانطلاق")
    curve = departure_curve(
        36.7167, 3.1833, 36.7705, 3.0589,
        now=when, horizon_min=180, step_min=30,
    )
    durs: list[float] = []
    for o in curve:
        m = o.duration_s / 60
        durs.append(m)
        print(
            f"  {o.depart_at.strftime('%H:%M')}  b={bucket_15m(o.depart_at):3}  "
            f"{m:5.1f} min  conf {o.confidence:.2f}"
        )

    spread = max(durs) - min(durs)
    print(f"\n  المدى: {spread:.1f} دقيقة")

    # كشف التذبذب: أي ارتفاع بعد هبوط (أو العكس) بفارق > 1.5 دقيقة
    flips = 0
    for a, b in zip(durs, durs[1:], strict=False):
        if abs(b - a) > 1.5:
            flips += 1
    # اتجاه واحد = 0. منحنى طبيعي: يرتفع حتى الذروة ثم ينخفض.
    print(f"  تغيّرات > 1.5 دقيقة: {flips}")

    # المنحنى يجب أن يكون رتيباً تقريباً (تغيّر واحد في الاتجاه)
    ups = sum(1 for a, b in zip(durs, durs[1:], strict=False) if b > a + 0.5)
    downs = sum(1 for a, b in zip(durs, durs[1:], strict=False) if b < a - 0.5)
    print(f"  صعود: {ups}  هبوط: {downs}")

    if ups > 1 and downs > 1:
        print("\n✗ المنحنى متذبذب — العيب عاد")
        return 1

    est = estimate_route(36.7167, 3.1833, 36.7705, 3.0589, when=when, now=when)
    print(f"\n── تقدير 07:30: {est.minutes:.1f} min, conf {est.confidence:.2f}")
    print(f"   الأساس: {est.basis_counts}")

    if spread < 2.0:
        print("\n✗ المنحنى مسطّح")
        return 1
    if est.confidence < 0.3:
        print("\n✗ الثقة منخفضة جداً")
        return 1

    print("\n✓ المنحنى سليم: يتغيّر، باتجاه واحد، وبثقة كافية")
    return 0


if __name__ == "__main__":
    sys.exit(main())
