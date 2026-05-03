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
