"""الحسم: هل التذبذب من السرعة أم من تغيّر المسار؟

**المكتشف:** مسار 07:30 (شريحة 30) = 261 مقطعاً، 14.78 كم، 21.55 د.
ومسار 07:45 (شريحة 31) = 298 مقطعاً، 13.94 كم، 28.34 د.

المسار **أقصر** (13.94 مقابل 14.78) لكن المدة **أطول** (28.34 مقابل 21.55).
والتغطية متداخلة 100%، والسرعات المتوسطة متقاربة (54.37 مقابل 56.06).

**فالسؤال الحاسم:** لو حسبنا مدة **نفس المسار** بالسرعتين، هل يتقاربان؟
- إن تقاربا ⇒ التذبذب كله من تغيّر المسار، والسرعات سليمة.
- إن اختلفا ⇒ السرعات نفسها متضاربة، وهي المشكلة.

**القياس:** نأخذ مقاطع مسار 30، ونحسب المدة عند الشريحتين بنفس المقاطع.
ثم نفعل العكس لمسار 31. هذا يفصل المتغيّرين تماماً.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from zahma.db import session_scope
from zahma.predict.engine import bucket_15m, calendar_flags, day_type_of
from zahma.predict.router import route, speeds_at

FROM = (36.7167, 3.1833)
TO = (36.7705, 3.0589)


def path_at(when: datetime):
    return route(*FROM, *TO, speeds=speeds_at(when=when, now=when))


def duration_on_path(ids: list[int], when: datetime) -> tuple[float, float]:
    """مدة على مقاطع محدّدة بسرعات وقت معيّن + الطول."""
    b = bucket_15m(when)
    dtype = day_type_of(when)
    flags = calendar_flags(when)

    from zahma.predict.engine import (
        fetch_class_ratios_bulk,
        fetch_class_speeds_bulk,
        fetch_profile_speeds_bulk,
    )

    prof = fetch_profile_speeds_bulk(b, dtype, flags)
    cls = fetch_class_speeds_bulk(b, dtype, flags)
    ratio = fetch_class_ratios_bulk(b, dtype, flags)

    with session_scope() as s:
        rows = s.execute(
            text(
                "SELECT seg_id, length_m, speed_free_kmh, road_class "
                "FROM segments WHERE seg_id = ANY(:ids)"
            ),
            {"ids": ids},
        ).mappings().all()
    by_id = {int(r["seg_id"]): dict(r) for r in rows}

    total_s = 0.0
    total_m = 0.0
    for sid in ids:
        seg = by_id.get(sid)
        if not seg:
            continue
        total_m += seg["length_m"]
        # نفس ترتيب المحرك: ملف ← صنف (نسبة) ← حر
        v = prof.get(sid)
        if v is None:
            r = ratio.get(seg["road_class"])
            c = cls.get(seg["road_class"])
            if r is not None and seg["speed_free_kmh"]:
                v = float(seg["speed_free_kmh"]) * float(r)
            elif c is not None:
                v = float(c)
            else:
                v = float(seg["speed_free_kmh"] or 30.0)
        v = max(float(v), 1.0)
        total_s += (seg["length_m"] / 1000.0) / v * 3600.0
    return total_s, total_m / 1000.0


def main() -> int:
    t30 = datetime(2026, 12, 15, 6, 30, tzinfo=UTC)   # 07:30 محلياً
    t31 = datetime(2026, 12, 15, 6, 45, tzinfo=UTC)   # 07:45 محلياً

    p30 = path_at(t30)
    p31 = path_at(t31)
    ids30 = list(p30.seg_ids)
    ids31 = list(p31.seg_ids)

    print(f"مسار 07:30: {len(ids30)} مقطعاً")
    print(f"مسار 07:45: {len(ids31)} مقطعاً")
    print()

    print("── مدة مسار 07:30 بالسرعتين")
    s_a, km_a = duration_on_path(ids30, t30)
    s_b, _ = duration_on_path(ids30, t31)
    print(f"  بسرعات 07:30: {s_a / 60:6.2f} د  ({km_a:.2f} كم)")
    print(f"  بسرعات 07:45: {s_b / 60:6.2f} د")
    print(f"  الفرق: {(s_b - s_a) / 60:+.2f} د  ({(s_b - s_a) / s_a * 100:+.1f}%)")
    print()

    print("── مدة مسار 07:45 بالسرعتين")
    s_c, km_c = duration_on_path(ids31, t31)
    s_d, _ = duration_on_path(ids31, t30)
    print(f"  بسرعات 07:45: {s_c / 60:6.2f} د  ({km_c:.2f} كم)")
    print(f"  بسرعات 07:30: {s_d / 60:6.2f} د")
    print(f"  الفرق: {(s_d - s_c) / 60:+.2f} د  ({(s_d - s_c) / s_c * 100:+.1f}%)")
    print()

    print("── الحكم")
    speed_effect_a = abs(s_b - s_a) / s_a * 100
    speed_effect_b = abs(s_d - s_c) / s_c * 100
    print(f"  أثر السرعة على نفس المسار: {speed_effect_a:.1f}% و{speed_effect_b:.1f}%")
    path_effect = abs(s_c - s_a) / s_a * 100
    print(f"  أثر اختيار المسار:        {path_effect:.1f}%")
    print()
    if max(speed_effect_a, speed_effect_b) < path_effect / 2:
        print("  ⇒ **التذبذب من اختيار المسار، لا من السرعة.**")
        print("     نفس المسار يعطي مدة شبه ثابتة بين الشريحتين.")
        print("     لكن Dijkstra يختار مساراً مختلفاً في كل شريحة،")
        print("     فتختلف المدة — والمنحنى يقارن رحلتين لا رحلة واحدة.")
        print()
        print("     **الإصلاح:** تثبيت المسار في منحنى الانطلاق.")
        print("     نحسب المسار مرة واحدة، ثم نقيس المدة على نفس المقاطع")
        print("     لكل شريحة. هذا ما تفعله تطبيقات الملاحة: «نفس الطريق،")
        print("     أوقات مختلفة». وإلا فالمقارنة بلا معنى.")
    else:
        print("  ⇒ السرعات نفسها متضاربة بين الشريحتين.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
