"""Azuro adapter — public The Graph subgraph (Polygon).

The data-feed subgraphs are technically deprecated in v3 in favour of a Backend
REST API, but the subgraph still serves usable game/odds data and works without
an API key, which keeps the PoC self-contained.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

# Try multiple endpoints; the first that responds is used.
SUBGRAPHS = [
    "https://thegraph-1.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-data-feed-polygon",
    "https://api.studio.thegraph.com/query/68573/azuro-data-feed-polygon/version/latest",
]

# 1X2 / moneyline outcomes. Schema as of 2026-05 (state=Prematch + Active conditions).
QUERY = """
{
  games(
    first: 200,
    orderBy: startsAt,
    orderDirection: asc,
    where: { state: Prematch, activeConditionsCount_gt: 0 }
  ) {
    id
    startsAt
    sport { name slug }
    league { name }
    participants { name image }
    conditions(where: { state: Active }) {
      id
      outcomes {
        id
        outcomeId
        currentOdds
      }
    }
  }
}
"""


class AzuroAdapter(Adapter):
    id = "azuro"
    domains = ("sport",)

    async def _post_subgraph(self, url: str) -> dict | None:
        try:
            r = await self.client.post(url, json={"query": QUERY}, timeout=15.0)
            if r.status_code != 200:
                return None
            data = r.json()
            if "errors" in data:
                logger.debug("azuro subgraph errors %s", data["errors"])
                return None
            return data.get("data")
        except Exception as e:
            logger.debug("azuro subgraph error: %s", e)
            return None

    async def fetch_markets(self) -> list[NormalizedMarket]:
        data = None
        for url in SUBGRAPHS:
            data = await self._post_subgraph(url)
            if data:
                break
        if not data:
            return []

        markets: list[NormalizedMarket] = []
        for g in data.get("games", []):
            try:
                participants = [p.get("name") for p in (g.get("participants") or [])]
                if len(participants) < 2:
                    continue
                title = " vs ".join([p for p in participants if p])
                starts = g.get("startsAt")
                start_time = None
                if (isinstance(starts, str) and starts.isdigit()) or isinstance(starts, (int, float)):
                    start_time = datetime.fromtimestamp(int(starts), tz=UTC)

                # Take the first 1X2/moneyline-like condition (3 outcomes) or 2-way
                cond = next(
                    (c for c in g.get("conditions", []) if 2 <= len(c.get("outcomes", [])) <= 3),
                    None,
                )
                if not cond:
                    continue
                outcomes: list[Outcome] = []
                for i, o in enumerate(cond["outcomes"]):
                    odds = o.get("currentOdds")
                    if not odds:
                        continue
                    try:
                        d = float(odds)
                    except (TypeError, ValueError):
                        continue
                    if d < 1.01:
                        continue
                    if len(cond["outcomes"]) == 3:
                        label = [participants[0], "Draw", participants[1]][i]
                    else:
                        label = participants[i] if i < len(participants) else f"Outcome {i+1}"
                    outcomes.append(Outcome(name=label, decimal_odds=d))

                if len(outcomes) < 2:
                    continue
                sport_slug = (g.get("sport") or {}).get("slug")
                league_name = (g.get("league") or {}).get("name")
                markets.append(
                    NormalizedMarket(
                        venue=self.id,
                        venue_market_id=str(g.get("id")),
                        title=title,
                        kind="match_winner" if len(outcomes) == 3 else "binary",
                        domain="sport",
                        outcomes=outcomes,
                        start_time=start_time,
                        liquidity_usd=0.0,
                        sport=sport_slug,
                        tags=[league_name] if league_name else [],
                        url=f"https://app.azuro.org/event/{g.get('id')}",
                    )
                )
            except Exception as e:
                logger.debug("azuro parse skip: %s", e)
                continue

        logger.info("azuro: %d markets", len(markets))
        return markets
