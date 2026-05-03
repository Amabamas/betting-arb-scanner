"""CLI entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.live import Live

from .config import load_settings
from .scanner import scan_once
from .ui import render

app = typer.Typer(add_completion=False, help="Cross-venue betting arbitrage scanner")
console = Console()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _apply_overrides(
    settings,
    interval: float | None,
    min_roi: float | None,
    venues: str | None,
    domain: str | None,
) -> None:
    if interval is not None:
        settings.scanner_interval_s = interval
    if min_roi is not None:
        settings.scanner_min_roi = min_roi
    if venues is not None:
        settings.scanner_venues = venues
    if domain is not None:
        settings.scanner_domain = domain  # type: ignore[assignment]


@app.command()
def main(
    once: Annotated[bool, typer.Option("--once", help="Run a single scan and exit")] = False,
    serve: Annotated[
        bool,
        typer.Option("--serve", help="Launch the web dashboard instead of the CLI"),
    ] = False,
    host: Annotated[str, typer.Option("--host", help="Web bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Web bind port")] = 8000,
    interval: Annotated[
        float | None,
        typer.Option("--interval", help="Override poll interval in seconds"),
    ] = None,
    min_roi: Annotated[
        float | None,
        typer.Option("--min-roi", help="Override min ROI (e.g. 0.01 = 1%)"),
    ] = None,
    venues: Annotated[
        str | None,
        typer.Option("--venues", help="Comma-separated adapter ids to enable"),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option("--domain", help="sport | prediction | hybrid"),
    ] = None,
) -> None:
    """Run the scanner. By default keeps polling and printing to the terminal.

    Use ``--serve`` to start the web dashboard instead.
    """
    settings = load_settings()
    _apply_overrides(settings, interval, min_roi, venues, domain)
    _configure_logging(settings.scanner_log_level)

    if serve:
        import uvicorn

        from .web import create_app

        fastapi_app = create_app(settings)
        console.print(
            f"[bold cyan]arb-scanner dashboard[/]: "
            f"open [link=http://{host}:{port}]http://{host}:{port}[/]"
        )
        uvicorn.run(
            fastapi_app, host=host, port=port, log_level=settings.scanner_log_level.lower()
        )
        return

    asyncio.run(_run(settings, once=once))


async def _run(settings, once: bool) -> None:
    stop_event = asyncio.Event()

    def _request_stop(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(getattr(signal, sig_name), _request_stop)

    async with httpx.AsyncClient(
        headers={"User-Agent": "betting-arb-scanner/0.1"},
        timeout=httpx.Timeout(20.0, connect=10.0),
    ) as client:
        if once:
            result = await scan_once(client, settings)
            console.print(render(result))
            return

        with Live(console=console, refresh_per_second=4, transient=False) as live:
            while not stop_event.is_set():
                try:
                    result = await scan_once(client, settings)
                    live.update(render(result))
                except Exception:
                    logging.exception("scan_once crashed")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=settings.scanner_interval_s)
                except TimeoutError:
                    continue


if __name__ == "__main__":
    app()
