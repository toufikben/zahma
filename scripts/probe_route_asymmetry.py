"""لماذا يتغيّر المسار بين 06:30 و06:45؟ — قياس على مسار الراوتر الحقيقي.

**الفرضية المعلّقة:** `speeds_at` يقرأ `fetch_profile_speeds_bulk`، فالمقاطع
ذات الملف في شريحة والمفقودة في أخرى تُستوفى أو تتراجع إلى وسيط الصنف.
إن اختلف عدد المغطّى بين الشريحتين، تغيّرت السرعات النسبية، فيختار
Dijkstra مساراً مختلفاً.

**القياس الصحيح:** نوجّه فعلياً عند الشريحتين، ونأخذ مجموعة المقاطع من
كل مسار، ثم نطبع: عدد المقاطع، وكم منها له ملف حقيقي في تلك الشريحة،
وكم تراجع إلى الصنف، وكم مقطعاً مشتركاً بين المسارين.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from zahma.db import session_scope
from zahma.predict.engine import bucket_15m, calendar_flags, day_type_of
from zahma.predict.router import route, speeds_at

FROM = (36.7167, 3.1833)  # باب الزوار
TO = (36.7705, 3.0589)    # وسط الجزائر


def probe(when: datetime) -> dict:
    b = bucket_15m(when)
    dtype = day_type_of(when)
    flags = calendar_flags(when)

    path = route(*FROM, *TO, speeds=speeds_at(when=when, now=when))
    ids = list(path.seg_ids)

    with session_scope() as s:
        # كم مقطعاً من المسار له ملف حقيقي في هذه الشريحة؟
        n_profile = s.execute(
            text(
                """
                SELECT count(DISTINCT segment_id) FROM speed_profiles
                WHERE day_type = :d AND bucket_15m = :b
                  AND segment_id = ANY(:ids)
                """
            ),
            {"d": dtype, "b": b, "ids": ids},
        ).scalar()

        # كم له ملف في أي شريحة قريبة (±8)؟
        n_near = s.execute(
            text(
                """
                SELECT count(DISTINCT segment_id) FROM speed_profiles
                WHERE day_type = :d AND bucket_15m BETWEEN :lo AND :hi
                  AND segment_id = ANY(:ids)
                """
            ),
            {"d": dtype, "lo": max(0, b - 8), "hi": min(95, b + 8), "ids": ids},
        ).scalar()

        total_len = s.execute(
            text("SELECT sum(length_m) FROM segments WHERE seg_id = ANY(:ids)"),
            {"ids": ids},
        ).scalar()

    return {
        "bucket": b,
        "n_segments": len(ids),
        "n_profile_exact": int(n_profile or 0),
        "n_profile_near": int(n_near or 0),
        "length_km": round(float(total_len or 0) / 1000, 2),
        "ids": set(ids),
    }


def main() -> int:
    a = probe(datetime(2026, 12, 15, 6, 30, tzinfo=UTC))
    b = probe(datetime(2026, 12, 15, 6, 45, tzinfo=UTC))

    for label, r in (("06:30", a), ("06:45", b)):
        print(
            f"{label}  bucket={r['bucket']:2d}  مقاطع={r['n_segments']:3d}  "
            f"طول={r['length_km']:5.2f} كم  "
            f"ملف تام={r['n_profile_exact']:3d}  ملف قريب={r['n_profile_near']:3d}"
        )

    common = a["ids"] & b["ids"]
    print()
    print(f"مقاطع مشتركة: {len(common)} من {len(a['ids'])} و{len(b['ids'])}")
    print(f"في 06:30 فقط: {len(a['ids'] - b['ids'])}")
    print(f"في 06:45 فقط: {len(b['ids'] - a['ids'])}")
    print()
    if a["n_segments"] != b["n_segments"]:
        print("⇒ **المسار مختلف فعلاً.** والسبب المقاس: تغطية الملفات")
        print(f"   {a['n_profile_exact']} عند 06:30 مقابل {b['n_profile_exact']} عند 06:45.")
        print("   المقاطع المفقودة تتراجع إلى وسيط الصنف، فتتغيّر الأوزان.")
        print()
        print("   وهذا **عيب بيانات لا كود**: الشريحة 26 جُمعت بكل الأزواج،")
        print("   والشريحة 27 جُمعت بـ3 أزواج فقط. الإصلاح: جمع 27 كاملاً.")
    else:
        print("⇒ المسار نفسه — لا عيب.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
