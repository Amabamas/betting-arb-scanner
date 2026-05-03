from datetime import UTC, datetime, timedelta

from arb_scanner.matching import group_markets, normalize_title, title_similarity
from arb_scanner.models import NormalizedMarket, Outcome


def _m(venue: str, title: str, start: datetime | None, domain: str = "sport") -> NormalizedMarket:
    return NormalizedMarket(
        venue=venue,
        venue_market_id=f"{venue}-{title}",
        title=title,
        kind="binary",
        domain=domain,  # type: ignore[arg-type]
        outcomes=[
            Outcome(name="Yes", decimal_odds=2.0),
            Outcome(name="No", decimal_odds=2.0),
        ],
        start_time=start,
        sport="soccer" if domain == "sport" else None,
    )


def test_normalize_strips_aliases_and_stopwords() -> None:
    assert normalize_title("Manchester United vs Chelsea FC") == normalize_title("Man Utd vs Chelsea")


def test_title_similarity_high_for_aliases() -> None:
    assert title_similarity("Man City vs Liverpool", "Manchester City vs Liverpool FC") >= 90


def test_group_matches_within_time_window() -> None:
    t = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
    a = _m("ps3838", "Manchester United vs Chelsea", t)
    b = _m("cloudbet", "Man Utd vs Chelsea FC", t + timedelta(minutes=10))
    c = _m("sxbet", "Real Madrid vs Barcelona", t)
    groups = group_markets([a, b, c])
    assert any({m.venue for m in g} == {"ps3838", "cloudbet"} for g in groups)


def test_group_skips_outside_window() -> None:
    t = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
    a = _m("ps3838", "Manchester United vs Chelsea", t)
    b = _m("cloudbet", "Manchester United vs Chelsea", t + timedelta(hours=10))
    groups = group_markets([a, b], time_window_hours=2)
    # No multi-venue group should be returned
    assert all(len({m.venue for m in g}) == 1 for g in groups)


def test_group_prediction_markets_no_time_required() -> None:
    a = _m("polymarket", "Will Bitcoin be above $200k by 2026?", None, domain="prediction")
    b = _m("kalshi", "Will BTC exceed 200k in 2026?", None, domain="prediction")
    groups = group_markets([a, b], title_threshold=60)
    assert any({m.venue for m in g} == {"polymarket", "kalshi"} for g in groups)
