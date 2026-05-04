"""Drift BET adapter — stub.

Drift BET prediction markets are special perp markets on Solana. As of 2026 the
public Drift Data REST API (`https://data.api.drift.trade`) does NOT expose live
mark prices for these markets — `currentPrice` is consistently empty and
`/stats/markets` returns `[]`. Real-time pricing requires the Drift TS/Python
SDK reading from the Solana DLOB account directly.

We keep the adapter as a no-op so the scanner skeleton supports it; integrators
who need Drift quotes should wire in the SDK separately.
"""

from __future__ import annotations

import logging

from ..models import NormalizedMarket
from .base import Adapter

logger = logging.getLogger(__name__)


class DriftBetAdapter(Adapter):
    id = "drift"
    domains = ("prediction",)

    async def fetch_markets(self) -> list[NormalizedMarket]:
        logger.debug("drift adapter is a stub; needs Solana SDK integration")
        return []
