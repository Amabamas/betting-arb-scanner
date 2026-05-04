"""BetDEX (Monaco Protocol on Solana) — stub adapter.

BetDEX is the consumer-facing brand; under the hood every market is a Monaco
Protocol PDA on Solana. Market reads need either the Monaco SDK + an RPC node,
or the BetDEX backend's wallet-signed JWT — neither is available without
account onboarding. There is no anonymous public API key flow.

We keep the adapter listed so the dashboard makes the venue's status visible,
but `fetch_markets` returns 0 until someone wires in the on-chain reader.
"""

from __future__ import annotations

import logging

from ..models import NormalizedMarket
from .base import Adapter

logger = logging.getLogger(__name__)


class BetdexAdapter(Adapter):
    id = "betdex"
    domains = ("sport",)

    async def fetch_markets(self) -> list[NormalizedMarket]:
        logger.debug("betdex adapter is a stub; returning 0 markets")
        return []
