"""إثبات أن `ON CONFLICT` يمحو قياسات الأزواج المتداخلة — بلا أي إشارة.

**الفرضية:** نرسل قياسين لنفس (المقطع، الشريحة) بقيمتين مختلفتين، ونرى
ماذا يبقى في `samples`. إن بقي صف واحد بأحد القيمتين فالعيب مؤكد: قياس
كامل ضاع بلا أثر، والقيمة الباقية تعتمد على ترتيب الكتابة لا على الطريق.

**لماذا هذا مهم:** 17.2 زوجاً تُجمع في نفس الشريحة، وكل زوج يعطي ~200-600
حافة. المجموع ~6,800، لكن المخزَّن 4,350 فقط. أي أن ~36% من القياسات
تُمحى. والأسوأ: الكتابة متوازية عبر ThreadPoolExecutor، فالفائز عشوائي.

**الأثر على المنتج:** الصف الباقي لمقطع مشترك بين زوجين قد يحمل سرعة
الطريق الآخر. والنموذج يبني عليه ملفاً. لا خطأ يُرفع، لا سجل، لا شيء.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from zahma.collect.match import EdgeMeasurement, RouteMeasurement, store
from zahma.db import session_scope

TS = datetime(2027, 6, 1, 12, 0, tzinfo=UTC)  # وقت بعيد، لا يتصادم مع بياناتنا
SEG_A = 600
SEG_B = 998


def cleanup() -> None:
    with session_scope() as ss:
        ss.execute(text("DELETE FROM samples WHERE ts_bucket = :t"), {"t": TS})
        ss.execute(
            text("DELETE FROM segment_pair_samples WHERE ts_bucket = :t"), {"t": TS}
        )


def read(seg: int) -> list[float]:
    with session_scope() as ss:
        rows = ss.execute(
            text(
                "SELECT speed_kmh FROM samples WHERE segment_id = :s AND ts_bucket = :t"
            ),
            {"s": seg, "t": TS},
        ).all()
    return [float(r[0]) for r in rows]


def read_detail(seg: int) -> list[tuple[int, float]]:
    """كل القياسات المحفوظة، بزوجها — ما كان يُمحى."""
    with session_scope() as ss:
        rows = ss.execute(
            text(
                """
                SELECT pair_id, speed_kmh FROM segment_pair_samples
                WHERE segment_id = :s AND ts_bucket = :t
                ORDER BY pair_id
                """
            ),
            {"s": seg, "t": TS},
        ).all()
    return [(int(r[0]), float(r[1])) for r in rows]


def make_measurement(pair_id: int, seg: int, speed: float) -> RouteMeasurement:
    return RouteMeasurement(
        pair_id=pair_id,
        duration_s=1000.0,
        duration_typical_s=800.0,
        distance_m=10000.0,
        edges=[EdgeMeasurement(seg_id=seg, speed_kmh=speed, dist_m=50.0, travel_s=2.0, offset_m=3.0)],
        matched=1,
        unmatched=0,
    )


def main() -> int:
    cleanup()
    try:
        # زوج 1 يقول: المقطع 600 سرعته 20 كم/س
        store([make_measurement(1, SEG_A, 20.0)], TS, forecast=True)
        first = read(SEG_A)
        print(f"بعد الزوج 1: المقطع {SEG_A} = {first}")

        # زوج 2 يمر بنفس المقطع ويقول: 80 كم/س (طريق مختلف، سرعة مختلفة)
        store([make_measurement(2, SEG_A, 80.0)], TS, forecast=True)
        second = read(SEG_A)
        print(f"بعد الزوج 2: المقطع {SEG_A} = {second}")

        detail = read_detail(SEG_A)
        print(f"التفصيل المحفوظ: {detail}")

        print()
        if len(detail) == 2:
            print("⇒ **الإصلاح يعمل.** القياسان محفوظان، كلٌّ بزوجه.")
            print("   `samples` يحمل قيمة مجمَّعة واحدة (المتوقع)،")
            print("   و`segment_pair_samples` يحمل الحقيقة كاملة.")
        else:
            print(f"⇒ التفصيل ناقص: {len(detail)} صف بدل 2 — ما زال يُمحى.")

        # القياس نفسه على مقطع آخر لم يتصادم: يبقى سليماً.
        store([make_measurement(3, SEG_B, 55.0)], TS, forecast=True)
        print(f"\nمقطع بلا تصادم ({SEG_B}): {read(SEG_B)} — سليم")
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
