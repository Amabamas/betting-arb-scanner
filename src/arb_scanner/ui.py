"""Rich-based CLI rendering."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .scanner import ScanResult


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _fmt_odds(x: float) -> str:
    return f"{x:.3f}"


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = dt - datetime.now(UTC)
    if -3600 < delta.total_seconds() < 3600 * 48:
        if delta.total_seconds() < 0:
            return f"{dt.strftime('%H:%M')} (live)"
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"in {int(delta.total_seconds() // 60)}m"
        if hours < 24:
            return f"in {hours:.1f}h"
    return dt.strftime("%Y-%m-%d %H:%M")


def render(result: ScanResult) -> Group:
    summary_t = Table.grid(padding=(0, 2))
    summary_t.add_column(style="bold")
    summary_t.add_column()
    summary_t.add_row("scanned", f"{len(result.per_adapter)} adapters")
    summary_t.add_row("markets", str(result.total_markets))
    summary_t.add_row("groups", str(result.total_groups))
    summary_t.add_row("opportunities", str(len(result.opps)))
    summary_t.add_row("elapsed", f"{result.elapsed_s:.2f}s")
    summary_t.add_row(
        "now",
        datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )

    adapter_t = Table(title="Adapters", show_header=True, header_style="bold cyan")
    adapter_t.add_column("venue")
    adapter_t.add_column("markets", justify="right")
    adapter_t.add_column("elapsed", justify="right")
    adapter_t.add_column("status")
    for venue, info in sorted(result.per_adapter.items()):
        status = Text("OK", style="green") if not info.get("error") else Text(
            str(info["error"])[:60], style="red"
        )
        adapter_t.add_row(
            venue,
            str(info["count"]),
            f"{info['elapsed_s']:.2f}s",
            status,
        )

    opp_t = Table(
        title="Arbitrage opportunities (sorted by ROI desc)",
        show_header=True,
        header_style="bold cyan",
        show_lines=False,
    )
    opp_t.add_column("ROI", justify="right", style="bold green")
    opp_t.add_column("dom")
    opp_t.add_column("event")
    opp_t.add_column("starts", justify="right")
    opp_t.add_column("A: venue / side / odds")
    opp_t.add_column("B: venue / side / odds")
    opp_t.add_column("stake A", justify="right")
    opp_t.add_column("stake B", justify="right")
    opp_t.add_column("payout", justify="right")

    for o in result.opps:
        opp_t.add_row(
            _fmt_pct(o.roi),
            o.domain[:4],
            o.title_a if len(o.title_a) <= 35 else o.title_a[:32] + "...",
            _fmt_dt(o.start_time),
            f"{o.venue_a}\n{o.side_a} @ {_fmt_odds(o.odds_a)}",
            f"{o.venue_b}\n{o.side_b} @ {_fmt_odds(o.odds_b)}",
            f"${o.stake_a:.2f}",
            f"${o.stake_b:.2f}",
            f"${o.payout:.2f}",
        )

    return Group(
        Panel(summary_t, title="Scan summary", border_style="cyan"),
        adapter_t,
        opp_t,
    )
