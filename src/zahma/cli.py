"""أوامر سطر الأوامر — كل عملية قابلة للتشغيل والتحقق."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.table import Table

from zahma.collect import queue
from zahma.config import get_settings

app = typer.Typer(help="زحمة — أدوات الجمع والتحقق", no_args_is_help=True)
console = Console()


@app.command("init-db")
def init_db() -> None:
    """ينشئ الجداول من sql/001_schema.sql."""
    from pathlib import Path

    from sqlalchemy import text

    from zahma.config import ROOT
    from zahma.db import session_scope

    sql_path = Path(ROOT) / "sql" / "001_schema.sql"
    stmts = sql_path.read_text(encoding="utf-8")
    with session_scope() as s:
        s.execute(text(stmts))
    console.print("[green]✓[/green] schema applied")


@app.command("build-network")
def build_network() -> None:
    """يبني شبكة المقاطع من OSM."""
    from zahma.graph.build import build

    gdf = build()
    console.print(f"[green]✓[/green] {len(gdf):,} segments")


@app.command("pick-corridors")
def pick_corridors() -> None:
    """يستخرج المحاور وأزواج O-D."""
    from zahma.graph.corridors import run

    r = run()
    console.print(f"[green]✓[/green] {len(r['corridors'])} corridors, {len(r['pairs'])} pairs")


@app.command("load-network")
def load_network() -> None:
    """يحمّل الشبكة إلى قاعدة البيانات."""
    from zahma.graph.load import run

    r = run()
    console.print(f"[green]✓[/green] {r}")


@app.command("collect")
def collect(once: bool = typer.Option(True, help="دورة واحدة أم مستمر")):
    """يشغّل المجمّع."""
    from zahma.collect.runner import run_forever

    run_forever(once=once)


@app.command("verify")
def verify(strict: bool = typer.Option(False, help="فشل عند أي تحذير")):
    """تحقق فعلي: يقرأ الصفوف من قاعدة البيانات ويحكم."""
    from zahma.collect.verify import run_verify

    ok = run_verify(strict=strict)
    raise typer.Exit(code=0 if ok else 1)


@app.command("probe")
def probe() -> None:
    """المرحلة 0: هل توجد بيانات حركة حقيقية للجزائر؟

    يقارن Mapbox driving مقابل driving-traffic، ويقرأ TomTom Flow.
    """
    from zahma.probe import run_probe

    run_probe()


@app.command("queue-status")
def queue_status() -> None:
    """حالة الطابور المحلي."""
    st = queue.stats()
    console.print_json(json.dumps(st, ensure_ascii=False))


@app.command("db-check")
def db_check() -> None:
    """فحص الاتصال بقاعدة البيانات."""
    from zahma.db import ping

    console.print_json(json.dumps(ping(), ensure_ascii=False))


@app.command("mock-fill")
def mock_fill(
    days: int = typer.Option(14, help="عدد أيام التاريخ الوهمي"),
    segments: int = typer.Option(400, help="عدد المقاطع المقيسة"),
    pairs: int = typer.Option(40, help="عدد أزواج O-D"),
    step_min: int = typer.Option(60, help="خطوة زمنية بالدقائق"),
):
    """يملأ قاعدة البيانات ببيانات وهمية — لتطوير النموذج والتطبيق."""
    from zahma.collect.mockfill import fill

    r = fill(days=days, step_min=step_min, n_segments=segments, n_pairs=pairs)
    console.print_json(json.dumps(r, ensure_ascii=False))


@app.command("collect-real")
def collect_real(
    pairs: int = typer.Option(20, help="عدد أزواج O-D لكل ساعة"),
    day: str = typer.Option("", help="اليوم YYYY-MM-DD (فارغ = التالي)"),
    hours: str = typer.Option(
        "", help="ساعات مفصولة بفاصلة، مثل 07:30,17:30 (فارغ = الافتراضية)"
    ),
    days: int = typer.Option(1, help="عدد الأيام ابتداءً من --day"),
    dry_run: bool = typer.Option(False, help="لا تكتب في القاعدة"),
) -> None:
    """جمع قياسات حقيقية من Mapbox وإسقاطها على شبكتنا.

    كل ساعة = طلب لكل زوج. الحصة 100,000 شهرياً.
    """
    from datetime import date, timedelta

    from zahma.collect.match import collect

    from datetime import date as _date

    start = date.fromisoformat(day) if day else _date.today()
    # الساعات الافتراضية تغطي 24 ساعة، لا 05:30–21:00 فقط.
    #
    # **العيب الذي أصلحه هذا:** القائمة كانت تتوقف عند 21:00، فلم نُقس
    # أسرع ساعات اليوم إطلاقاً. القياس المباشر أثبت أن 04:00 = 68.2 كم/س
    # مقابل 17:00 = 42.5 — أي أننا كنا نجهل 60% من مدى اليوم، والمنحنى
    # المعروض للمستخدم كان يبدأ من 14.9 دقيقة بدل 12.6.
    #
    # **ولماذا ساعتان ليلاً لا سبع:** المنحنى مسطّح بين 23:59 و05:00
    # (64 → 68 → 66، مدى 4.2 كم/س). سبع ساعات تعني 7× الحصة مقابل صفر
    # معلومة إضافية. الساعتان تحصران النطاق كله.
    hour_list = hours.split(",") if hours else [
        "05:30", "06:30", "07:00", "07:30", "08:00", "08:30",
        "09:00", "10:00", "12:00", "14:00", "16:30", "17:00",
        "17:30", "18:00", "18:30", "19:00", "21:00",
        "23:59", "03:00",
    ]

    total_segs = 0
    total_routes = 0
    for d in range(days):
        cur = start + timedelta(days=d)
        for hh in hour_list:
            r = collect(
                limit_pairs=pairs,
                depart_at=f"{cur}T{hh}",
                dry_run=dry_run,
            )
            total_segs += r.get("segments", 0)
            total_routes += r.get("routes", 0)
            console.print(
                f"{cur} {hh}  segs={r.get('segments', 0):>6}  "
                f"match={r.get('match_rate_pct', 0):>5.1f}%"
            )

    console.print(
        f"\n[bold]الإجمالي:[/bold] {total_segs:,} قياس مقطع، "
        f"{total_routes:,} مسار"
    )


@app.command("rebuild-profiles")
def rebuild_profiles() -> None:
    """يبني ملفات تعريف السرعة + أولوية صنف الطريق من العينات.

    الخطوتان معاً ضروريتان: ملفات التعريف تعطي دقة عالية للمقاطع
    المقيسة، وأولوية الصنف تنقل سلوك الصنف إلى المقاطع غير المقيسة
    (شوارع المدينة) — وبلا الثانية يبقى منحنى الانطلاق مسطّحاً.
    """
    from zahma.predict.profiles import (
        coverage_report,
        quality_report,
        rebuild,
        rebuild_class_profiles,
    )

    seg = rebuild()
    cls = rebuild_class_profiles()
    console.print_json(
        json.dumps({"segment_profiles": seg, "class_profiles": cls}, ensure_ascii=False)
    )
    console.print("\n[bold]جودة ملفات التعريف[/bold]")
    console.print_json(json.dumps(quality_report(), ensure_ascii=False))
    console.print("\n[bold]التغطية حسب صنف الطريق[/bold]")
    for row in coverage_report():
        console.print(
            f"  {row['road_class']:<16} {row['with_profile']:>6}/{row['total']:<8} "
            f"({row['pct']}%)"
        )


@app.command("estimate")
def estimate(
    from_lat: float = typer.Option(..., help="خط عرض الانطلاق"),
    from_lon: float = typer.Option(..., help="طول الانطلاق"),
    to_lat: float = typer.Option(..., help="خط عرض الوصول"),
    to_lon: float = typer.Option(..., help="طول الوصول"),
    at: str = typer.Option("", help="وقت الانطلاق ISO (فارغ = الآن)"),
):
    """يقدّر رحلة الآن أو في وقت محدد — ويعرض أساس كل تقدير."""
    from datetime import datetime

    from zahma.predict.engine import estimate_route

    when = datetime.fromisoformat(at) if at else None
    r = estimate_route(from_lat, from_lon, to_lat, to_lon, when=when)
    console.print(
        f"[bold]{r.minutes:.1f} دقيقة[/bold] (p90 {r.minutes_p90:.1f}) "
        f"ثقة {r.confidence:.2f}"
    )
    console.print(f"أساس التقدير: {r.basis_counts}")
    for w in r.warnings:
        console.print(f"  [yellow]![/yellow] {w}")


@app.command("departure")
def departure(
    from_lat: float = typer.Option(..., help="خط عرض الانطلاق"),
    from_lon: float = typer.Option(..., help="طول الانطلاق"),
    to_lat: float = typer.Option(..., help="خط عرض الوصول"),
    to_lon: float = typer.Option(..., help="طول الوصول"),
    at: str = typer.Option("", help="وقت البداية ISO (فارغ = الآن)"),
    horizon: int = typer.Option(180, help="أفق التوقعات بالدقائق"),
    step: int = typer.Option(15, help="خطوة المنحنى بالدقائق"),
):
    """منحنى الانطلاق — «متى أخرج؟» — قلب المنتج."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from zahma.predict.engine import best_departure, departure_curve

    tz = ZoneInfo("Africa/Algiers")
    now = datetime.fromisoformat(at) if at else None
    curve = departure_curve(
        from_lat, from_lon, to_lat, to_lon, horizon_min=horizon, step_min=step, now=now
    )
    if not curve:
        console.print("[red]تعذّر إيجاد مسار[/red]")
        raise typer.Exit(1)

    base = curve[0].duration_s
    console.print(f"[bold]منحنى الانطلاق ({len(curve)} نقطة)[/bold]")
    for o in curve:
        local = o.depart_at.astimezone(tz)
        bar = "█" * max(1, int(o.duration_s / 60))
        delta = (o.duration_s - base) / 60
        sign = "+" if delta >= 0 else ""
        console.print(
            f"  {local.strftime('%H:%M')}  {o.duration_s / 60:5.1f} د  "
            f"{sign}{delta:5.1f}  ثقة {o.confidence:.2f}  {bar}"
        )

    best = best_departure(curve, min_confidence=0.3)
    if best:
        local = best.depart_at.astimezone(tz)
        save = (base - best.duration_s) / 60
        console.print(
            f"\n[green]أفضل خروج: {local.strftime('%H:%M')} — "
            f"{best.duration_s / 60:.1f} دقيقة (توفير {save:.1f} د)[/green]"
        )
    else:
        console.print("\n[yellow]لا نافذة بثقة كافية — لا نوصي بشيء[/yellow]")


@app.command("router-stats")
def router_stats(
    force: bool = typer.Option(False, help="إعادة بناء المصفوفة من الصفر"),
):
    """أرقام مصفوفة التوجيه — للتحقق في CI."""
    from zahma.predict.router import build_matrix, stats

    if force:
        build_matrix(force=True)
    console.print_json(json.dumps(stats(), ensure_ascii=False))


if __name__ == "__main__":
    app()
