"""SX Bet adapter — public REST orderbook (no auth).

Docs: https://docs.sx.bet/
We pull active markets, then fan-out best-odds queries one market at a time
with a small concurrency pool. Batching marketHashes returns HTTP 500 in
practice as of 2026, so we deliberately go single-hash.

`/orders/odds/best` returns `outcomeOnePercentageOdds` and
`outcomeTwoPercentageOdds` — those are the *taker's* probability for that
outcome scaled by 1e20 (per SX docs). We invert each to get decimal odds.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

API = "https://api.sx.bet"
SCALE = 10**20
USDC_BASE_TOKEN = "0x6629Ce1Cf35Cc1329ebB4F63202F3f197b3F050B"  # SX Toronto USDC
MAX_MARKETS = 60
CONCURRENCY = 4


def _parse_market(m: dict, best: dict[str, float]) -> NormalizedMarket | None:
    market_hash = str(m.get("marketHash") or "")
    if not market_hash:
        return None
    p_one = best.get("outcome_one_prob")
    p_two = best.get("outcome_two_prob")
    if p_one is None or p_two is None:
        return None
    if not (0.001 < p_one < 0.999) or not (0.001 < p_two < 0.999):
        return None

    one_team = m.get("teamOneName") or m.get("outcomeOneName")
    two_team = m.get("teamTwoName") or m.get("outcomeTwoName")
    title = (
        f"{one_team} vs {two_team}"
        if one_team and two_team
        else (m.get("outcomeOneName") or "SX market")
    )

    ts_str = m.get("gameTime") or m.get("startDate")
    start_time = None
    if isinstance(ts_str, (int, float)):
        try:
            start_time = datetime.fromtimestamp(int(ts_str), tz=UTC)
        except (ValueError, OSError):
            start_time = None
    elif isinstance(ts_str, str):
        try:
            start_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            start_time = None

    sport = m.get("sportLabel") or m.get("sport")
    one_label = str(one_team or m.get("outcomeOneName") or "Yes")
    two_label = str(two_team or m.get("outcomeTwoName") or "No")

    return NormalizedMarket(
        venue="sxbet",
        venue_market_id=market_hash,
        title=title,
        kind="match_winner" if "vs" in title.lower() else "binary",
        domain="sport" if m.get("sportLabel") else "prediction",
        outcomes=[
            Outcome(name=one_label, decimal_odds=1.0 / p_one),
            Outcome(name=two_label, decimal_odds=1.0 / p_two),
        ],
        start_time=start_time,
        liquidity_usd=0.0,
        sport=str(sport).lower() if sport else None,
        tags=[],
        url=f"https://sx.bet/markets/{market_hash}" if market_hash else None,
    )


class SxBetAdapter(Adapter):
    id = "sxbet"
    domains = ("sport", "prediction")

    async def _fetch_best_odds(self, market_hash: str) -> dict[str, float] | None:
        try:
            r = await self.client.get(
                f"{API}/orders/odds/best",
                params={"marketHashes": market_hash, "baseToken": USDC_BASE_TOKEN},
                timeout=10.0,
            )
            if r.status_code != 200:
                return None
            payload = r.json()
            rows = payload.get("data", {}).get("bestOdds", []) if isinstance(payload, dict) else []
            if not rows:
                return None
            row = rows[0]
            try:
                # percentageOdds in /orders/odds/best is TAKER probability scaled by 1e20.
                p_one_taker = int(row["outcomeOnePercentageOdds"]) / SCALE
                p_two_taker = int(row["outcomeTwoPercentageOdds"]) / SCALE
            except (KeyError, TypeError, ValueError):
                return None
            return {"outcome_one_prob": p_one_taker, "outcome_two_prob": p_two_taker}
        except Exception as e:
            logger.debug("sxbet best-odds %s error: %s", market_hash[:10], e)
            return None

    async def fetch_markets(self) -> list[NormalizedMarket]:
        try:
            r = await self.client.get(f"{API}/markets/active", timeout=15.0)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning("sxbet fetch error: %s", e)
            return []

        all_markets = data.get("data", {}).get("markets") if isinstance(data, dict) else None
        if not isinstance(all_markets, list):
            return []
        # Cap to soccer/tennis/basketball only to keep traffic predictable
        all_markets = [m for m in all_markets if m.get("sportLabel")][:MAX_MARKETS]

        sem = asyncio.Semaphore(CONCURRENCY)

        async def _one(m: dict) -> NormalizedMarket | None:
            mh = str(m.get("marketHash") or "")
            async with sem:
                best = await self._fetch_best_odds(mh)
            if not best:
                return None
            return _parse_market(m, best)

        results = await asyncio.gather(*[_one(m) for m in all_markets])
        markets = [m for m in results if m is not None]
        logger.info("sxbet: %d markets (with quotes)", len(markets))
        return markets
