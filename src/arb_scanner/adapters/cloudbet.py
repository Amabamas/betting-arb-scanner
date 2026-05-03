"""Cloudbet adapter — Feed API with X-API-Key header.

Docs: https://docs.cloudbet.com / https://cloudbet.github.io/wiki/en/docs/sports/api/
We pull a configurable set of sports → competitions → events with prices.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

BASE = "https://sports-api.cloudbet.com/pub/v2/odds"

# Limit the universe to most-liquid sports for the PoC.
DEFAULT_SPORTS = ["soccer", "basketball", "tennis", "american-football", "ice-hockey"]


class CloudbetAdapter(Adapter):
    id = "cloudbet"
    domains = ("sport",)
    requires_auth = True

    def has_credentials(self) -> bool:
        return bool(self.settings.cloudbet_api_key)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.settings.cloudbet_api_key or "",
            "Accept": "application/json",
        }

    async def _competitions(self, sport_key: str) -> list[str]:
        try:
            r = await self.client.get(
                f"{BASE}/sports/{sport_key}", headers=self._headers, timeout=15.0
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.debug("cloudbet competitions(%s) error: %s", sport_key, e)
            return []
        keys: list[str] = []
        for cat in data.get("categories", []):
            for comp in cat.get("competitions", []):
                key = comp.get("key")
                if key and comp.get("eventCount", 0) > 0:
                    keys.append(key)
        return keys[:10]  # cap per sport

    async def _competition_markets(self, comp_key: str) -> list[NormalizedMarket]:
        out: list[NormalizedMarket] = []
        try:
            r = await self.client.get(
                f"{BASE}/competitions/{comp_key}", headers=self._headers, timeout=15.0
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.debug("cloudbet competition(%s) error: %s", comp_key, e)
            return out
        for event in data.get("events", []):
            cutoff = event.get("cutoffTime")
            start_time = None
            if isinstance(cutoff, str):
                try:
                    start_time = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
                except ValueError:
                    start_time = None
            if start_time is None:
                continue
            if start_time < datetime.now(UTC):
                continue

            home = event.get("home", {}).get("name") or "Home"
            away = event.get("away", {}).get("name") or "Away"
            title = f"{home} vs {away}"
            event_id = str(event.get("id") or "")
            sport = data.get("sport", {}).get("key") or data.get("sportKey") or ""

            for market_key, market in (event.get("markets") or {}).items():
                # Pull only main 1X2 ("soccer.match_odds" etc.) and 2-way moneylines for PoC
                if not market_key.endswith(".match_odds") and "moneyline" not in market_key:
                    continue
                submarkets = market.get("submarkets") or {}
                main = submarkets.get("period=ft") or next(iter(submarkets.values()), None)
                if not main:
                    continue
                selections = main.get("selections") or []
                outcomes: list[Outcome] = []
                for sel in selections:
                    name = sel.get("outcome") or sel.get("params") or "?"
                    price = sel.get("price")
                    if price is None:
                        continue
                    try:
                        odds = float(price)
                    except (TypeError, ValueError):
                        continue
                    if odds < 1.01:
                        continue
                    pretty = {
                        "home": home,
                        "away": away,
                        "draw": "Draw",
                    }.get(str(name).lower(), str(name))
                    outcomes.append(Outcome(name=pretty, decimal_odds=odds))

                if len(outcomes) < 2:
                    continue
                kind: Literal["binary", "match_winner"] = (
                    "match_winner" if len(outcomes) == 3 else "binary"
                )
                out.append(
                    NormalizedMarket(
                        venue=self.id,
                        venue_market_id=f"{event_id}:{market_key}",
                        title=title,
                        kind=kind,
                        domain="sport",
                        outcomes=outcomes,
                        start_time=start_time,
                        liquidity_usd=0.0,  # Cloudbet doesn't expose stake limits via Feed API
                        sport=str(sport).lower() if sport else None,
                        tags=[market_key],
                        url=f"https://www.cloudbet.com/en/sports/event/{event_id}",
                    )
                )
        return out

    async def fetch_markets(self) -> list[NormalizedMarket]:
        if not self.has_credentials():
            return []
        all_markets: list[NormalizedMarket] = []
        for sport in DEFAULT_SPORTS:
            comps = await self._competitions(sport)
            for comp in comps:
                all_markets.extend(await self._competition_markets(comp))
        logger.info("cloudbet: %d markets", len(all_markets))
        return all_markets
