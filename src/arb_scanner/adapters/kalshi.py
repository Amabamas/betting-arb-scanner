"""Kalshi adapter — RSA-PSS signed REST.

Auth headers (every request):
  KALSHI-ACCESS-KEY: <api_key_id>
  KALSHI-ACCESS-TIMESTAMP: <ms_since_epoch>
  KALSHI-ACCESS-SIGNATURE: base64( RSA-PSS-SHA256( timestamp + method + path ) )

We sign with the user-provided private key PEM block and pull /markets?status=open.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ..models import NormalizedMarket, Outcome
from .base import Adapter

logger = logging.getLogger(__name__)

BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _load_private_key(pem: str) -> rsa.RSAPrivateKey:
    if "BEGIN" not in pem:
        # Allow user to paste base64 single-line; reconstruct PEM
        pem = (
            "-----BEGIN PRIVATE KEY-----\n"
            + "\n".join(pem[i : i + 64] for i in range(0, len(pem), 64))
            + "\n-----END PRIVATE KEY-----\n"
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


class KalshiAdapter(Adapter):
    id = "kalshi"
    domains = ("prediction",)
    requires_auth = True

    def has_credentials(self) -> bool:
        return bool(self.settings.kalshi_api_key_id and self.settings.kalshi_private_key_pem)

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
        for _ in range(5):  # cap pages
            path = "/trade-api/v2/markets"
            params: list[tuple[str, str | int | float | bool | None]] = [
                ("status", "open"),
                ("limit", "200"),
            ]
            if cursor:
                params.append(("cursor", cursor))
            ts = str(int(time.time() * 1000))
            sig = _sign(key, ts, "GET", path)
            try:
                r = await self.client.get(
                    f"{BASE}/markets",
                    params=params,
                    headers={
                        "KALSHI-ACCESS-KEY": self.settings.kalshi_api_key_id or "",
                        "KALSHI-ACCESS-TIMESTAMP": ts,
                        "KALSHI-ACCESS-SIGNATURE": sig,
                        "Accept": "application/json",
                    },
                    timeout=15.0,
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.warning("kalshi fetch error: %s", e)
                break

            for m in data.get("markets", []):
                # Prices in cents (0..100). yes_ask / no_ask = lowest selling price.
                yes_ask = m.get("yes_ask")
                no_ask = m.get("no_ask")
                if not yes_ask or not no_ask:
                    continue
                try:
                    yp = float(yes_ask) / 100.0
                    np_ = float(no_ask) / 100.0
                except (TypeError, ValueError):
                    continue
                if not (0.005 < yp < 0.995) or not (0.005 < np_ < 0.995):
                    continue
                title = str(m.get("title") or m.get("subtitle") or m.get("ticker") or "").strip()
                ticker = str(m.get("ticker") or "")
                close_ts = m.get("close_time")
                start_time = None
                if isinstance(close_ts, str):
                    try:
                        start_time = datetime.fromisoformat(close_ts.replace("Z", "+00:00"))
                    except ValueError:
                        start_time = None

                markets.append(
                    NormalizedMarket(
                        venue=self.id,
                        venue_market_id=ticker,
                        title=title,
                        kind="binary",
                        domain="prediction",
                        outcomes=[
                            Outcome(
                                name="Yes",
                                decimal_odds=1.0 / yp,
                                available_usd=float(m.get("yes_ask_size", 0)) * yp,
                            ),
                            Outcome(
                                name="No",
                                decimal_odds=1.0 / np_,
                                available_usd=float(m.get("no_ask_size", 0)) * np_,
                            ),
                        ],
                        start_time=start_time,
                        liquidity_usd=float(m.get("liquidity") or 0.0) / 100.0,
                        tags=[m.get("category", "")],
                        url=f"https://kalshi.com/markets/{ticker.lower()}" if ticker else None,
                    )
                )

            cursor = data.get("cursor") or ""
            if not cursor:
                break

        logger.info("kalshi: %d markets", len(markets))
        return markets
