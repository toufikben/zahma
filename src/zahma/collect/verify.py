"""تقرير التحقق — الحكم على الجمع بالأرقام، لا بالانطباع.

المبدأ: لا يُعلن «يعمل» إلا بعد قراءة الصفوف الفعلية.
كل فحص يعيد نتيجة قابلة للفشل، والأمر يفشل إن فشل أي فحص حرج.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from zahma.collect import queue
from zahma.db import session_scope

console = Console()


def _scalar(s, sql: str, **params):
    return s.execute(text(sql), params).scalar()


def run_verify(strict: bool = False) -> bool:
    now = datetime.now(UTC)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, critical: bool = True) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, "critical": critical})

    with session_scope() as s:
        # ---------- الشبكة ----------
        n_seg = _scalar(s, "SELECT COUNT(*) FROM segments")
        add("segments", n_seg > 5000, f"{n_seg:,} segments")

        n_cor = _scalar(s, "SELECT COUNT(*) FROM corridors")
        add("corridors", n_cor >= 10, f"{n_cor} corridors")

        n_pairs = _scalar(s, "SELECT COUNT(*) FROM od_pairs")
        add("od_pairs", n_pairs >= 100, f"{n_pairs} pairs")

        geom_bad = _scalar(
            s, "SELECT COUNT(*) FROM segments WHERE NOT ST_IsValid(geom) OR ST_IsEmpty(geom)"
        )
        add("geometry_valid", geom_bad == 0, f"{geom_bad} invalid geometries")

        # ---------- القياسات ----------
        n_samples = _scalar(s, "SELECT COUNT(*) FROM samples")
        add("samples_exist", n_samples > 0, f"{n_samples:,} samples")

        n_routes = _scalar(s, "SELECT COUNT(*) FROM route_samples")
        add("routes_exist", n_routes > 0, f"{n_routes:,} route samples")

        if n_samples > 0:
            newest = _scalar(s, "SELECT MAX(ts_utc) FROM samples")
            age_min = (now - newest).total_seconds() / 60 if newest else 9999
            add(
                "data_fresh",
                age_min <= 30,
                f"newest sample {age_min:.0f} min old",
                critical=False,
            )

            # قيم مستحيلة
            bad_speed = _scalar(
                s,
                "SELECT COUNT(*) FROM samples WHERE speed_kmh <= 0 OR speed_kmh > 200",
            )
            add("speed_sane", bad_speed == 0, f"{bad_speed} impossible speeds")

            bad_ratio = _scalar(
                s,
                "SELECT COUNT(*) FROM samples WHERE ratio IS NOT NULL AND (ratio <= 0.02 OR ratio > 3)",
            )
            add("ratio_sane", bad_ratio == 0, f"{bad_ratio} impossible ratios")

            # تغطية
            n_measured = _scalar(s, "SELECT COUNT(DISTINCT segment_id) FROM samples")
            cov = n_measured / n_seg * 100 if n_seg else 0
            add("coverage", cov >= 1.0, f"{n_measured:,} segments measured ({cov:.1f}%)", critical=False)

            # تنوع المصادر
            n_src = _scalar(s, "SELECT COUNT(DISTINCT source) FROM samples")
            add("multi_source", n_src >= 1, f"{n_src} sources contributing", critical=False)

        # ---------- الفجوات ----------
        gap_24h = _scalar(
            s,
            "SELECT COUNT(*) FROM collection_gaps WHERE from_ts > now() - interval '24 hours'",
        )
        add("gaps_24h", gap_24h < 20, f"{gap_24h} gaps in last 24h", critical=False)

        # ---------- الصحة ----------
        health = s.execute(
            text(
                "SELECT source, last_ok_ts, consecutive_failures, circuit_open "
                "FROM source_health ORDER BY source"
            )
        ).mappings().all()

    # ---------- الطابور ----------
    qst = queue.stats()
    add("queue_drain", qst["pending"] < 5000, f"{qst['pending']} pending, {qst['dead']} dead", critical=False)

    # ---------- العرض ----------
    t = Table(title="تقرير التحقق — زحمة", show_lines=False)
    t.add_column("فحص", style="cyan", no_wrap=True)
    t.add_column("نتيجة", justify="center")
    t.add_column("تفصيل", style="dim")

    for c in checks:
        mark = "[green]✓[/green]" if c["ok"] else ("[red]✗[/red]" if c["critical"] else "[yellow]![/yellow]")
        t.add_row(c["check"], mark, c["detail"])

    console.print(t)

    if health:
        th = Table(title="صحة المصادر")
        th.add_column("مصدر")
        th.add_column("آخر نجاح")
        th.add_column("فشل متتابع")
        th.add_column("قاطع")
        for h in health:
            th.add_row(
                h["source"],
                h["last_ok_ts"].strftime("%H:%M:%S") if h["last_ok_ts"] else "—",
                str(h["consecutive_failures"]),
                "مفتوح" if h["circuit_open"] else "مغلق",
            )
        console.print(th)

    failed_critical = [c for c in checks if not c["ok"] and c["critical"]]
    failed_any = [c for c in checks if not c["ok"]]

    if failed_critical:
        console.print(f"[red]✗ فشل حرج: {len(failed_critical)}[/red]")
        return False
    if strict and failed_any:
        console.print(f"[yellow]! تحذيرات: {len(failed_any)} (وضع صارم)[/yellow]")
        return False
    if failed_any:
        console.print(f"[yellow]! نجح مع {len(failed_any)} تحذير[/yellow]")
    else:
        console.print("[green]✓ كل الفحوص نجحت[/green]")
    return True
