"""Normalized market data models shared by all adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MarketKind = Literal["binary", "match_winner", "totals", "handicap", "futures", "other"]
Domain = Literal["sport", "prediction"]


class Outcome(BaseModel):
    """A single side of a market — e.g. "Yes" / "No", or a team name."""

    name: str
    # Decimal odds (>= 1.0). For prediction markets we convert price (0..1) to
    # decimal odds via 1/price so that all venues share one representation.
    decimal_odds: float
    # Available stake the venue can absorb at this price, expressed in USD-equivalent.
    # 0 means unknown / unbounded; treated as "infinite" for sportsbook fixed odds.
    available_usd: float = 0.0


class NormalizedMarket(BaseModel):
    """A canonicalised market view used by the matcher and arb engine."""

    venue: str  # adapter id, e.g. "polymarket"
    venue_market_id: str  # adapter-local id (slug, hash, ticker)
    title: str
    kind: MarketKind
    domain: Domain
    outcomes: list[Outcome]
    start_time: datetime | None = None
    liquidity_usd: float = 0.0
    sport: str | None = None  # e.g. "soccer", "tennis"
    tags: list[str] = Field(default_factory=list)
    url: str | None = None  # deep link to the venue page (for the operator)


class ArbOpportunity(BaseModel):
    """A 2-way arb across two venues."""

    domain: Domain
    title_a: str
    title_b: str
    venue_a: str
    venue_b: str
    market_id_a: str = ""  # adapter-local market id on venue A
    market_id_b: str = ""  # adapter-local market id on venue B
    side_a: str  # outcome name on venue A
    side_b: str  # opposing outcome on venue B
    odds_a: float  # decimal odds
    odds_b: float
    p_a: float  # implied probability (1/odds_a)
    p_b: float
    overround: float  # p_a + p_b
    roi: float  # 1/overround - 1
    # Stake split for $100 total
    stake_a: float
    stake_b: float
    payout: float
    liquidity_usd: float  # min(liquidity_a, liquidity_b)
    start_time: datetime | None
    url_a: str | None = None
    url_b: str | None = None

    @property
    def arb_id(self) -> str:
        """Stable identity for this arb pair across scans.

        Hashed over the venues, market ids, and sides — *order-invariant* so
        swapping the A/B legs (which can happen scan-to-scan based on title
        ordering inside a group) doesn't change the id. Used by the dashboard
        to flag freshly-discovered arbs.
        """
        leg_a = (self.venue_a, self.market_id_a, self.side_a.lower())
        leg_b = (self.venue_b, self.market_id_b, self.side_b.lower())
        first, second = sorted([leg_a, leg_b])
        return "|".join([*first, *second])
