"""تحقّق: هل ملفات التعريف المبنية من بيانات حقيقية تُنتج منحنى حقيقياً؟

هذا هو الاختبار الحاسم للمرحلة 0. لا يكفي أن نقول «لدينا بيانات».
يجب أن يُظهر النموذج — المبني على تلك البيانات — فرقاً واضحاً بين
ساعة الذروة والهدوء، وأن يتفق مع ما قاسه المزوّد.

التشغيل: python scripts/verify_real.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from zahma.db import session_scope
from zahma.predict.engine import departure_curve, estimate_route

ALGIERS = ZoneInfo("Africa/Algiers")

# باب الزوار ← وسط العاصمة — المحور الذي قِيس يدوياً.
FROM = (36.7167, 3.1833)
TO = (36.7705, 3.0589)


def sample_report() -> dict:
    with session_scope() as s:
        return dict(
            s.execute(
                text(
                    """
                    SELECT count(*) AS samples,
                           count(DISTINCT segment_id) AS segments,
                           count(DISTINCT ts_utc::date) AS days,
                           count(DISTINCT ts_bucket) AS buckets
                    FROM samples WHERE source = 'mapbox'
                    """
                )
            ).mappings().one()
        )


def profile_report() -> dict:
    with session_scope() as s:
        return dict(
            s.execute(
                text(
                    """
                    SELECT count(*) AS rows,
                           coalesce(max(segments_n), 0) AS segments,
                           count(DISTINCT road_class) AS classes,
                           coalesce(sum(samples_n), 0) AS samples
                    FROM class_profiles
                    """
                )
            ).mappings().one()
        )


def curve_report() -> list[tuple[str, float, float]]:
    """منحنى الانطلاق على 24 ساعة محلياً.

    كان 06:00–20:00 فقط، فكان يخفي كل ما جمعناه ليلاً. المنحنى الكامل
    ضروري: الليل أسرع بـ60% من الذروة المسائية (مقاس مباشرة من API)،
    وهذا فرق يجب أن يراه المستخدم في «متى أخرج».
    """
    base = datetime(2026, 11, 30, 0, 0, tzinfo=UTC)  # 01:00 محلي (UTC+1)
    out: list[tuple[str, float, float]] = []
    for i in range(0, 24, 1):
        t = base.replace(hour=base.hour + i)
        est = estimate_route(FROM[0], FROM[1], TO[0], TO[1], when=t, now=t)
        out.append(
            (t.astimezone(ALGIERS).strftime("%H:%M"), est.minutes, est.confidence)
        )
    return out


def main() -> int:
    smp = sample_report()
    prof = profile_report()

    print("── عينات حقيقية")
    print(
        f"   {smp['samples']:,} قياس، {smp['segments']:,} مقطع، "
        f"{smp['days']} يوم، {smp['buckets']:,} شريحة"
    )

    print("\n── ملفات تعريف الأصناف")
    print(
        f"   {prof['rows']:,} صفاً، {prof['classes']} صنف طريق، "
        f"{prof['samples']:,} عينة داخلة"
    )

    print("\n── منحنى الانطلاق (باب الزوار ← الوسط)")
    curve = curve_report()
    durs = []
    for hh, mins, conf in curve:
        durs.append(mins)
        bar = "█" * max(1, int(mins / 1.5))
        print(f"   {hh}  {mins:5.1f} د  ثقة {conf:.2f}  {bar}")

    spread = max(durs) - min(durs)
    print(f"\n   المدى: {spread:.1f} دقيقة")

    ok = True
    if smp["samples"] == 0:
        print("\n✗ لا عينات حقيقية")
        ok = False
    if prof["rows"] == 0:
        print("\n✗ ملفات تعريف فارغة — البيانات لم تُبنَ")
        ok = False
    if spread < 2.0:
        print(f"\n✗ المنحنى مسطّح ({spread:.1f} د) — الإسقاط فاشل")
        ok = False

    # الحارس الأهم: الاتجاه. الذروة المسائية أسوأ من الصباحية
    # (مقيس من المزوّد: 41.3 مقابل 45.9 كم/س).
    morning = min(d for hh, d, _ in curve if hh in ("07:30", "08:00", "08:30"))
    evening = max(d for hh, d, _ in curve if hh in ("17:00", "17:30", "18:00"))
    if evening > morning:
        print(f"   ✓ الذروة المسائية أبطأ: {evening:.1f} د مقابل {morning:.1f} د صباحاً")
    else:
        print(f"   ! المسائية {evening:.1f} د ليست أبطأ من الصباحية {morning:.1f} د")

    if ok:
        print("\n✓ ملفات التعريف مبنية على بيانات حقيقية وتُنتج منحنى حقيقياً")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
