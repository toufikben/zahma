"""دقة حقيقية بأسلوب «حجز مكاني» — المقاطع التي لم تُقس قط.

**لماذا لا يصحّ أي اختبار آخر:** اكتشفنا أن Mapbox يعيد للجزائر **نمطاً
أسبوعياً نموذجياً** لا قياساً حياً:

- كل يوم اثنين مطابق لكل يوم اثنين آخر بدقة 0.00 كم/س.
- كل ثلاثاء مطابق لكل ثلاثاء بدقة 0.00 كم/س.
- `depart_at` و«الآن» يعيدان نفس الرقم بالضبط، وثابتان عبر الدقائق.

لذلك أي تقسيم زمني (تدريب على 6 أيام، اختبار على السابع) هو **تسرّب
كامل**: اليوم السابع هو نفس بيانات اليوم الأول حرفياً. «دقة 0.1%»
التي قِسناها بهذه الطريقة لا تعني شيئاً.

**ما يبقى صادقاً: الحجز المكاني.**

نقسّم أزواج O-D نصفين. نبني أولوية الصنف من نصفها، ثم نسأل: هل تتنبأ
بمقاطع النصف الآخر التي **لم تُقس أبداً**؟ هذا سؤال حقيقي، لأن المقاطع
في نصف الاختبار لم تدخل في حساب أي وسيط.

هذا يقيس ما يهم فعلاً: هل نستطيع تقدير شارع لم نمشِ عليه، اعتماداً على
سلوك أقرانه من نفس الصنف؟ إن كان الجواب لا، فالمنتج أعمى عن 97.8% من
شبكته.

التشغيل: python scripts/spatial_accuracy.py
"""

from __future__ import annotations

import argparse
import re
import statistics
from collections import defaultdict
from datetime import UTC

from sqlalchemy import text

from zahma.db import session_scope

PAIR_RE = re.compile(r"pair=(\d+)")


def bucket_of(ts) -> int:
    """رقم الشريحة الربعية بالتوقيت المحلي (0..95)."""
    from zoneinfo import ZoneInfo

    local = ts.astimezone(ZoneInfo("Africa/Algiers"))
    return local.hour * 4 + local.minute // 15


