"""2-way arbitrage detection.

For two outcomes A and B that together cover the entire outcome space (e.g. Yes/No
on a binary prediction market, or Home/(Draw+Away) → not applicable here, only true
2-way; in 3-way 1X2 we approximate by treating each outcome as binary against
"anything else" only when the opposite venue offers exactly that opposing combined
quote, which most sportsbooks do not — so this module focuses on true binary 2-way).

Math:
    p_A = 1 / odds_A
    p_B = 1 / odds_B
    overround = p_A + p_B
    arb iff overround < 1
    ROI = 1 / overround - 1
    Stake split for total stake S, equal payout regardless of side:
        stake_A = S * p_A / overround
        stake_B = S * p_B / overround
        payout  = S / overround
"""

from __future__ import annotations

from itertools import combinations

from .matching import title_similarity
from .models import ArbOpportunity, NormalizedMarket, Outcome


def _opposite_side(name: str) -> str | None:
    """Map a 2-way outcome name to its opposite where it's unambiguous."""
    n = name.strip().lower()
    if n in {"yes", "y", "true", "выиграет"}:
        return "no"
    if n in {"no", "n", "false", "не выиграет"}:
        return "yes"
    if n in {"over", "o"}:
        return "under"
    if n in {"under", "u"}:
        return "over"
    if n in {"home", "1"}:
        return "away"
    if n in {"away", "2"}:
        return "home"
    return None


def is_binary_pair(market: NormalizedMarket) -> tuple[Outcome, Outcome] | None:
    """Return (yes, no) outcomes if the market is 2-way."""
    if market.kind not in {"binary", "totals", "match_winner"}:
        return None
    if len(market.outcomes) != 2:
        return None
    a, b = market.outcomes
    return (a, b)


def _stake_split(odds_a: float, odds_b: float, total: float = 100.0) -> tuple[float, float, float]:
    p_a = 1.0 / odds_a
    p_b = 1.0 / odds_b
    overround = p_a + p_b
    stake_a = total * p_a / overround
    stake_b = total * p_b / overround
    payout = total / overround
    return stake_a, stake_b, payout


def _find_outcome(outcomes: list[Outcome], name: str) -> Outcome | None:
    target = name.strip().lower()
    for o in outcomes:
        if o.name.strip().lower() == target:
            return o
    return None


def find_arbs_for_pair(
    market_a: NormalizedMarket,
    market_b: NormalizedMarket,
    min_roi: float,
    min_liquidity: float,
) -> list[ArbOpportunity]:
    """Find 2-way arbs between two already-matched markets on different venues."""
    if market_a.venue == market_b.venue:
        return []

    pair_a = is_binary_pair(market_a)
    pair_b = is_binary_pair(market_b)
    if pair_a is None or pair_b is None:
        return []

    opps: list[ArbOpportunity] = []
    for side_a in pair_a:
        opposite = _opposite_side(side_a.name)
        if opposite is None:
            continue
        side_b = _find_outcome(list(pair_b), opposite)
        if side_b is None:
            continue

        p_a = 1.0 / side_a.decimal_odds
        p_b = 1.0 / side_b.decimal_odds
        overround = p_a + p_b
        if overround >= 1.0:
            continue
        roi = 1.0 / overround - 1.0
        if roi < min_roi:
            continue

        # Liquidity floor: take min of the two; treat 0 as unbounded
        avail_a = side_a.available_usd if side_a.available_usd > 0 else float("inf")
        avail_b = side_b.available_usd if side_b.available_usd > 0 else float("inf")
        liquidity = min(avail_a, avail_b)
        if liquidity < min_liquidity and liquidity != float("inf"):
            continue

        stake_a, stake_b, payout = _stake_split(side_a.decimal_odds, side_b.decimal_odds)
        liquidity_for_record = 0.0 if liquidity == float("inf") else liquidity

        opps.append(
            ArbOpportunity(
                domain=market_a.domain,
                title_a=market_a.title,
                title_b=market_b.title,
                venue_a=market_a.venue,
                venue_b=market_b.venue,
                side_a=side_a.name,
                side_b=side_b.name,
                odds_a=side_a.decimal_odds,
                odds_b=side_b.decimal_odds,
                p_a=p_a,
                p_b=p_b,
                overround=overround,
                roi=roi,
                stake_a=stake_a,
                stake_b=stake_b,
                payout=payout,
                liquidity_usd=liquidity_for_record,
                start_time=market_a.start_time or market_b.start_time,
                url_a=market_a.url,
                url_b=market_b.url,
            )
        )
    return opps


def find_arbs_in_group(
    matched_group: list[NormalizedMarket],
    min_roi: float,
    min_liquidity: float,
    pairwise_title_threshold: int = 85,
) -> list[ArbOpportunity]:
    """All 2-way arbs across markets that the matcher decided refer to the same event.

    The greedy clusterer chains matches transitively (A~B, B~C ⇒ {A, B, C}), so
    we enforce a stricter pairwise title similarity here before treating any
    two markets as the same event for arb purposes.
    """
    opps: list[ArbOpportunity] = []
    for a, b in combinations(matched_group, 2):
        if a.venue == b.venue:
            continue
        if title_similarity(a.title, b.title) < pairwise_title_threshold:
            continue
        opps.extend(find_arbs_for_pair(a, b, min_roi, min_liquidity))
    return opps
