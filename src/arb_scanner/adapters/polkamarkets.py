"""Polkamarkets — stub adapter.

Polkamarkets data lives in EVM smart contracts on Moonriver/Moonbeam/Polygon. A
full read implementation needs an RPC + the polkamarkets-js ABI; this is out of
scope for the initial PoC. Returns no markets so the scanner doesn't crash.
"""

from __future__ import annotations

import logging

from ..models import NormalizedMarket
from .base import Adapter

logger = logging.getLogger(__name__)


class PolkamarketsAdapter(Adapter):
    id = "polkamarkets"
    domains = ("prediction",)

    async def fetch_markets(self) -> list[NormalizedMarket]:
        logger.debug("polkamarkets adapter is a stub; returning 0 markets")
        return []
