"""Monaco Protocol — stub adapter.

Monaco's REST API requires a wallet-signature challenge → JWT exchange before
read access. Implementing the signature flow needs a Solana keypair and is left
out of the initial PoC. Returns no markets so the scanner doesn't crash.
"""

from __future__ import annotations

import logging

from ..models import NormalizedMarket
from .base import Adapter

logger = logging.getLogger(__name__)


class MonacoAdapter(Adapter):
    id = "monaco"
    domains = ("sport",)

    async def fetch_markets(self) -> list[NormalizedMarket]:
        logger.debug("monaco adapter is a stub; returning 0 markets")
        return []
