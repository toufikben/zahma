"""دقة التنبؤ: تقديرنا مقابل قياس Mapbox — على يوم محجوز لم يُتدرَّب عليه.

**لماذا يوم محجوز:** ملفات التعريف تُبنى من قياسات Mapbox نفسها. لو
قارنّا تقديرنا بقياس دخل في بناء الملفات، لكان التقييم دائرياً: نقيس
البيانات على نفسها فنحصل على خطأ شبه صفر لا يعني شيئاً عن المستقبل.
لذلك نبني الملفات من 6 أيام، ونقيس على اليوم السابع.

**ثلاثة أسس تُقارن في نفس الوقت** — هذا ما يكشف قيمة كل طبقة:

1. `freeflow`  — سرعة OSM الحرة. هذا ما يعرفه أي تطبيق خريطة مجاني.
2. `class`     — أولوية صنف الطريق في نفس الشريحة الزمنية.
3. `profile`   — ملف تعريف المقطع نفسه من أيام أخرى.

إن لم يتفوّق `profile` على `class`، فالمنتج لا يضيف شيئاً على المتوقع
من صنف الطريق، والملفات عديمة القيمة. هذا هو الاختبار الحقيقي.

التشغيل: python scripts/accuracy.py [--holdout 2026-12-08]
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import text

from zahma.db import session_scope
from zahma.predict.engine import bucket_15m, estimate_segment
from zahma.predict.profiles import rebuild, rebuild_class_profiles


def load_segments() -> dict[int, dict]:
    """كل المقاطع التي لها قياس في اليوم المحجوز — مع صفاتها."""
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT seg_id, length_m, speed_free_kmh, road_class
                FROM segments
                """
            )
        ).mappings().all()
    return {
        int(r["seg_id"]): {
            "seg_id": int(r["seg_id"]),
            "length_m": float(r["length_m"]),
            "speed_free_kmh": float(r["speed_free_kmh"]),
            "road_class": r["road_class"],
        }
        for r in rows
    }


