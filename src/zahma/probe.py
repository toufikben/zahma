"""المرحلة 0 — تجربة الحسم.

السؤال الوحيد: هل لدى Mapbox/TomTom بيانات حركة حقيقية للجزائر؟

لماذا هذه الخطوة أولاً:
إن أظهر profile `driving-traffic` نفس مدة `driving`، فلا توجد بيانات
حركة — والمنتج كله مبني على رمل. نعرف ذلك في دقائق، لا في أسابيع.

المعيار:
- Mapbox: فرق ≥ 5% بين driving و driving-traffic ⇒ بيانات حقيقية.
- TomTom: ratio = current/freeflow ≤ 0.85 ⇒ زحمة مرصودة فعلاً.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

from zahma.config import get_settings
from zahma.sources.mapbox import MapboxSource
from zahma.sources.tomtom_flow import TomTomFlowSource
from zahma.sources.tomtom_incidents import TomTomIncidentsSource

console = Console()

# ثلاثة محاور مزدحمة معروفة في العاصمة — نقاط على الطرق الفعلية
PROBES = [
    {
        "name": "الحراش ← وسط العاصمة",
        "origin": (36.7200, 3.1400),
        "dest": (36.7705, 3.0589),
        "flow_point": (36.7400, 3.1000),
    },
    {
        "name": "باب الزوار ← وسط العاصمة",
        "origin": (36.7167, 3.1833),
        "dest": (36.7705, 3.0589),
        "flow_point": (36.7400, 3.1200),
    },
    {
        "name": "زرالدة ← وسط العاصمة",
        "origin": (36.7100, 2.8400),
        "dest": (36.7705, 3.0589),
        "flow_point": (36.7400, 2.9500),
    },
]


def run_probe() -> dict:
    s = get_settings()
    out: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "has_mapbox": s.has_mapbox,
        "has_tomtom": s.has_tomtom,
        "results": [],
        "verdict": None,
    }

    if not s.has_mapbox and not s.has_tomtom:
        console.print("[red]✗ لا توجد مفاتيح. ضع MAPBOX_TOKEN و TOMTOM_KEY في .env[/red]")
        out["verdict"] = "no_keys"
        return out

    mb = MapboxSource()
    tt = TomTomFlowSource()

    for p in PROBES:
        row = {"probe": p["name"]}

        if s.has_mapbox:
            r = mb.probe(p["origin"], p["dest"])
            row["mapbox"] = r
        if s.has_tomtom:
            lat, lon = p["flow_point"]
            row["tomtom"] = tt.probe(lat, lon)

        out["results"].append(row)

    # أعطال
    if s.has_tomtom:
        try:
            out["incidents"] = TomTomIncidentsSource().probe()
        except Exception as e:  # noqa: BLE001
            out["incidents"] = {"ok": False, "error": str(e)}

    # ---------- الحكم ----------
    mb_hits = sum(
        1 for r in out["results"]
        if r.get("mapbox", {}).get("has_live_traffic") is True
    )
    tt_hits = sum(
        1 for r in out["results"]
        if r.get("tomtom", {}).get("has_congestion_data") is True
    )

    out["mapbox_hits"] = mb_hits
    out["tomtom_hits"] = tt_hits

    if mb_hits + tt_hits == 0:
        out["verdict"] = "NO_TRAFFIC_DATA"
    elif mb_hits + tt_hits >= 2:
        out["verdict"] = "GOOD"
    else:
        out["verdict"] = "WEAK"

    # ---------- العرض ----------
    t = Table(title=f"المرحلة 0 — فحص بيانات الحركة ({out['timestamp'][:19]} UTC)")
    t.add_column("المحور", style="cyan")
    t.add_column("Mapbox driving", justify="right")
    t.add_column("Mapbox traffic", justify="right")
    t.add_column("الفرق %", justify="right")
    t.add_column("TomTom cur/free", justify="right")
    t.add_column("نسبة", justify="right")

    for r in out["results"]:
        m = r.get("mapbox", {})
        tt_r = r.get("tomtom", {})
        a = m.get("driving", {}).get("duration_s")
        b = m.get("driving-traffic", {}).get("duration_s")
        diff = m.get("diff_pct")
        t.add_row(
            r["probe"],
            f"{a:.0f}s" if a else "—",
            f"{b:.0f}s" if b else "—",
            f"{diff:+.1f}%" if diff is not None else "—",
            f"{tt_r.get('current')}/{tt_r.get('freeflow')}" if tt_r.get("ok") else "—",
            f"{tt_r.get('ratio')}" if tt_r.get("ratio") is not None else "—",
        )
    console.print(t)

    if out.get("incidents", {}).get("ok"):
        inc = out["incidents"]
        console.print(
            f"\n[bold]الأعطال الآن:[/bold] {inc['count']} — {inc.get('by_category')}"
        )
        for smp in inc.get("sample", [])[:5]:
            console.print(f"  • {smp['cat']}: {smp['road']} — {smp['desc']}")
    elif out.get("incidents"):
        console.print(f"\n[yellow]الأعطال: {out['incidents'].get('error')}[/yellow]")

    verdict = out["verdict"]
    if verdict == "GOOD":
        console.print(f"\n[green]✓ بيانات حركة حقيقية مؤكدة ({mb_hits} Mapbox + {tt_hits} TomTom)[/green]")
    elif verdict == "WEAK":
        console.print(f"\n[yellow]! بيانات ضعيفة ({mb_hits} Mapbox + {tt_hits} TomTom) — نكمل بمصدر واحد[/yellow]")
    elif verdict == "NO_TRAFFIC_DATA":
        console.print("\n[red]✗ لا بيانات حركة. المشروع يحتاج إعادة تصميم.[/red]")

    return out


if __name__ == "__main__":
    print(json.dumps(run_probe(), ensure_ascii=False, indent=2, default=str))
