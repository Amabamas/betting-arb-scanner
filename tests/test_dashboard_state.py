"""Verify the NEW-badge tracking in DashboardState."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from arb_scanner.config import Settings
from arb_scanner.models import ArbOpportunity
from arb_scanner.scanner import ScanResult
from arb_scanner.web import NEW_BADGE_TTL, DashboardState


def _opp(market_a: str, market_b: str) -> ArbOpportunity:
    return ArbOpportunity(
        domain="prediction",
        title_a="t",
        title_b="t",
        venue_a="polymarket",
        venue_b="kalshi",
        market_id_a=market_a,
        market_id_b=market_b,
        side_a="Yes",
        side_b="No",
        odds_a=2.0,
        odds_b=2.5,
        p_a=0.5,
        p_b=0.4,
        overround=0.9,
        roi=0.111,
        stake_a=55.0,
        stake_b=45.0,
        payout=110.0,
        liquidity_usd=1000.0,
        start_time=None,
    )


def _result(opps: list[ArbOpportunity]) -> ScanResult:
    return ScanResult(
        opps=opps, per_adapter={}, total_markets=0, total_groups=0, elapsed_s=0.0
    )


def test_arb_id_is_order_invariant() -> None:
    a = _opp("A", "B")
    b = ArbOpportunity(
        domain="prediction",
        title_a="t",
        title_b="t",
        venue_a="kalshi",
        venue_b="polymarket",
        market_id_a="B",
        market_id_b="A",
        side_a="No",
        side_b="Yes",
        odds_a=2.5,
        odds_b=2.0,
        p_a=0.4,
        p_b=0.5,
        overround=0.9,
        roi=0.111,
        stake_a=45.0,
        stake_b=55.0,
        payout=110.0,
        liquidity_usd=1000.0,
        start_time=None,
    )
    assert a.arb_id == b.arb_id


def test_new_badge_lifecycle() -> None:
    settings = Settings()
    state = DashboardState()

    old = _opp("OLD-A", "OLD-B")
    new = _opp("NEW-A", "NEW-B")

    # Scan 1: only the "old" arb is observed → it shows up as NEW for the
    # first TTL window (which is fine; the user just opened the app).
    state.last_result = _result([old])
    state.record_seen(state.last_result)
    flags = {o["arb_id"]: o["is_new"] for o in state.to_dict(settings)["opps"]}
    assert flags[old.arb_id] is True

    # Backdate the "old" arb past the TTL, then push a scan with both arbs.
    state.first_seen[old.arb_id] = datetime.now(UTC) - NEW_BADGE_TTL - timedelta(seconds=10)
    state.last_result = _result([old, new])
    state.record_seen(state.last_result)
    flags = {o["arb_id"]: o["is_new"] for o in state.to_dict(settings)["opps"]}
    assert flags[old.arb_id] is False
    assert flags[new.arb_id] is True

    # Backdate the "new" arb past the TTL → no NEW flags anywhere.
    state.first_seen[new.arb_id] = datetime.now(UTC) - NEW_BADGE_TTL - timedelta(seconds=10)
    state.last_result = _result([old, new])
    state.record_seen(state.last_result)
    flags = {o["arb_id"]: o["is_new"] for o in state.to_dict(settings)["opps"]}
    assert flags == {old.arb_id: False, new.arb_id: False}
