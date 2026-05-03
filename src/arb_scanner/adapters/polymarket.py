"""Polymarket adapter — Gamma API (public, no auth).

Docs: https://docs.polymarket.com/api-reference
We pull active, non-closed binary markets and convert the YES price to decimal odds.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"


def _parse_outcomes(raw: dict) -> list[Outcome]:
    names_raw = raw.get("outcomes")
    prices_raw = raw.get("outcomePrices")
    if isinstance(names_raw, str):
        try:
            names = json.loads(names_raw)
        except json.JSONDecodeError:
            return []
    else:
        names = names_raw or []
    if isinstance(prices_raw, str):
        try:
            prices = json.loads(prices_raw)
        except json.JSONDecodeError:
            return []
    else:
        prices = prices_raw or []
    if len(names) != len(prices):
        return []

    outcomes: list[Outcome] = []
    for n, p_str in zip(names, prices, strict=False):
        try:
            p = float(p_str)
        except (TypeError, ValueError):
            continue
        # Polymarket prices are probabilities in [0, 1]. Skip anything pinned at the
        # edges — there's effectively no orderbook on those sides.
        if p <= 0.001 or p >= 0.999:
            continue
        outcomes.append(Outcome(name=str(n), decimal_odds=1.0 / p))
    return outcomes


class PolymarketAdapter(Adapter):
    id = "polymarket"
    domains = ("prediction",)

    async def fetch_markets(self) -> list[NormalizedMarket]:
        markets: list[NormalizedMarket] = []
        offset = 0
        limit = 100
        # Cap pages so we don't drift into stale archived markets.
        for _ in range(5):
            try:
                r = await self.client.get(
                    f"{GAMMA}/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "archived": "false",
                        "limit": str(limit),
                        "offset": str(offset),
                    },
                    timeout=15.0,
                )
                r.raise_for_status()
            except Exception as e:
                logger.warning("polymarket fetch error: %s", e)
                break

            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break

            for m in batch:
                outcomes = _parse_outcomes(m)
                if len(outcomes) < 2:
                    continue
                end_iso = m.get("endDate")
                start_time = None
                if isinstance(end_iso, str):
                    try:
                        start_time = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
                    except ValueError:
                        start_time = None
                liquidity = float(m.get("liquidityNum") or m.get("liquidity") or 0.0)
                tags = []
                tags_field = m.get("tags") or []
                if isinstance(tags_field, list):
                    tags = [str(t.get("label", t)) if isinstance(t, dict) else str(t) for t in tags_field]
                slug = m.get("slug")
                url = f"https://polymarket.com/event/{slug}" if slug else None

                markets.append(
                    NormalizedMarket(
                        venue=self.id,
                        venue_market_id=str(m.get("id") or slug or m.get("conditionId") or ""),
                        title=str(m.get("question") or m.get("title") or "").strip(),
                        kind="binary",
                        domain="prediction",
                        outcomes=outcomes,
                        start_time=start_time,
                        liquidity_usd=liquidity,
                        tags=tags,
                        url=url,
                    )
                )

            if len(batch) < limit:
                break
            offset += limit

        logger.info("polymarket: %d markets", len(markets))
        return markets
