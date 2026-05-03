"""FastAPI web dashboard.

Runs the scanner in a background task and serves a single-page Tailwind +
Alpine.js dashboard plus a JSON endpoint that the page polls every interval.

Usage from the CLI:
    arb-scan serve [--host 0.0.0.0 --port 8000]

Open http://localhost:8000 in a browser.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .scanner import ScanResult, scan_once

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


class DashboardState:
    """Holds the most recent scan result + adapter health for the API endpoint."""

    def __init__(self) -> None:
        self.last_result: ScanResult | None = None
        self.last_error: str | None = None
        self.last_started_at: datetime | None = None
        self.last_finished_at: datetime | None = None
        self.scan_count: int = 0

    def to_dict(self, settings: Settings) -> dict[str, Any]:
        result = self.last_result
        if result is None:
            return {
                "ready": False,
                "last_error": self.last_error,
                "last_started_at": _isoformat(self.last_started_at),
                "scan_count": self.scan_count,
                "settings": _settings_dict(settings),
            }
        return {
            "ready": True,
            "last_error": self.last_error,
            "last_started_at": _isoformat(self.last_started_at),
            "last_finished_at": _isoformat(self.last_finished_at),
            "scan_count": self.scan_count,
            "elapsed_s": result.elapsed_s,
            "total_markets": result.total_markets,
            "total_groups": result.total_groups,
            "settings": _settings_dict(settings),
            "per_adapter": [
                {"venue": v, **info} for v, info in result.per_adapter.items()
            ],
            "opps": [
                {
                    "domain": op.domain,
                    "title_a": op.title_a,
                    "title_b": op.title_b,
                    "venue_a": op.venue_a,
                    "venue_b": op.venue_b,
                    "side_a": op.side_a,
                    "side_b": op.side_b,
                    "odds_a": op.odds_a,
                    "odds_b": op.odds_b,
                    "p_a": op.p_a,
                    "p_b": op.p_b,
                    "overround": op.overround,
                    "roi": op.roi,
                    "stake_a": op.stake_a,
                    "stake_b": op.stake_b,
                    "payout": op.payout,
                    "liquidity_usd": op.liquidity_usd,
                    "start_time": _isoformat(op.start_time),
                    "url_a": op.url_a,
                    "url_b": op.url_b,
                }
                for op in result.opps
            ],
        }


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _settings_dict(s: Settings) -> dict[str, Any]:
    return {
        "scanner_interval_s": s.scanner_interval_s,
        "scanner_min_roi": s.scanner_min_roi,
        "scanner_min_liquidity_usd": s.scanner_min_liquidity_usd,
        "scanner_title_threshold": s.scanner_title_threshold,
        "scanner_domain": s.scanner_domain,
        "scanner_venues": s.scanner_venues,
        "scanner_max_opps": s.scanner_max_opps,
    }


async def _scanner_loop(state: DashboardState, settings: Settings, stop: asyncio.Event) -> None:
    """Background task: scans on `scanner_interval_s` and stores result in state."""
    async with httpx.AsyncClient(
        headers={"User-Agent": "betting-arb-scanner/0.1"},
        timeout=httpx.Timeout(20.0, connect=10.0),
    ) as client:
        while not stop.is_set():
            state.last_started_at = datetime.now(UTC)
            try:
                result = await scan_once(client, settings)
                state.last_result = result
                state.last_error = None
            except Exception as exc:
                logger.exception("scan_once failed in background loop")
                state.last_error = str(exc)
            state.last_finished_at = datetime.now(UTC)
            state.scan_count += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.scanner_interval_s)
            except TimeoutError:
                continue


def create_app(settings: Settings) -> FastAPI:
    state = DashboardState()
    stop_event = asyncio.Event()
    background_task: asyncio.Task | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal background_task
        background_task = asyncio.create_task(_scanner_loop(state, settings, stop_event))
        yield
        stop_event.set()
        if background_task:
            background_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await background_task

    app = FastAPI(title="arb-scanner dashboard", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(INDEX_HTML)

    @app.get("/api/scan")
    async def api_scan() -> JSONResponse:
        return JSONResponse(state.to_dict(settings))

    return app
