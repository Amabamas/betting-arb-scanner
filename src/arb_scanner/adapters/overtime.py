"""Overtime Markets V2 adapter — x-api-key.

Without a key, `https://api.overtime.io/overtime-v2/...` returns 401. We additionally
try a known public read endpoint as a fallback for read-only PoC use.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

PROTECTED = "https://api.overtime.io/overtime-v2/networks/{network}/markets"
NETWORK_OPTIMISM = 10


class OvertimeAdapter(Adapter):
    id = "overtime"
    domains = ("sport",)

    def has_credentials(self) -> bool:
        # We always run — fall back to public read if key is missing.
        return True

    @property
    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.settings.overtime_api_key:
            h["x-api-key"] = self.settings.overtime_api_key
        return h

    async def _try_protected(self) -> list[dict]:
        try:
            r = await self.client.get(
                PROTECTED.format(network=NETWORK_OPTIMISM),
                headers=self._headers,
                timeout=15.0,
            )
            if r.status_code == 401:
                return []
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                # Flatten by sport
                out: list[dict] = []
                for sport_markets in data.values():
                    if isinstance(sport_markets, dict):
                        for league_markets in sport_markets.values():
                            if isinstance(league_markets, list):
                                out.extend(league_markets)
                    elif isinstance(sport_markets, list):
                        out.extend(sport_markets)
                return out
            if isinstance(data, list):
                return data
        except Exception as e:
            logger.debug("overtime protected error: %s", e)
        return []

    async def fetch_markets(self) -> list[NormalizedMarket]:
        raw_markets = await self._try_protected()
        markets: list[NormalizedMarket] = []
        for m in raw_markets:
            try:
                home = m.get("homeTeam") or m.get("home") or "Home"
                away = m.get("awayTeam") or m.get("away") or "Away"
                title = f"{home} vs {away}"
                odds_list = m.get("odds") or []
                if not isinstance(odds_list, list) or len(odds_list) < 2:
                    continue
                outcomes: list[Outcome] = []
                labels = [home, "Draw", away] if len(odds_list) == 3 else [home, away]
                for i, o in enumerate(odds_list):
                    d = (o.get("decimal") or o.get("americanOdd")) if isinstance(o, dict) else o
                    try:
                        decimal_odds = float(d) if d else 0
                    except (TypeError, ValueError):
                        continue
                    if decimal_odds < 1.01:
                        continue
                    label = labels[i] if i < len(labels) else f"Outcome {i+1}"
                    outcomes.append(Outcome(name=label, decimal_odds=decimal_odds))
                if len(outcomes) < 2:
                    continue
                ts = m.get("maturityDate") or m.get("startTime") or m.get("maturity")
                start_time = None
                if isinstance(ts, (int, float)):
                    start_time = datetime.fromtimestamp(int(ts), tz=UTC)
                elif isinstance(ts, str):
                    try:
                        start_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        start_time = None
                game_id = m.get("gameId") or m.get("address") or m.get("id") or ""
                markets.append(
                    NormalizedMarket(
                        venue=self.id,
                        venue_market_id=str(game_id),
                        title=title,
                        kind="match_winner" if len(outcomes) == 3 else "binary",
                        domain="sport",
                        outcomes=outcomes,
                        start_time=start_time,
                        liquidity_usd=0.0,
                        sport=str(m.get("sport") or "").lower() or None,
                        tags=[m.get("leagueName", "")],
                        url=f"https://overtimemarkets.xyz/markets/{game_id}",
                    )
                )
            except Exception as e:
                logger.debug("overtime parse skip: %s", e)
                continue
        logger.info("overtime: %d markets", len(markets))
        return markets
