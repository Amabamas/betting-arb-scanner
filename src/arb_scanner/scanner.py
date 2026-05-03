"""Main scanner loop: fetch markets from all adapters, match, find arbs."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .adapters import ALL_ADAPTERS, Adapter
from .arb import find_arbs_in_group
from .config import Settings
from .matching import group_markets
from .models import ArbOpportunity, NormalizedMarket

logger = logging.getLogger(__name__)


def _build_adapters(client: httpx.AsyncClient, settings: Settings) -> list[Adapter]:
    adapters: list[Adapter] = []
    for cls in ALL_ADAPTERS:
        a = cls(client, settings)
        if not a.domain_enabled():
            continue
        if not a.is_enabled():
            continue
        adapters.append(a)
    return adapters


async def _safe_fetch(adapter: Adapter) -> tuple[str, list[NormalizedMarket], float, str | None]:
    t0 = time.monotonic()
    try:
        ms = await adapter.fetch_markets()
        return adapter.id, ms, time.monotonic() - t0, None
    except Exception as e:
        logger.exception("adapter %s crashed", adapter.id)
        return adapter.id, [], time.monotonic() - t0, str(e)


class ScanResult:
    def __init__(
        self,
        opps: list[ArbOpportunity],
        per_adapter: dict[str, dict[str, object]],
        total_markets: int,
        total_groups: int,
        elapsed_s: float,
    ) -> None:
        self.opps = opps
        self.per_adapter = per_adapter
        self.total_markets = total_markets
        self.total_groups = total_groups
        self.elapsed_s = elapsed_s


async def scan_once(client: httpx.AsyncClient, settings: Settings) -> ScanResult:
    t0 = time.monotonic()
    adapters = _build_adapters(client, settings)
    logger.info("scanning with %d adapters: %s", len(adapters), [a.id for a in adapters])

    results = await asyncio.gather(*[_safe_fetch(a) for a in adapters])

    all_markets: list[NormalizedMarket] = []
    per_adapter: dict[str, dict[str, object]] = {}
    for venue_id, ms, elapsed, err in results:
        per_adapter[venue_id] = {
            "count": len(ms),
            "elapsed_s": round(elapsed, 2),
            "error": err,
        }
        all_markets.extend(ms)

    # The matching pass is CPU-bound (token blocking + rapidfuzz) and on a 25k
    # Kalshi market catalogue takes 100-150 seconds. Run it in a worker thread
    # so the asyncio event loop stays responsive for /api/scan polling.
    opps, groups = await asyncio.to_thread(_match_and_arb, all_markets, settings)

    return ScanResult(
        opps=opps,
        per_adapter=per_adapter,
        total_markets=len(all_markets),
        total_groups=groups,
        elapsed_s=time.monotonic() - t0,
    )


def _match_and_arb(
    all_markets: list[NormalizedMarket], settings: Settings
) -> tuple[list[ArbOpportunity], int]:
    """CPU-bound matching + arb pairing. Runs in a thread executor."""
    sport = [m for m in all_markets if m.domain == "sport"]
    pred = [m for m in all_markets if m.domain == "prediction"]

    sport_groups = group_markets(
        sport,
        title_threshold=settings.scanner_title_threshold,
        time_window_hours=settings.scanner_time_window_hours,
    )
    pred_groups = group_markets(
        pred,
        title_threshold=settings.scanner_title_threshold,
        time_window_hours=settings.scanner_time_window_hours,
    )
    groups = sport_groups + pred_groups

    opps: list[ArbOpportunity] = []
    for g in groups:
        opps.extend(
            find_arbs_in_group(
                g,
                min_roi=settings.scanner_min_roi,
                min_liquidity=settings.scanner_min_liquidity_usd,
            )
        )

    opps.sort(key=lambda o: o.roi, reverse=True)
    return opps[: settings.scanner_max_opps], len(groups)
