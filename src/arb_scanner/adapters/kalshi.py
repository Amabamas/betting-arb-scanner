"""Kalshi adapter — RSA-PSS signed REST.

Auth headers (every request):
  KALSHI-ACCESS-KEY: <api_key_id>
  KALSHI-ACCESS-TIMESTAMP: <ms_since_epoch>
  KALSHI-ACCESS-SIGNATURE: base64( RSA-PSS-SHA256( timestamp + method + path ) )

We sign with the user-provided private key PEM block and pull
`/events?with_nested_markets=true&status=open`. The flat `/markets` endpoint
returns markets in an order dominated by tens of thousands of illiquid
multivariate sports stat contracts — paginating it for tens of pages still
misses the high-traffic futures (NBA/NHL Finals, Fed rate, election, climate)
because they live behind their parent events. Iterating events surfaces the
full taxonomy and lets us tag each market with its category.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from typing import cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

BASE = "https://api.elections.kalshi.com/trade-api/v2"
EVENTS_PATH = "/trade-api/v2/events"


def _load_private_key(pem: str) -> rsa.RSAPrivateKey:
    """Load a PEM-encoded RSA private key tolerantly.

    Accepts:
      * a real multi-line PEM block (works when .env uses double-quoted
        multi-line value, or when the var is set directly in the shell)
      * a single-line value where each newline was escaped as the two
        characters '\\n' (common when copy-pasting a key into a JSON or .env
        file via single-line tooling)
      * a single-line value with all whitespace stripped (we re-fold every
        64 chars and wrap with BEGIN/END markers as a last-resort)
      * surrounding single or double quotes (removed)
    """
    pem = pem.strip()
    if (pem.startswith('"') and pem.endswith('"')) or (
        pem.startswith("'") and pem.endswith("'")
    ):
        pem = pem[1:-1]
    # Convert escaped newlines from .env / JSON-style values back to real ones.
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    if "BEGIN" not in pem:
        # Reconstruct PEM from a base64-only blob.
        body = "".join(pem.split())
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            + "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
            + "\n-----END RSA PRIVATE KEY-----\n"
        )
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("KALSHI_PRIVATE_KEY_PEM is not an RSA private key")
    return key


def _sign(key: rsa.RSAPrivateKey, timestamp_ms: str, method: str, path: str) -> str:
    msg = f"{timestamp_ms}{method.upper()}{path}".encode()
    sig = key.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def _parse_market(m: dict, event: dict) -> NormalizedMarket | None:
    """Convert one Kalshi market entry into a NormalizedMarket; returns None if illiquid."""
    yes_ask_raw = m.get("yes_ask_dollars") or m.get("yes_ask")
    no_ask_raw = m.get("no_ask_dollars") or m.get("no_ask")
    if not yes_ask_raw or not no_ask_raw:
        return None
    try:
        yp = float(yes_ask_raw)
        np_ = float(no_ask_raw)
    except (TypeError, ValueError):
        return None
    # Legacy `yes_ask` field was in cents (0..100).
    if yp > 1.5 or np_ > 1.5:
        yp /= 100.0
        np_ /= 100.0
    if not (0.005 < yp < 0.995) or not (0.005 < np_ < 0.995):
        return None

    # Drop Kalshi multi-leg sports parlays and per-game player-stat props.
    # These have auto-generated titles like:
    #   "yes Both Teams To Score,yes Over 1.5 goals,..."
    #   "Player Name: 2+ hits + runs + RBIs?"
    #   "Player Name: 1+ hits?"
    # They never have a counterpart on Polymarket/Limitless and account for
    # 80%+ of Kalshi's daily catalog, dominating matching cost.
    raw_title = str(m.get("title") or "")
    rt_low = raw_title.lower()
    if rt_low.startswith(("yes ", "no ", "yes,")) or ",yes " in rt_low or ",no " in rt_low:
        return None
    if " hits + runs + rbis" in rt_low or " hits + runs?" in rt_low or " hits?" in rt_low:
        return None
    if rt_low.endswith((" attempted?", " over/under?", " spread?")):
        return None
    # Prefer the event's title (the question) over the market's narrow title
    # (which is often just the answer — e.g. event "Who will be the next Pope?"
    # with markets titled "Cardinal X", "Cardinal Y", ...). We append the
    # subtitle so cross-venue matching keys on event + outcome.
    event_title = str(event.get("title") or "").strip()
    sub = str(m.get("yes_sub_title") or m.get("subtitle") or raw_title or "").strip()
    if event_title and sub and event_title.lower() not in sub.lower():
        title = f"{event_title} — {sub}"
    else:
        title = sub or event_title or str(m.get("ticker") or "")
    ticker = str(m.get("ticker") or "")
    close_ts = m.get("close_time")
    start_time: datetime | None = None
    if isinstance(close_ts, str):
        try:
            start_time = datetime.fromisoformat(close_ts.replace("Z", "+00:00"))
        except ValueError:
            start_time = None
    yes_size = float(m.get("yes_ask_size_fp") or m.get("yes_ask_size") or 0)
    no_size = float(m.get("no_ask_size_fp") or m.get("no_ask_size") or 0)
    liq_dollars = float(m.get("liquidity_dollars") or 0.0)
    category = str(event.get("category") or "").lower()

    # Kalshi web doesn't have per-market URLs — only per-event. The previous
    # `/markets/{market_ticker}` pattern produced 404s for sport markets like
    # KXUCLGAME-26MAY05ARSATM-ATM. The /events/{event_ticker} path resolves
    # for both sports and prediction events. Fall back to the series page if
    # the event ticker is missing.
    event_ticker = str(event.get("event_ticker") or m.get("event_ticker") or "").lower()
    series_ticker = str(event.get("series_ticker") or "").lower()
    url: str | None = None
    if event_ticker:
        url = f"https://kalshi.com/events/{event_ticker}"
    elif series_ticker:
        url = f"https://kalshi.com/series/{series_ticker}"

    return NormalizedMarket(
        venue="kalshi",
        venue_market_id=ticker,
        title=title,
        kind="binary",
        domain="prediction",
        outcomes=[
            Outcome(name="Yes", decimal_odds=1.0 / yp, available_usd=yes_size * yp),
            Outcome(name="No", decimal_odds=1.0 / np_, available_usd=no_size * np_),
        ],
        start_time=start_time,
        liquidity_usd=liq_dollars,
        tags=[category] if category else [],
        url=url,
    )


class KalshiAdapter(Adapter):
    id = "kalshi"
    domains = ("prediction",)
    requires_auth = True

    # Iterate up to ~6000 events. Each page returns 200, so 30 pages is the cap;
    # most categories are exhausted well before that.
    MAX_PAGES = 30
    PAGE_LIMIT = 200

    def has_credentials(self) -> bool:
        return bool(self.settings.kalshi_api_key_id and self.settings.kalshi_private_key_pem)

    def _headers(self, key: rsa.RSAPrivateKey, method: str, path: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        sig = _sign(key, ts, method, path)
        return {
            "KALSHI-ACCESS-KEY": self.settings.kalshi_api_key_id or "",
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "Accept": "application/json",
        }

    async def fetch_markets(self) -> list[NormalizedMarket]:
        if not self.has_credentials():
            return []
        try:
            key = _load_private_key(self.settings.kalshi_private_key_pem or "")
        except Exception as e:
            logger.warning("kalshi private key load failed: %s", e)
            return []

        markets: list[NormalizedMarket] = []
        cursor = ""
        seen_pages = 0
        for _ in range(self.MAX_PAGES):
            params: list[tuple[str, str | int | float | bool | None]] = [
                ("status", "open"),
                ("limit", str(self.PAGE_LIMIT)),
                ("with_nested_markets", "true"),
            ]
            if cursor:
                params.append(("cursor", cursor))
            try:
                r = await self.client.get(
                    f"{BASE}/events",
                    params=params,
                    headers=self._headers(key, "GET", EVENTS_PATH),
                    timeout=20.0,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.warning("kalshi events fetch error: %s", e)
                break
            seen_pages += 1
            events = data.get("events") or []
            for ev in events:
                ev_dict = cast(dict, ev)
                for raw in ev_dict.get("markets") or []:
                    parsed = _parse_market(cast(dict, raw), ev_dict)
                    if parsed is not None:
                        markets.append(parsed)
            cursor = data.get("cursor") or ""
            if not cursor:
                break

        logger.info("kalshi: %d liquid markets across %d pages", len(markets), seen_pages)
        return markets
