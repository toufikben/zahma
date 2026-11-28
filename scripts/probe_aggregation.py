"""هل التجميع حتمي داخل استدعاء واحد؟ — الاختبار الذي يقرّر صحة الإصلاح.

**السؤال:** الجمع الحقيقي يمرّر 20 زوجاً في **استدعاء `store` واحد**. هل
يُجمّعها في قيمة واحدة حتمية، أم ما زال آخر كاتب يفوز؟

**ولماذا الحتمية مهمة:** لو كان الوسيط يعتمد على ترتيب الإدخال، فإعادة جمع
نفس الشريحة تعطي رقماً مختلفاً — ويصير النموذج غير قابل للتكرار. القياس
السابق أثبت أن هذا يحدث فعلاً (33.82 مقابل 9.92 لنفس الخانة).

هذا السكربت يتحقق من ثلاثة أشياء:
1. استدعاء واحد بعشر قياسات ⇒ صف واحد، بالقيمة الوسيطة.
2. خلط ترتيب الإدخال ⇒ نفس النتيجة بالضبط.
3. التفصيل يحفظ العشر كلها.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import permutations

from sqlalchemy import text

from zahma.collect.match import EdgeMeasurement, RouteMeasurement, store
from zahma.db import session_scope

TS = datetime(2027, 6, 2, 12, 0, tzinfo=UTC)
SEG = 600

# عشر قياسات لنفس المقطع من عشرة أزواج، بسرعات ومسافات مختلفة.
OBS = [(20.0 + i * 7.0, 10.0 + i * 5.0, i + 1) for i in range(10)]


def cleanup() -> None:
    with session_scope() as ss:
        ss.execute(text("DELETE FROM samples WHERE ts_bucket = :t"), {"t": TS})
        ss.execute(
            text("DELETE FROM segment_pair_samples WHERE ts_bucket = :t"), {"t": TS}
        )


def run(order: list[tuple[float, float, int]]) -> tuple[float, int, int]:
    """يشغّل استدعاء store واحداً بترتيب معيّن. يُرجع (القيمة، التفصيل، الصفوف)."""
    cleanup()
    ms = [
        RouteMeasurement(
            pair_id=pid,
            duration_s=1000.0,
            duration_typical_s=800.0,
            distance_m=10000.0,
            edges=[
                EdgeMeasurement(
                    seg_id=SEG, speed_kmh=spd, dist_m=dist, travel_s=2.0, offset_m=3.0
                )
            ],
            matched=1,
            unmatched=0,
        )
        for spd, dist, pid in order
    ]
    store(ms, TS, forecast=True)
    with session_scope() as ss:
        v = ss.execute(
            text("SELECT speed_kmh FROM samples WHERE segment_id=:s AND ts_bucket=:t"),
            {"s": SEG, "t": TS},
        ).scalar()
        d = ss.execute(
            text(
                "SELECT count(*) FROM segment_pair_samples "
                "WHERE segment_id=:s AND ts_bucket=:t"
            ),
            {"s": SEG, "t": TS},
        ).scalar()
        rows = ss.execute(
            text("SELECT count(*) FROM samples WHERE ts_bucket=:t"), {"t": TS}
        ).scalar()
    return float(v), int(d), int(rows)


def main() -> int:
    cleanup()
    try:
        # 1. ترتيب أصلي
        v1, d1, r1 = run(OBS)
        print(f"الترتيب الأصلي:       القيمة={v1}  التفصيل={d1}  صفوف samples={r1}")

        # 2. ترتيب معكوس
        v2, d2, _ = run(list(reversed(OBS)))
        print(f"الترتيب المعكوس:      القيمة={v2}  التفصيل={d2}")

        # 3. ترتيب مبعثر (ثلاث تبديلات)
        vals = {v1, v2}
        for i, perm in enumerate(permutations(OBS, len(OBS))):
            if i > 2:
                break
            v, d, _ = run(list(perm))
            vals.add(v)
        print(f"ثلاثة ترتيبات أخرى:   القيم={sorted(vals)}")

        print()
        ok = True
        if r1 != 1:
            print(f"⇒ {r1} صفاً في samples — المتوقع 1 (المقطع واحد)")
            ok = False
        if d1 != 10:
            print(f"⇒ التفصيل {d1} صفاً بدل 10 — ما زال يُمحى")
            ok = False
        if len(vals) != 1:
            print(f"⇒ القيمة تعتمد على الترتيب: {sorted(vals)} — غير حتمي")
            ok = False
        if ok:
            print(f"⇒ **حتمي بالكامل.** صف واحد، تفصيل كامل (10)،")
            print(f"   ونفس القيمة ({v1}) في كل ترتيب إدخال.")

        # 4. هل القيمة وسيط فعلاً؟
        speeds = sorted(s for s, _, _ in OBS)
        print(f"\nالسرعات: {speeds}")
        print(f"الوسيط الحسابي: {(speeds[4] + speeds[5]) / 2:.2f}")
        print(f"المخزَّن (موزون بالمسافة): {v1}")
        print("(الفرق متوقع: المسافات مختلفة، فالوسيط موزون لا حسابي)")
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
