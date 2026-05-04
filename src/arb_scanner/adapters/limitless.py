"""Limitless Exchange adapter — public market data, no auth.

Docs: https://docs.limitless.exchange/api-reference/introduction
Pulls `/markets/active`. Each market exposes `prices` as a `[yes, no]` array of
floats already in [0, 1].
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Literal

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

API = "https://api.limitless.exchange"

# Limitless titles with "N+ total {metric}?" mean "N or more {metric}".
# Translated to standard sportsbook line: Over (N-1).5 {metric}.
# We surface that as a tag and as a `totals` kind so the matcher does NOT
# pair them with moneyline markets (3+ goals !=  match_winner).
_TOTALS_RE = re.compile(
    r"\b(?P<n>\d+)\+\s*(?:total\s+)?"
    r"(?P<metric>goals?|corners?|cards?|points?|rebounds?|assists?|"
    r"strikeouts?|hits?|runs?|threes?|three\s*pointers?|tries|fouls?)\b",
    re.IGNORECASE,
)
# Markets that aren't full-event yes/no — e.g. "Player X to score a goal",
# "match to go to extra time", "Y to start" — are legitimate Limitless
# contracts but conflate badly with moneyline markets that share team
# names. Mark them `kind="other"` so the matcher leaves them alone.
_PROP_HINTS = (
    "to score",
    "first goal",
    "anytime goalscorer",
    "anytime scorer",
    "first to score",
    "to be sent off",
    "to assist",
    "hat-trick",
    "hat trick",
    "extra time",
    "penalty",
    "to start",
    "to make",
    "to complete",
    "to have more",
    "diving save",
    "park the bus",
    "possession",
    "yellow card",
    "red card",
    "clean sheet",
    "both teams to score",
    "btts",
    "to win penalty",
    "shots on target",
    "sot",
)
# Most Limitless event-level markets read "Team A vs Team B: …?" — those are
# moneyline-style yes/no. We want them paired only with moneyline markets.
_MATCH_RE = re.compile(r"\b\w[\w'.\- ]+\s+vs\s+\w[\w'.\- ]+", re.IGNORECASE)


def _classify_market(title: str) -> tuple[Literal["binary", "match_winner", "totals", "other"], list[str]]:
    """Classify a Limitless title.

    Returns (kind, extra_tags). The extra tags carry the parsed "Over X.5"
    line for totals so a future totals-aware matcher can pair them across
    venues at the correct line.
    """
    low = title.lower()
    tot = _TOTALS_RE.search(low)
    if tot:
        n = int(tot.group("n"))
        metric = tot.group("metric").lower().rstrip("s")
        # "3+ goals" wins on >=3 goals → equivalent sportsbook line is Over (n-1).5
        line = max(0, n - 1) + 0.5
        return "totals", [f"totals_line:over_{line:g}_{metric}"]
    if any(h in low for h in _PROP_HINTS):
        return "other", ["prop"]
    if _MATCH_RE.search(low):
        return "match_winner", []
    return "binary", []


def _parse_expiration(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is None:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _extract_prices(prices: object) -> tuple[float, float] | None:
    """Limitless returns prices as [yes, no] (sometimes already 0..1, sometimes %)."""
    if not isinstance(prices, list) or len(prices) < 2:
        return None
    try:
        yp = float(prices[0])
        np_ = float(prices[1])
    except (TypeError, ValueError):
        return None
    if yp > 1.5 or np_ > 1.5:  # "in cents"
        yp /= 100.0
        np_ /= 100.0
    if not (0.001 < yp < 0.999) or not (0.001 < np_ < 0.999):
        return None
    return yp, np_


def _is_uninitiated(yp: float, np_: float, volume: float) -> bool:
    """Detect Limitless markets that are showing placeholder 50/50 odds.

    Limitless returns `[50, 50]` (or `[0.5, 0.5]`) for AMM markets that
    have not yet had a single trade. These conflate badly with active
    Kalshi/Polymarket markets covering the same teams and produce
    impressive-looking but fake arbs (the most common one we saw was
    "Arsenal vs Atletico extra time" @ 50/50 paired with Kalshi's
    18% / 82% Atletico-to-win line, "ROI" 47%).

    We flag them as uninitiated when:
      - both legs sit within ±0.03 of 0.5 (overround ≈ 0%, no real edge), AND
      - the market reports zero volume so far.
    """
    near_fifty = abs(yp - 0.5) < 0.03 and abs(np_ - 0.5) < 0.03
    return near_fifty and volume <= 0.0


class LimitlessAdapter(Adapter):
    id = "limitless"
    domains = ("prediction",)

    async def _fetch_page(self, path: str, params: dict) -> list[dict]:
        try:
            r = await self.client.get(f"{API}{path}", params=params, timeout=15.0)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.debug("limitless %s error: %s", path, e)
            return []
        items = data.get("data") if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

    async def fetch_markets(self) -> list[NormalizedMarket]:
        markets: list[NormalizedMarket] = []
        # Limitless paginates by `page` (1-indexed) and caps `limit` at 25.
        items: list[dict] = []
        for page in range(1, 11):  # up to 250 markets
            entries = await self._fetch_page(
                "/markets/active", {"limit": 25, "page": page}
            )
            if not entries:
                break
            items.extend(entries)
            if len(entries) < 25:
                break

        for m in items:
            try:
                title = str(m.get("title") or m.get("proxyTitle") or "").strip()
                if not title:
                    continue
                prices = _extract_prices(m.get("prices"))
                if prices is None:
                    continue
                yp, np_ = prices

                start_time = _parse_expiration(m.get("expirationDate") or m.get("deadline"))
                # `volumeFormatted` is already in human units (USDC). Fall
                # back to the raw `volume` field (atomic units, 1e6 = 1 USDC).
                vol_raw = m.get("volumeFormatted")
                if isinstance(vol_raw, (int, float)):
                    volume_usd = float(vol_raw)
                else:
                    raw = m.get("volume")
                    volume_usd = float(raw) / 1e6 if isinstance(raw, (int, float)) else 0.0
                if _is_uninitiated(yp, np_, volume_usd):
                    continue
                liquidity = volume_usd
                slug = m.get("slug") or m.get("stableSlug")
                url = f"https://limitless.exchange/markets/{slug}" if slug else None

                kind, extra_tags = _classify_market(title)
                tags = [t for t in (m.get("tags") or []) if isinstance(t, str)]
                tags.extend(extra_tags)

                markets.append(
                    NormalizedMarket(
                        venue=self.id,
                        venue_market_id=str(m.get("id") or slug or ""),
                        title=title,
                        kind=kind,
                        domain="prediction",
                        outcomes=[
                            Outcome(name="Yes", decimal_odds=1.0 / yp),
                            Outcome(name="No", decimal_odds=1.0 / np_),
                        ],
                        start_time=start_time,
                        liquidity_usd=liquidity,
                        tags=tags,
                        url=url,
                    )
                )
            except Exception as e:
                logger.debug("limitless skip market: %s", e)
                continue

        logger.info("limitless: %d markets", len(markets))
        return markets
