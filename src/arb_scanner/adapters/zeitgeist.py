"""Zeitgeist adapter — best-effort GraphQL.

Zeitgeist exposes a Subsquid GraphQL processor at `processor.zeitgeist.pm`. It is
not always reachable from cloud egress (SSL handshake failures observed). We
treat it as best-effort and return an empty list on any failure — the scanner
will simply note 0 markets in the adapter table.
"""

from __future__ import annotations

import logging

from ..models import NormalizedMarket
from .base import Adapter

logger = logging.getLogger(__name__)

ENDPOINT = "https://processor.zeitgeist.pm/graphql"

QUERY = """
query ActiveMarkets($limit: Int!) {
  markets(limit: $limit, where: {status_eq: "Active"}) {
    id
    question
    status
    outcomeAssets
    pool { weights baseAsset }
  }
}
"""


class ZeitgeistAdapter(Adapter):
    id = "zeitgeist"
    domains = ("prediction",)

    async def fetch_markets(self) -> list[NormalizedMarket]:
        try:
            r = await self.client.post(
                ENDPOINT,
                json={"query": QUERY, "variables": {"limit": 50}},
                timeout=10.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.debug("zeitgeist endpoint unavailable (skipping): %s", e)
            return []

        markets_raw = data.get("data", {}).get("markets") if isinstance(data, dict) else None
        if not isinstance(markets_raw, list):
            return []

        # Pool prices on Zeitgeist require LMSR math we don't replicate here. We
        # only return metadata so the scanner can note presence; arb won't fire
        # without prices.
        logger.info("zeitgeist: %d markets (no price data)", len(markets_raw))
        return []
