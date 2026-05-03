"""Limitless Exchange adapter — public market data, no auth.

Docs: https://docs.limitless.exchange/api-reference/introduction
Pulls `/markets/active`. Each market exposes `prices` as a `[yes, no]` array of
floats already in [0, 1].
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

API = "https://api.limitless.exchange"


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
                liquidity = 0.0
                vol = m.get("volumeFormatted") or m.get("volume")
                if isinstance(vol, (int, float)):
                    # `volume` is in raw token units; treat as USD-ish for sorting only.
                    liquidity = float(vol) / 1e6
                slug = m.get("slug") or m.get("stableSlug")
                url = f"https://limitless.exchange/markets/{slug}" if slug else None

                markets.append(
                    NormalizedMarket(
                        venue=self.id,
                        venue_market_id=str(m.get("id") or slug or ""),
                        title=title,
                        kind="binary",
                        domain="prediction",
                        outcomes=[
                            Outcome(name="Yes", decimal_odds=1.0 / yp),
                            Outcome(name="No", decimal_odds=1.0 / np_),
                        ],
                        start_time=start_time,
                        liquidity_usd=liquidity,
                        tags=[t for t in (m.get("tags") or []) if isinstance(t, str)],
                        url=url,
                    )
                )
            except Exception as e:
                logger.debug("limitless skip market: %s", e)
                continue

        logger.info("limitless: %d markets", len(markets))
        return markets