def load() -> list[dict]:
    """كل القياسات الحقيقية مع صنف الطريق ورقم الزوج."""
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT s.segment_id, s.speed_kmh, s.ts_utc,
                       sg.road_class, sg.length_m, sg.speed_free_kmh, s.raw_ref
                FROM samples s
                JOIN segments sg ON sg.seg_id = s.segment_id
                WHERE s.source = 'mapbox'
                  AND s.speed_kmh BETWEEN 3 AND 130
                """
            )
        ).mappings().all()

    out = []
    for r in rows:
        m = PAIR_RE.search(r["raw_ref"] or "")
        if not m:
            continue
        ts = r["ts_utc"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        out.append(
            {
                "seg": int(r["segment_id"]),
                "speed": float(r["speed_kmh"]),
                "b": bucket_of(ts),
                "cls": r["road_class"],
                "pair": int(m.group(1)),
                "len": float(r["length_m"]),
                "free": float(r["speed_free_kmh"]),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    data = load()
    if not data:
        print("لا بيانات")
        return 1

    # تقسيم الأزواج: زوجي = تدريب، فردي = اختبار.
    pairs = sorted({d["pair"] for d in data})
    train_pairs = {p for p in pairs if p % 2 == 0}
    test_pairs = set(pairs) - train_pairs
    print(f"أزواج: {len(pairs)} ← تدريب {len(train_pairs)} / اختبار {len(test_pairs)}")

    train = [d for d in data if d["pair"] in train_pairs]
    test = [d for d in data if d["pair"] in test_pairs]

    train_segs = {d["seg"] for d in train}
    # الحجز الحقيقي: نستبعد من الاختبار أي مقطع ظهر في التدريب.
    test = [d for d in test if d["seg"] not in train_segs]
    if args.limit:
        test = test[: args.limit]

    print(f"عينات تدريب: {len(train):,}  |  عينات اختبار (مقاطع لم تُقس): {len(test):,}")

    # أولوية الصنف من التدريب فقط: وسيط مرجّح بالطول لكل (صنف، شريحة).
    by_key: dict[tuple[str, int], list[tuple[float, float]]] = defaultdict(list)
    ratio_key: dict[tuple[str, int], list[tuple[float, float]]] = defaultdict(list)
    for d in train:
        by_key[(d["cls"], d["b"])].append((d["speed"], d["len"]))
        if d["free"] > 5:
            ratio_key[(d["cls"], d["b"])].append(
                (d["speed"] / d["free"], d["len"])
            )

    def weighted_median(vals: list[tuple[float, float]]) -> float:
        vals = sorted(vals)
        total = sum(w for _, w in vals)
        acc = 0.0
        for v, w in vals:
            acc += w
            if acc >= total / 2:
                return v
        return vals[-1][0]

    class_prior = {k: weighted_median(v) for k, v in by_key.items()}
    class_ratio = {k: weighted_median(v) for k, v in ratio_key.items()}

    # احتياط: وسيط الصنف عبر كل الشرائح إن غابت الشريحة.
    by_cls: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for d in train:
        by_cls[d["cls"]].append((d["speed"], d["len"]))
    cls_any = {k: weighted_median(v) for k, v in by_cls.items()}

    errs_free: list[float] = []
    errs_prior: list[float] = []
    errs_ratio: list[float] = []
    hit = {"exact_bucket": 0, "class_any": 0, "none": 0}

    for d in test:
        actual = d["speed"]
        errs_free.append((d["free"] - actual) / actual * 100)

        prior = class_prior.get((d["cls"], d["b"]))
        if prior is not None:
            hit["exact_bucket"] += 1
        else:
            prior = cls_any.get(d["cls"])
            if prior is not None:
                hit["class_any"] += 1
            else:
                hit["none"] += 1
                prior = d["free"]
        errs_prior.append((prior - actual) / actual * 100)

        # نموذج النسبة: نسبة الأداء × السرعة الحرة لهذا المقطع.
        r = class_ratio.get((d["cls"], d["b"]))
        r_pred = r * d["free"] if r is not None else prior
        errs_ratio.append((r_pred - actual) / actual * 100)

    def report(name: str, errs: list[float]) -> dict:
        a = sorted(abs(e) for e in errs)
        n = len(a)
        return {
            "name": name,
            "median": statistics.median(a),
            "mean": statistics.mean(a),
            "p75": a[int(n * 0.75)],
            "p90": a[int(n * 0.90)],
            "bias": statistics.median(errs),
        }

    r_free = report("سرعة حرة (OSM)", errs_free)
    r_prior = report("أولوية مطلقة", errs_prior)
    r_ratio = report("نسبة × سرعة حرة", errs_ratio)

    print(f"\n{'الأساس':<22} {'وسيط':>7} {'متوسط':>7} {'p75':>7} {'p90':>7} {'تحيز':>7}")
    print("─" * 64)
    for r in (r_free, r_prior, r_ratio):
        print(
            f"{r['name']:<22} {r['median']:>6.1f}% {r['mean']:>6.1f}% "
            f"{r['p75']:>6.1f}% {r['p90']:>6.1f}% {r['bias']:>+6.1f}%"
        )

    print("\n── مصدر الأولوية")
    print(f"   شريحة محددة      {hit['exact_bucket']:>6}")
    print(f"   وسيط الصنف كله   {hit['class_any']:>6}")
    print(f"   لا شيء (سرعة حرة) {hit['none']:>6}")

    gain = 1 - r_ratio["median"] / r_free["median"]
    print(f"\n── الحكم: نسبة الأداء تحسّن الخطأ على السرعة الحرة بمقدار {gain * 100:.0f}%")
    print(f"   p90: {r_free['p90']:.0f}% → {r_prior['p90']:.0f}% (مطلق) → {r_ratio['p90']:.0f}% (نسبة)")
    if r_ratio["median"] <= 30.0:
        print(f"   ✓ خطأ {r_ratio['median']:.1f}% على مقاطع لم تُقس — مقبول")
        return 0
    print(f"   ! خطأ {r_ratio['median']:.1f}% — يحتاج تحسيناً")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
