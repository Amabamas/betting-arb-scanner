"""PS3838 adapter — HTTP Basic, requires funded account.

Docs: https://ps3838api.github.io/
We follow the standard sports → leagues → fixtures + odds workflow.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

BASE = "https://api.ps3838.com/v3"

# Sport IDs are stable on Pinnacle/PS3838:
DEFAULT_SPORT_IDS = {
    29: "soccer",
    33: "tennis",
    4: "basketball",
    19: "ice-hockey",
    15: "american-football",
}


class PS3838Adapter(Adapter):
    id = "ps3838"
    domains = ("sport",)
    requires_auth = True

    def has_credentials(self) -> bool:
        return bool(self.settings.ps3838_username and self.settings.ps3838_password)

    @property
    def _headers(self) -> dict[str, str]:
        creds = f"{self.settings.ps3838_username}:{self.settings.ps3838_password}"
        token = base64.b64encode(creds.encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "betting-arb-scanner/0.1",
        }

    async def _leagues(self, sport_id: int) -> list[int]:
        try:
            r = await self.client.get(
                f"{BASE}/leagues",
                params={"sportId": sport_id},
                headers=self._headers,
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.debug("ps3838 leagues(%d) error: %s", sport_id, e)
            return []
        return [int(L["id"]) for L in data.get("leagues", []) if L.get("eventCount", 0) > 0][:25]

    async def _fixtures(self, sport_id: int, league_ids: list[int]) -> dict[int, dict]:
        if not league_ids:
            return {}
        params: list[tuple[str, str | int | float | bool | None]] = [("sportId", sport_id)]
        params.extend(("leagueIds", L) for L in league_ids)
        try:
            r = await self.client.get(
                f"{BASE}/fixtures",
                params=params,
                headers=self._headers,
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.debug("ps3838 fixtures(%d) error: %s", sport_id, e)
            return {}
        events: dict[int, dict] = {}
        for league in data.get("league", []):
            for event in league.get("events", []):
                events[int(event["id"])] = {
                    "home": event.get("home"),
                    "away": event.get("away"),
                    "starts": event.get("starts"),
                    "league_name": league.get("name"),
                }
        return events

    async def _odds(self, sport_id: int, league_ids: list[int]) -> dict[int, list[Outcome]]:
        if not league_ids:
            return {}
        params: list[tuple[str, str | int | float | bool | None]] = [
            ("sportId", sport_id),
            ("oddsFormat", "DECIMAL"),
        ]
        params.extend(("leagueIds", L) for L in league_ids)
        try:
            r = await self.client.get(
                f"{BASE}/odds",
                params=params,
                headers=self._headers,
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.debug("ps3838 odds(%d) error: %s", sport_id, e)
            return {}

        by_event: dict[int, list[Outcome]] = {}
        for league in data.get("leagues", []):
            for event in league.get("events", []):
                event_id = int(event["id"])
                # Take the moneyline period 0 (full match)
                for period in event.get("periods", []):
                    if period.get("number") != 0:
                        continue
                    ml = period.get("moneyline")
                    if not ml:
                        continue
                    outcomes: list[Outcome] = []
                    for side, label in (("home", "home"), ("draw", "Draw"), ("away", "away")):
                        odds = ml.get(side)
                        if odds is None or float(odds) < 1.01:
                            continue
                        outcomes.append(Outcome(name=label, decimal_odds=float(odds)))
                    if outcomes:
                        by_event[event_id] = outcomes
                    break
        return by_event

    async def fetch_markets(self) -> list[NormalizedMarket]:
        if not self.has_credentials():
            return []
        all_markets: list[NormalizedMarket] = []
        for sport_id, sport_label in DEFAULT_SPORT_IDS.items():
            leagues = await self._leagues(sport_id)
            if not leagues:
                continue
            fixtures = await self._fixtures(sport_id, leagues)
            odds_map = await self._odds(sport_id, leagues)
            for event_id, fx in fixtures.items():
                outcomes = odds_map.get(event_id)
                if not outcomes:
                    continue
                home = fx.get("home") or "Home"
                away = fx.get("away") or "Away"
                # Replace placeholder "home"/"away" labels with team names
                pretty: list[Outcome] = []
                for o in outcomes:
                    label = {"home": home, "away": away}.get(o.name, o.name)
                    pretty.append(Outcome(name=label, decimal_odds=o.decimal_odds))
                start_time = None
                starts = fx.get("starts")
                if isinstance(starts, str):
                    try:
                        start_time = datetime.fromisoformat(starts.replace("Z", "+00:00"))
                    except ValueError:
                        start_time = None
                title = f"{home} vs {away}"
                all_markets.append(
                    NormalizedMarket(
                        venue=self.id,
                        venue_market_id=str(event_id),
                        title=title,
                        kind="match_winner" if len(pretty) == 3 else "binary",
                        domain="sport",
                        outcomes=pretty,
                        start_time=start_time,
                        liquidity_usd=0.0,
                        sport=sport_label,
                        tags=[fx.get("league_name", "")],
                        url=f"https://www.ps3838.com/en/sports/event/{event_id}",
                    )
                )
        logger.info("ps3838: %d markets", len(all_markets))
        return all_markets
