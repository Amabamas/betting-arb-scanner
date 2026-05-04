"""Limitless title classification + uninitiated-market guard."""

from __future__ import annotations

from arb_scanner.adapters.limitless import (
    _classify_market,
    _extract_prices,
    _is_uninitiated,
)


def test_extra_time_classified_as_other() -> None:
    kind, _ = _classify_market("Arsenal vs Atlético Madrid to go to extra time on May 5")
    assert kind == "other"


def test_player_to_start_classified_as_other() -> None:
    kind, _ = _classify_market("Julián Álvarez to start for Atletico Madrid vs Arsenal on May 5")
    assert kind == "other"


def test_player_to_score_classified_as_other() -> None:
    kind, _ = _classify_market("Bukayo Saka to score in the next match")
    assert kind == "other"


def test_totals_n_plus_goals() -> None:
    kind, tags = _classify_market("Arsenal vs Atletico Madrid: 3+ total goals?")
    assert kind == "totals"
    assert any("over_2.5_goal" in t for t in tags)


def test_match_winner_remains() -> None:
    kind, _ = _classify_market("Arsenal vs Atletico Madrid?")
    assert kind == "match_winner"


def test_pure_yes_no_question_is_binary() -> None:
    kind, _ = _classify_market("Will BTC close above $80k on May 5?")
    assert kind == "binary"


def test_uninitiated_50_50_with_no_volume_rejected() -> None:
    assert _is_uninitiated(0.5, 0.5, 0.0) is True
    assert _is_uninitiated(0.495, 0.505, 0.0) is True


def test_uninitiated_with_volume_kept() -> None:
    # A market that genuinely sits at 50/50 but has had real trading volume
    # should not be treated as uninitiated.
    assert _is_uninitiated(0.5, 0.5, 100.0) is False


def test_uninitiated_with_real_asymmetry_kept() -> None:
    # Even with zero volume, a CLOB-quoted market with a real spread is
    # real (the orderbook just hasn't matched yet).
    assert _is_uninitiated(0.32, 0.68, 0.0) is False


def test_extract_prices_handles_int_pair() -> None:
    # `[50, 50]` integer form (Limitless's placeholder convention) should
    # be parsed to (0.5, 0.5) so the uninitiated check can catch it.
    assert _extract_prices([50, 50]) == (0.5, 0.5)
