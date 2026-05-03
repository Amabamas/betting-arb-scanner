# Betting Arbitrage Scanner

Cross-venue arbitrage scanner for sportsbooks and on-chain prediction markets. CLI
PoC: pulls live odds from supported venues every N seconds, matches markets across
venues with a fuzzy title+time heuristic, computes 2-way arbitrage opportunities,
and renders a sortable Rich table in the terminal.

## Supported venues

| Venue        | Domain     | Auth                         | Status                                     |
|--------------|------------|------------------------------|--------------------------------------------|
| Polymarket   | prediction | none                         | working (Gamma API, ~380 markets)          |
| Limitless    | prediction | none                         | working (~170 markets)                     |
| Azuro        | sport      | none (subgraph)              | working (~200 prematch games)              |
| SX Bet       | sport+pred | none                         | working (no makers active right now)       |
| Kalshi       | prediction | RSA-PSS signed (env keys)    | implemented, needs key+private PEM         |
| Cloudbet     | sport      | `CLOUDBET_API_KEY`           | implemented, needs affiliate key           |
| PS3838       | sport      | `PS3838_USERNAME/PASSWORD`   | implemented, needs funded account          |
| Overtime     | sport      | `OVERTIME_API_KEY` (gated)   | implemented, needs partner-issued key      |
| Zeitgeist    | prediction | none (Subsquid GraphQL)      | best-effort (LMSR pool prices not derived) |
| Drift BET    | prediction | Solana SDK + DLOB            | stub (data API doesn't expose live prices) |
| Polkamarkets | prediction | EVM RPC                      | stub                                       |
| Monaco       | sport      | wallet-signed JWT            | stub                                       |

Adapters with missing credentials silently skip themselves; the scanner runs with
whatever subset is available.

## Quickstart

```bash
git clone <this-repo>
cd betting-arb-scanner
cp .env.example .env
# Fill in whichever credentials you have. Polymarket/Limitless/SX Bet/Azuro/Drift
# work with no creds at all.

python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

arb-scan --once          # run a single scan and print
arb-scan                 # run forever (poll every SCANNER_INTERVAL_S)
arb-scan --min-roi 0.01  # only show >=1% ROI
arb-scan --venues polymarket,kalshi,limitless --domain prediction
arb-scan --serve --port 8000   # web dashboard at http://127.0.0.1:8000
```

### Web dashboard

`arb-scan --serve` launches a FastAPI app that runs the scanner in a background
task and serves a single-page Tailwind + Alpine.js UI at
`http://127.0.0.1:8000`. The page polls `/api/scan` every 5 s and re-renders
without reload.

Filters (all client-side, no round trip):

- search by event title (substring, case-insensitive)
- min ROI slider (0–20 %)
- max ROI slider (1–100 %, useful to hide stale-quote phantoms like 89 %)
- show top N (10 / 25 / 50 / 100 / all)
- domain checkboxes (prediction / sport)
- venue checkboxes (auto-populated from active adapters)
- sort by ROI / payout / liquidity / start time, click again to flip direction

Each row links the side-A and side-B legs to the original event pages on the
respective venues, so you can jump straight to placing the trade.

![dashboard screenshot](docs/dashboard.png)


### Verifying Kalshi credentials

If `arb-scan` reports `kalshi: 0 markets`, your key id and PEM probably aren't
being loaded correctly. Run:

```bash
python scripts/check_kalshi.py
```

This prints exactly what made it into `KALSHI_API_KEY_ID` /
`KALSHI_PRIVATE_KEY_PEM`, parses the PEM, and makes a signed call to
`/exchange/status`. If that check passes, Kalshi will work in `arb-scan`.

The most common cause of failures is the multi-line PEM block confusing
`python-dotenv`. The bullet-proof format is to paste the PEM as a single line
with literal `\n` between rows, in double quotes:

```env
KALSHI_PRIVATE_KEY_PEM="-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIB...\nl5O7myVUkAT2C/...lots of lines.../==\n-----END RSA PRIVATE KEY-----"
```

### Running from PyCharm / VS Code

In PyCharm:

1. Open the project, right-click `src/arb_scanner/main.py` → **Run 'main'**.
2. Edit the run configuration:
   - **Parameters**: `--once --domain prediction --venues polymarket,kalshi --min-roi 0.005`
   - **Working directory**: the repo root (`betting-arb-scanner`)
   - **Python interpreter**: the one in `.venv/bin/python`
3. Make sure the **EnvFile** plugin is enabled, or just keep `.env` in the
   project root — `pydantic-settings` reads it automatically when launched
   from the working directory.


## How it works

1. Each adapter fetches its venue's live odds in parallel (`asyncio.gather`).
2. Returns are normalised to `NormalizedMarket` objects with decimal odds for
   every outcome.
3. Markets are split by domain (sport vs prediction) and grouped by a fuzzy
   title match (`rapidfuzz token_set_ratio`) plus a `±2h` start-time window
   for sport. Sport markets without a start time are dropped.
4. For each multi-venue group, a 2-way arb is computed for every YES/NO-style
   outcome pair: `ROI = 1 / (1/odds_a + 1/odds_b) - 1`.
5. Results are filtered (min ROI, min liquidity), sorted by ROI desc, and
   rendered as a Rich `Live` table.

## Configuration

All configuration goes through `.env` or environment variables (see
`.env.example`). Most useful runtime overrides:

| Var                         | Default | What it does                                    |
|-----------------------------|---------|-------------------------------------------------|
| `SCANNER_DOMAIN`            | hybrid  | `sport`, `prediction`, or `hybrid`              |
| `SCANNER_INTERVAL_S`        | 15      | Poll interval                                   |
| `SCANNER_MIN_ROI`           | 0.005   | Hide opportunities below this ROI               |
| `SCANNER_MIN_LIQUIDITY_USD` | 50      | Hide opportunities below this minimum liquidity |
| `SCANNER_TIME_WINDOW_HOURS` | 2       | Time tolerance for matching sport events        |
| `SCANNER_TITLE_THRESHOLD`   | 82      | rapidfuzz `token_set_ratio` cutoff (0..100)     |
| `SCANNER_VENUES`            | (all)   | CSV of adapter ids to enable                    |

CLI flags (`--min-roi`, `--interval`, `--venues`, `--domain`, `--once`)
override the env values.

## Limitations and caveats

- **Liquidity is partial**: most sportsbooks don't expose stake limits via their
  feed; we record `0` and treat that as "unbounded". Real arb execution must
  re-validate available size at order time. Polymarket/Kalshi/SX Bet expose
  some size data and are weighted accordingly.
- **Matching is heuristic**: title+time fuzzy matching is correct ~85% of the
  time. Always sanity-check before placing real bets — false-positive matches
  produce phantom arbs (looks like +ROI but the events differ).
- **Stale data**: a 15s polling cadence is fine for prematch, but live (in-play)
  markets move faster than the scanner can re-fetch. Treat all output as a
  research signal, not a trade order.
- **Stub adapters**: Monaco Protocol and Polkamarkets return zero markets in
  this PoC. They need wallet-signed auth and EVM RPC respectively, which are
  out of scope for the initial version.
- **No execution**: this is a scanner, not a placer. Do not connect it to any
  trading account that has withdrawal permissions enabled.

## Tests / lint

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## Disclaimer

Research / educational software. Use at your own risk. Live betting is illegal
in many jurisdictions and most venues' terms of service prohibit programmatic
access without an explicit partnership.
