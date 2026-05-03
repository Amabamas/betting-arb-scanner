from datetime import UTC, datetime

from arb_scanner.arb import find_arbs_for_pair, find_arbs_in_group
from arb_scanner.models import NormalizedMarket, Outcome


def _market(venue: str, yes_odds: float, no_odds: float) -> NormalizedMarket:
    return NormalizedMarket(
        venue=venue,
        venue_market_id=f"{venue}-1",
        title="Will X happen?",
        kind="binary",
        domain="prediction",
        outcomes=[
            Outcome(name="Yes", decimal_odds=yes_odds),
            Outcome(name="No", decimal_odds=no_odds),
        ],
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_clear_arb_two_way_one_direction() -> None:
    # Yes_a=2.10, No_b=2.10 → arb (5%); the other direction (No_a=1.95 + Yes_b=1.95) is NOT an arb.
    a = _market("polymarket", 2.10, 1.95)
    b = _market("kalshi", 1.95, 2.10)
    opps = find_arbs_for_pair(a, b, min_roi=0.0, min_liquidity=0.0)
    assert len(opps) == 1
    o = opps[0]
    assert (o.side_a, o.side_b) == ("Yes", "No")
    assert 0.04 < o.roi < 0.06
    assert abs(o.stake_a + o.stake_b - 100.0) < 0.01
    # Equal-payout invariant
    assert abs(o.stake_a * o.odds_a - o.stake_b * o.odds_b) < 0.01


def test_clear_arb_two_way_both_directions() -> None:
    # Symmetric favorable odds: Yes_a + No_b AND No_a + Yes_b both arb.
    a = _market("polymarket", 2.10, 2.10)
    b = _market("kalshi", 2.05, 2.05)
    opps = find_arbs_for_pair(a, b, min_roi=0.0, min_liquidity=0.0)
    assert len(opps) == 2
    for o in opps:
        assert 0.03 < o.roi < 0.04


def test_no_arb_when_overround() -> None:
    a = _market("polymarket", 1.85, 1.85)
    b = _market("kalshi", 1.85, 1.85)
    assert find_arbs_for_pair(a, b, min_roi=0.0, min_liquidity=0.0) == []


def test_min_roi_filter() -> None:
    a = _market("polymarket", 2.02, 2.02)  # tiny edge ~ 1%
    b = _market("kalshi", 2.02, 2.02)
    assert find_arbs_for_pair(a, b, min_roi=0.05, min_liquidity=0.0) == []
    opps = find_arbs_for_pair(a, b, min_roi=0.0, min_liquidity=0.0)
    assert opps and opps[0].roi > 0


def test_same_venue_skipped() -> None:
    a = _market("polymarket", 2.10, 2.10)
    b = _market("polymarket", 2.10, 2.10)
    assert find_arbs_for_pair(a, b, min_roi=0.0, min_liquidity=0.0) == []


def test_group_with_three_venues() -> None:
    a = _market("polymarket", 2.10, 1.95)
    b = _market("kalshi", 1.95, 2.10)
    c = _market("limitless", 2.05, 2.05)
    opps = find_arbs_in_group([a, b, c], min_roi=0.0, min_liquidity=0.0)
    # 3 venue pairs * 2 directions each, all should clear since odds are favorable
    assert len(opps) >= 3
