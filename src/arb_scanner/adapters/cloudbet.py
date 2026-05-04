"""Cloudbet adapter — Feed API with X-API-Key header.

Docs: https://docs.cloudbet.com / https://cloudbet.github.io/wiki/en/docs/sports/api/
We pull a configurable set of sports → competitions → events with prices.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

BASE = "https://sports-api.cloudbet.com/pub/v2/odds"

# Limit the universe to most-liquid sports for the PoC.
DEFAULT_SPORTS = ["soccer", "basketball", "tennis", "american-football", "ice-hockey"]

# Cloudbet market keys are camelCase, e.g. `soccer.matchOdds`,
# `basketball.moneyline`, `baseball.moneyline`. The previous snake_case filter
# (`.match_odds`) matched nothing for soccer/hockey, which is why arbs were
# essentially limited to basketball/baseball. Match suffix case-insensitively
# and accept both stylings + the common 2-way aliases.
_MAIN_MARKET_SUFFIXES = (
    "matchodds",  # soccer / hockey 1X2
    "match_odds",  # snake-case fallback
    "moneyline",  # NBA / MLB / NFL 2-way
    "matchwinner",
    "match_winner",
    "winner",  # sport-agnostic 2-way alias
    "drawnobet",
    "draw_no_bet",  # 1X2 collapsed to 2-way
)


def _is_main_market(market_key: str) -> bool:
    suffix = market_key.rsplit(".", 1)[-1].lower()
    return suffix in _MAIN_MARKET_SUFFIXES


class CloudbetAdapter(Adapter):
    id = "cloudbet"
    domains = ("sport",)
    requires_auth = True

    def has_credentials(self) -> bool:
        return bool(self.settings.cloudbet_api_key)

    @property
    def _headers(self) -> dict[str, str]:
        # Trim whitespace + accidental wrapping quotes (`"abc"` or `'abc'`) that
        # users sometimes paste into .env. Keep the key opaque otherwise.
        raw = (self.settings.cloudbet_api_key or "").strip()
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1]
        return {
            "X-API-Key": raw,
            "Accept": "application/json",
        }

    async def _competitions(self, sport_key: str) -> list[str]:
        try:
            r = await self.client.get(
                f"{BASE}/sports/{sport_key}", headers=self._headers, timeout=15.0
            )
            if r.status_code == 401:
                raise RuntimeError("cloudbet auth failed (401) — check CLOUDBET_API_KEY")
            if r.status_code == 403:
                raise RuntimeError(
                    "cloudbet returned 403 — region-restricted or key not authorised"
                )
            r.raise_for_status()
            data = r.json() or {}
        except RuntimeError:
            raise
        except Exception as e:
            logger.debug("cloudbet competitions(%s) error: %s", sport_key, e)
            return []
        keys: list[str] = []
        for cat in data.get("categories") or []:
            if not isinstance(cat, dict):
                continue
            for comp in cat.get("competitions") or []:
                if not isinstance(comp, dict):
                    continue
                key = comp.get("key")
                # eventCount can be missing or null on rare new categories — coerce safely
                event_count = comp.get("eventCount") or 0
                if key and event_count > 0:
                    keys.append(key)
        # Cap so a single sport can't blow up runtime; 30 is enough to cover
        # the major leagues per sport (top European football tiers, NBA + EuroLeague,
        # ATP/WTA majors, NFL/NCAAF, NHL + KHL).
        return keys[:30]

    async def _competition_markets(self, comp_key: str) -> list[NormalizedMarket]:
        out: list[NormalizedMarket] = []
        try:
            r = await self.client.get(
                f"{BASE}/competitions/{comp_key}", headers=self._headers, timeout=15.0
            )
            r.raise_for_status()
            data = r.json() or {}
        except Exception as e:
            logger.debug("cloudbet competition(%s) error: %s", comp_key, e)
            return out
        # Cloudbet sometimes returns null for `events`, `home`, `away`, `sport`
        # (when an event lacks one side, was just created, etc). dict.get(key, {})
        # returns None — not the default — when the key exists with value=None,
        # so we coerce defensively at every dereference.
        sport_obj = data.get("sport") or {}
        if not isinstance(sport_obj, dict):
            sport_obj = {}
        sport = sport_obj.get("key") or data.get("sportKey") or ""

        for event in data.get("events") or []:
            if not isinstance(event, dict):
                continue
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

            home_obj = event.get("home") or {}
            away_obj = event.get("away") or {}
            if not isinstance(home_obj, dict):
                home_obj = {}
            if not isinstance(away_obj, dict):
                away_obj = {}
            home = home_obj.get("name") or "Home"
            away = away_obj.get("name") or "Away"
            title = f"{home} vs {away}"
            event_id = str(event.get("id") or "")

            markets_dict = event.get("markets") or {}
            if not isinstance(markets_dict, dict):
                continue
            for market_key, market in markets_dict.items():
                if not isinstance(market, dict):
                    continue
                # Pull main 1X2 / moneyline markets only. See _MAIN_MARKET_SUFFIXES
                # for the full list — Cloudbet uses camelCase keys
                # (`soccer.matchOdds`, NOT `soccer.match_odds`), which the
                # previous filter silently dropped.
                if not _is_main_market(market_key):
                    continue
                submarkets = market.get("submarkets") or {}
                if not isinstance(submarkets, dict):
                    continue
                # Cloudbet score-types: `period=default`, `period=ft`, etc. We
                # want the one covering the full game/match (no half / set /
                # quarter slicing). Try the obvious aliases, then fall back to
                # the first submarket so we never silently drop a valid market.
                main = (
                    submarkets.get("period=ft")
                    or submarkets.get("period=default")
                    or submarkets.get("period=match")
                    or next(iter(submarkets.values()), None)
                )
                if not isinstance(main, dict):
                    continue
                selections = main.get("selections") or []
                if not isinstance(selections, list):
                    continue
                outcomes: list[Outcome] = []
                for sel in selections:
                    if not isinstance(sel, dict):
                        continue
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
        first_error: Exception | None = None
        sports_with_comps = 0
        all_comps: list[str] = []
        for sport in DEFAULT_SPORTS:
            try:
                comps = await self._competitions(sport)
            except Exception as e:
                # Auth / region errors propagate from _competitions for visibility.
                first_error = first_error or e
                continue
            if comps:
                sports_with_comps += 1
            all_comps.extend(comps)

        # Cloudbet competition pages are independent — fetching them in
        # parallel cuts the previous ~30s of sequential I/O down to a few
        # seconds. Cap concurrency to be polite with the rate limiter.
        sem = asyncio.Semaphore(8)

        async def _bounded(comp: str) -> list[NormalizedMarket]:
            async with sem:
                return await self._competition_markets(comp)

        if all_comps:
            for batch in await asyncio.gather(
                *(_bounded(c) for c in all_comps), return_exceptions=True
            ):
                if isinstance(batch, BaseException):
                    if first_error is None and isinstance(batch, Exception):
                        first_error = batch
                    continue
                all_markets.extend(batch)
        if not all_markets:
            if first_error is not None:
                # Surface the first sport's error so the dashboard shows a red dot
                # with a useful message instead of a silent empty result.
                raise first_error
            # Auth succeeded but every sport returned 0 — most often this means
            # the key is restricted to a subset of products / regions, or there
            # are no upcoming events matched by our market-key filter.
            raise RuntimeError(
                f"cloudbet: 0 markets across {len(DEFAULT_SPORTS)} sports "
                f"({sports_with_comps} responded) — key may be restricted "
                "or no upcoming match-winner / moneyline markets right now"
            )
        logger.info("cloudbet: %d markets", len(all_markets))
        return all_markets
