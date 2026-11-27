"""تجربة أولويات أفضل من «وسيط السرعة المطلقة للصنف».

**المشكلة في الأولوية الحالية:** تأخذ وسيط السرعة المطلقة لكل (صنف، شريحة).
لكن مقطعاً سكنياً سرعته الحرة 40 كم/س ومقطعاً آخر سرعته الحرة 60 كم/س
يتصرفان بشكل مختلف تماماً، وكلاهما «residential». الوسيط المطلق يخلط بينهما.

**البديل:** نسبة الأداء — `السرعة الفعلية ÷ السرعة الحرة للمقطع نفسه`.
هذه كمية بلا وحدة تصف «كيف يتصرف هذا الشارع نسبةً إلى طبيعته»، فتنطبق
على مقطع لم نمشِ عليه إذا عرفنا سرعته الحرة من OSM.

ثلاثة نماذج تُقارن على نفس الحجز المكاني:
1. وسيط السرعة المطلقة (الحالي).
2. نسبة الأداء × السرعة الحرة للمقطع.
3. نسبة الأداء × السرعة الحرة، مع تفصيل الصنف.

التشغيل: python scripts/prior_experiment.py
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC
from zoneinfo import ZoneInfo

from sqlalchemy import text

from zahma.db import session_scope

ALGIERS = ZoneInfo("Africa/Algiers")
PAIR_RE = __import__("re").compile(r"pair=(\d+)")


def bucket_of(ts) -> int:
    local = ts.astimezone(ALGIERS)
    return local.hour * 4 + local.minute // 15


def load() -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT s.segment_id, s.speed_kmh, s.ts_utc,
                       sg.road_class, sg.length_m, sg.speed_free_kmh, s.raw_ref
                FROM samples s
                JOIN segments sg ON sg.seg_id = s.segment_id
                WHERE s.source = 'mapbox' AND s.speed_kmh BETWEEN 3 AND 130
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
        free = float(r["speed_free_kmh"])
        if free <= 5:
            continue
        out.append(
            {
                "seg": int(r["segment_id"]),
                "speed": float(r["speed_kmh"]),
                "b": bucket_of(ts),
                "cls": r["road_class"],
                "pair": int(m.group(1)),
                "len": float(r["length_m"]),
                "free": free,
            }
        )
    return out


def wmedian(vals: list[tuple[float, float]]) -> float:
    vals = sorted(vals)
    total = sum(w for _, w in vals)
    acc = 0.0
    for v, w in vals:
        acc += w
        if acc >= total / 2:
            return v
    return vals[-1][0]


def main() -> int:
    data = load()
    pairs = sorted({d["pair"] for d in data})
    train_p = {p for p in pairs if p % 2 == 0}
    test_p = set(pairs) - train_p

    train = [d for d in data if d["pair"] in train_p]
    train_segs = {d["seg"] for d in train}
    test = [d for d in data if d["pair"] in test_p and d["seg"] not in train_segs]

    print(f"تدريب {len(train):,}  |  اختبار {len(test):,} (مقاطع لم تُقس)\n")

    # 1) وسيط السرعة المطلقة لكل (صنف، شريحة)
    abs_key: dict[tuple[str, int], list[tuple[float, float]]] = defaultdict(list)
    # 2) وسيط نسبة الأداء لكل (صنف، شريحة)
    ratio_key: dict[tuple[str, int], list[tuple[float, float]]] = defaultdict(list)
    # 3) وسيط نسبة الأداء لكل شريحة فقط (بلا صنف) — للمقارنة
    ratio_all: dict[int, list[tuple[float, float]]] = defaultdict(list)

    for d in train:
        w = d["len"]
        abs_key[(d["cls"], d["b"])].append((d["speed"], w))
        ratio_key[(d["cls"], d["b"])].append((d["speed"] / d["free"], w))
        ratio_all[d["b"]].append((d["speed"] / d["free"], w))

    abs_prior = {k: wmedian(v) for k, v in abs_key.items()}
    ratio_prior = {k: wmedian(v) for k, v in ratio_key.items()}
    ratio_b = {k: wmedian(v) for k, v in ratio_all.items()}

    # احتياط على مستوى الصنف كله
    abs_cls: dict[str, list[tuple[float, float]]] = defaultdict(list)
    ratio_cls: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for d in train:
        abs_cls[d["cls"]].append((d["speed"], d["len"]))
        ratio_cls[d["cls"]].append((d["speed"] / d["free"], d["len"]))
    abs_cls_m = {k: wmedian(v) for k, v in abs_cls.items()}
    ratio_cls_m = {k: wmedian(v) for k, v in ratio_cls.items()}

    models: dict[str, list[float]] = defaultdict(list)

    for d in test:
        actual = d["speed"]

        # نموذج 1: مطلق
        p1 = abs_prior.get((d["cls"], d["b"])) or abs_cls_m.get(d["cls"], d["free"])
        models["1. وسيط مطلق (الحالي)"].append((p1 - actual) / actual * 100)

        # نموذج 2: نسبة × سرعة حرة
        r2 = ratio_prior.get((d["cls"], d["b"]))
        if r2 is None:
            r2 = ratio_cls_m.get(d["cls"], 1.0)
        p2 = r2 * d["free"]
        models["2. نسبة × سرعة حرة"].append((p2 - actual) / actual * 100)

        # نموذج 3: نسبة على مستوى الشريحة بلا صنف
        r3 = ratio_b.get(d["b"], 1.0)
        p3 = r3 * d["free"]
        models["3. نسبة بلا صنف"].append((p3 - actual) / actual * 100)

        # نموذج 4: سرعة حرة (خط الأساس)
        models["4. سرعة حرة"].append((d["free"] - actual) / actual * 100)

    print(f"{'النموذج':<26} {'وسيط':>7} {'متوسط':>7} {'p75':>7} {'p90':>7} {'تحيز':>7}")
    print("─" * 68)
    best = None
    for name, errs in models.items():
        a = sorted(abs(e) for e in errs)
        n = len(a)
        med = statistics.median(a)
        print(
            f"{name:<26} {med:>6.1f}% {statistics.mean(a):>6.1f}% "
            f"{a[int(n*0.75)]:>6.1f}% {a[int(n*0.90)]:>6.1f}% "
            f"{statistics.median(errs):>+6.1f}%"
        )
        if name.startswith(("1", "2", "3")) and (best is None or med < best[1]):
            best = (name, med)

    print(f"\nالأفضل: {best[0]} بخطأ {best[1]:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
