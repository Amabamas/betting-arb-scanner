"""Standalone Kalshi credentials sanity check.

Usage (from repo root, after `cp .env.example .env` and filling KALSHI_* vars):

    uv run scripts/check_kalshi.py            # or `python scripts/check_kalshi.py`

Reports:
  * whether KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PEM were picked up
  * the raw length / first-and-last bytes of the PEM (without leaking it)
  * whether the key parses as a real RSA private key
  * whether a signed request to /trade-api/v2/exchange/status returns 200
  * how many events are visible on the first /events page
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

# Allow `python scripts/check_kalshi.py` from repo root without installing the package.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from arb_scanner.adapters.kalshi import BASE, EVENTS_PATH, _load_private_key, _sign  # noqa: E402


def _redact(s: str, head: int = 12, tail: int = 8) -> str:
    if len(s) <= head + tail + 5:
        return "***"
    return f"{s[:head]}…(+{len(s) - head - tail} chars)…{s[-tail:]}"


async def main() -> int:
    key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    pem = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")

    print("=== KALSHI_API_KEY_ID ===")
    if not key_id:
        print("  ❌ MISSING — set KALSHI_API_KEY_ID in your .env")
        return 1
    print(f"  ✅ set, length={len(key_id)}, value={_redact(key_id)}")

    print("\n=== KALSHI_PRIVATE_KEY_PEM ===")
    if not pem:
        print("  ❌ MISSING — set KALSHI_PRIVATE_KEY_PEM in your .env")
        return 1
    raw_len = len(pem)
    nl = pem.count("\n")
    has_begin = "BEGIN" in pem
    has_end = "END" in pem
    print(
        f"  raw_length={raw_len}  newlines={nl}  has_BEGIN={has_begin}  has_END={has_end}"
    )
    print(f"  first 40 chars: {pem[:40]!r}")
    print(f"  last  40 chars: {pem[-40:]!r}")

    try:
        priv = _load_private_key(pem)
    except Exception as exc:
        print(f"  ❌ key did not parse: {exc}")
        print(
            "     Hints: in .env, paste the PEM as a single line with literal "
            "'\\n' between rows, e.g.\n"
            "     KALSHI_PRIVATE_KEY_PEM='-----BEGIN RSA PRIVATE KEY-----\\nMIIE...\\n-----END RSA PRIVATE KEY-----'"
        )
        return 1
    print(f"  ✅ parsed as RSA private key ({priv.key_size} bits)")

    print("\n=== Signed request to /exchange/status ===")
    async with httpx.AsyncClient() as client:
        path = "/trade-api/v2/exchange/status"
        ts = str(int(__import__("time").time() * 1000))
        sig = _sign(priv, ts, "GET", path)
        try:
            r = await client.get(
                f"{BASE}/exchange/status",
                headers={
                    "KALSHI-ACCESS-KEY": key_id,
                    "KALSHI-ACCESS-TIMESTAMP": ts,
                    "KALSHI-ACCESS-SIGNATURE": sig,
                    "Accept": "application/json",
                },
                timeout=10.0,
            )
        except Exception as exc:
            print(f"  ❌ HTTP error: {exc}")
            return 1
        print(f"  status={r.status_code}")
        if r.status_code != 200:
            print(f"  body[:200]={r.text[:200]!r}")
            print("  ❌ auth failed — your key id and PEM probably don't match")
            return 1
        print(f"  body={r.json()}")

        print("\n=== /events?limit=5 ===")
        ts = str(int(__import__("time").time() * 1000))
        sig = _sign(priv, ts, "GET", EVENTS_PATH)
        r = await client.get(
            f"{BASE}/events",
            params={"status": "open", "limit": 5, "with_nested_markets": "true"},
            headers={
                "KALSHI-ACCESS-KEY": key_id,
                "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": sig,
                "Accept": "application/json",
            },
            timeout=15.0,
        )
        print(f"  status={r.status_code}")
        events = r.json().get("events") or []
        print(f"  events on first page: {len(events)}")
        for ev in events[:3]:
            ev_title = ev.get("title")
            n_markets = len(ev.get("markets") or [])
            print(f"    • {ev_title!r}  ({n_markets} nested markets)")

    print("\n✅ Kalshi credentials are working — re-run `arb-scan --once` and you should see ~25k markets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
