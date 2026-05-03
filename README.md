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

arb-scan --once         # run a single scan and print
arb-scan                # run forever (poll every SCANNER_INTERVAL_S)
arb-scan --min-roi 0.01 # only show >=1% ROI
arb-scan --venues polymarket,kalshi,limitless --domain prediction
```

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