def load_holdout(day: date) -> list[dict]:
    """قياسات اليوم المحجوز — الحقيقة الأرضية."""
    with session_scope() as s:
        rows = s.execute(
            text(
                """
                SELECT segment_id, speed_kmh, ts_utc
                FROM samples
                WHERE source = 'mapbox'
                  AND speed_kmh BETWEEN 3 AND 130
                  AND (ts_utc AT TIME ZONE 'Africa/Algiers')::date = :d
                """,
            ),
            {"d": day},
        ).mappings().all()
    out = []
    for r in rows:
        ts = r["ts_utc"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        out.append(
            {
                "segment_id": int(r["segment_id"]),
                "actual": float(r["speed_kmh"]),
                "ts": ts,
            }
        )
    return out


def evaluate(
    obs: list[dict], segs: dict[int, dict], mode: str
) -> dict:
    """يقيس خطأ وضع واحد: freeflow / class / profile.

    `mode` يحدّد ما نمرّره للمحرك:
      - freeflow: لا خرائط ⇒ المحرك يرجع للسرعة الحرة.
      - class:    class_map فقط ⇒ يستعمل أولوية الصنف.
      - profile:  prof_map + class_map ⇒ يستعمل ملف المقطع ثم الصنف.
    """
    # خرائط مخزّنة مؤقتاً حسب الشريحة الزمنية — التجميع يقلّل الاستعلامات
    # من واحدة لكل عينة (مئات الآلاف) إلى واحدة لكل شريحة (119).
    cache: dict[tuple[str, int], tuple[dict, dict]] = {}

    def maps_for(dtype: str, b: int) -> tuple[dict, dict]:
        key = (dtype, b)
        if key not in cache:
            from zahma.predict.engine import (
                fetch_class_speeds_bulk,
                fetch_profile_speeds_bulk,
            )

            flags = {
                "is_ramadan": False,
                "is_school": True,
                "is_summer": False,
            }
            if mode == "profile":
                prof = fetch_profile_speeds_bulk(b, dtype, flags)
            else:
                prof = {}
            if mode in ("class", "profile"):
                cls = fetch_class_speeds_bulk(b, dtype, flags)
            else:
                cls = {}
            cache[key] = (prof, cls)
        return cache[key]

    errs: list[float] = []
    basis_count: dict[str, int] = defaultdict(int)

    for o in obs:
        seg = segs.get(o["segment_id"])
        if seg is None:
            continue
        prof_map, class_map = maps_for("WORKDAY", bucket_15m(o["ts"]))
        est = estimate_segment(
            seg,
            when=o["ts"],
            dtype="WORKDAY",
            flags={"is_ramadan": False, "is_school": True, "is_summer": False},
            now=o["ts"],
            live_map={},  # لا قياس حي في التقييم — نتقيّم النموذج لا اللحظة
            prof_map=prof_map if mode == "profile" else {},
            class_map=class_map if mode in ("class", "profile") else None,
        )
        errs.append((est.speed_kmh - o["actual"]) / o["actual"] * 100)
        basis_count[est.basis] += 1

    if not errs:
        return {"n": 0}

    abs_err = sorted(abs(e) for e in errs)

    def pct(p: float) -> float:
        return abs_err[min(len(abs_err) - 1, int(len(abs_err) * p))]

    return {
        "n": len(errs),
        "median_abs": statistics.median(abs_err),
        "mean_abs": statistics.mean(abs_err),
        "p75": pct(0.75),
        "p90": pct(0.90),
        "bias": statistics.median(errs),
        "basis": dict(basis_count),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", default="2026-12-08")
    ap.add_argument("--skip-rebuild", action="store_true")
    args = ap.parse_args()

    holdout = date.fromisoformat(args.holdout)

    if not args.skip_rebuild:
        print(f"── بناء الملفات من كل الأيام ما عدا {holdout}\n")
        r1 = rebuild(sources=("mapbox",), exclude_days=(holdout,))
        r2 = rebuild_class_profiles(sources=("mapbox",))
        print(f"   ملفات المقاطع: {r1['profiles']:,} صفاً، {r1['segments']:,} مقطع")
        print(f"   ملفات الأصناف: {r2['class_profiles']} صفاً، {r2['classes']} صنف\n")

    obs = load_holdout(holdout)
    if not obs:
        print(f"لا قياسات في {holdout}")
        return 1

    segs = load_segments()
    print(f"── {len(obs):,} قياس حقيقي في {holdout} (يوم محجوز)\n")

    results = {}
    for mode, label in (
        ("freeflow", "سرعة حرة (OSM)"),
        ("class", "أولوية الصنف"),
        ("profile", "ملف التعريف + الصنف"),
    ):
        results[mode] = evaluate(obs, segs, mode)

    print(f"{'الأساس':<24} {'وسيط':>7} {'متوسط':>7} {'p75':>7} {'p90':>7} {'تحيز':>7}")
    print("─" * 66)
    for mode, label in (
        ("freeflow", "سرعة حرة (OSM)"),
        ("class", "أولوية الصنف"),
        ("profile", "ملف التعريف + الصنف"),
    ):
        r = results[mode]
        print(
            f"{label:<24} {r['median_abs']:>6.1f}% {r['mean_abs']:>6.1f}% "
            f"{r['p75']:>6.1f}% {r['p90']:>6.1f}% {r['bias']:>+6.1f}%"
        )

    print("\n── تفصيل أساس التقدير (وضع profile)")
    for k, v in sorted(results["profile"]["basis"].items(), key=lambda x: -x[1]):
        print(f"   {k:16} {v:>6}  ({100 * v / results['profile']['n']:.1f}%)")

    base = results["freeflow"]["median_abs"]
    cls = results["class"]["median_abs"]
    prof = results["profile"]["median_abs"]

    print("\n── الحكم")
    print(f"   الصنف يحسّن على السرعة الحرة: {base:.1f}% → {cls:.1f}% "
          f"({(1 - cls / base) * 100:+.0f}%)")
    print(f"   الملف يحسّن على الصنف:      {cls:.1f}% → {prof:.1f}% "
          f"({(1 - prof / cls) * 100:+.0f}%)")

    ok = True
    if prof > 25.0:
        print(f"\n   ✗ خطأ الوسيط {prof:.1f}% أعلى من الحد المقبول 25%")
        ok = False
    if prof >= cls:
        print("\n   ✗ ملفات التعريف لا تضيف شيئاً على أولوية الصنف")
        ok = False

    if ok:
        print(f"\n   ✓ خطأ {prof:.1f}% — النموذج يتفوّق على كلا الأساسين")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
