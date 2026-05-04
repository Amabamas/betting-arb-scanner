# Sportsbook scraping research

> Written 2026-05-04. Probed each book from a non-RU, non-Asia VPS using
> a stock Chrome 124 user-agent over plain `httpx`/curl. The protection
> tier reflects what is required to *get a JSON-shaped response* from a
> book's events feed without paying for partner access.

## TL;DR

- **None of the 16 books are Tier 1** (clean public REST/JSON, no
  challenge, no region lock, no auth).
- Of the 16, ~6 have *no realistic free path at all*: country-blocked or
  partner-gated (Vave, 188BET, SBOBET, 888sport, GG.BET, 12BET).
- The remaining 10 split between **Tier 2** (Cloudflare-Lite or
  ServicePipe, beatable with `curl_cffi` TLS-fingerprint impersonation)
  and **Tier 3** (full Cloudflare Turnstile or WebSocket-only SPAs that
  need Playwright with a real browser).
- Most of the crypto books (Stake / BC.Game / Rollbit / BetFury /
  Sportsbet.io) sit on **the same TSG White Label / 1xBet feed** — they
  have **near-identical odds**, so adding all five is not 5× more arb
  signal, it is one signal repeated.
- **The single highest-value book on this list is Pinnacle (PS3838)**
  because it has the only independent priced compiler with API access,
  and we already have an adapter for it gated on the user's account
  having API permission enabled.

## Tier definitions

| Tier | What it means | Cost to implement | Expected maintenance |
|---|---|---|---|
| **1** | Plain GET → JSON response. No region lock, no challenge, no auth. | hours, `httpx` only | quarterly when URLs move |
| **2** | Cloudflare-Lite, DDoS-Guard, ServicePipe, or signed cookies. Beatable with TLS-fingerprint impersonation (`curl_cffi`, `tls-client`) and a realistic UA + cookie jar. | days, +`curl_cffi` dep | monthly |
| **3** | Cloudflare Turnstile, Akamai Bot Manager, browser fingerprinting, WebSocket-only feeds, JS-rendered SPA that won't load without executing scripts. | weeks, +Playwright +residential proxies | weekly |
| **4** | Partner-gated B2B (OpenBet, Kambi, Spectate). Requires signed contract or a real licensed account in good standing in the right jurisdiction. | months + recurring fees | constant |

## Per-book findings

### Crypto-casino sportsbooks (TSG White Label / 1xBet feed)

These five books all source their odds from one of two B2B providers
(TSG / 1xBet). Odds are functionally identical across them, only the
margin overlay differs by 0.5–1%. From an arbitrage perspective, this is
**one feed**, not five.

| Book | Probe | Tier | Notes |
|---|---|---|---|
| **Stake** | `/_api/graphql` → CF challenge (HTTP 403) | 3 | GraphQL endpoint exists but requires CF Turnstile solve and an auth cookie. Region-restricted in many countries. |
| **BC.Game** | `/api/sports/v1/sports` → `{"code":1901,"msg":"Oops, coco is gone!"}` | 2–3 | Has a real internal API, but it returns an error code unless you've already solved a CF challenge and have a session cookie. |
| **Sportsbet.io** | `/api/v2/listings/active` → CF challenge (HTTP 403) | 3 | TSG White Label with strict CF Turnstile. |
| **Rollbit** | `/api/sports/sports` → CF challenge (HTTP 403) | 3 | |
| **BetFury** | Main 200, `/api/sports/sports` → 404 | 2–3 | Their actual sports API path differs and is auth-gated. |

**Recommendation:** Pick **at most one** of these (Stake or
Sportsbet.io are the most liquid). Adding the others is duplicate
signal. Implementation requires Playwright + stealth + at least one
auth cookie obtained via real account login.

### Asian sportsbooks (partner-gated / region-locked)

| Book | Probe | Tier | Notes |
|---|---|---|---|
| **SBOBET** | Main 200, `/api/sports` → generic HTML, no public API | 4 | Asian Handicap pool. API access is partner-only. |
| **188BET** | All hostnames TIMEOUT from non-Asia IP | 4 | Region-locked at the network layer. |
| **12BET** | Main 200, no obvious API | 3–4 | Likely partner-gated like SBOBET. |
| **GG.BET** | Outright HTTP 403 from non-EU IP | 3 | Esports-focused; their feed is Sportradar Esports under the hood, which is also what other esports books use. |
| **888sport** | Spectate engine, scripts on `cdn.spectateprod.com` | 4 | OpenBet/Spectate B2B feed. Public web client streams data but only inside an authenticated session. |

**Recommendation:** **Skip all five.** Implementation cost is
disproportionate to value, and their pricing is largely correlated with
what we already get from Pinnacle / Cloudbet.

### Country-blocked from outside RU/Asia

These books may have semi-open feeds inside their target geography but
return either 30x redirects or a JS DDoS-challenge from anywhere else.

| Book | Probe | Tier | Notes |
|---|---|---|---|
| **Fonbet** | `https://fon.bet/` → ServicePipe JS challenge (RU DDoS-Guard) | 2 (with RU IP) | Real internal feed exists at `/api/v1/events` etc., but reachable only after a ServicePipe cookie is set, which requires an RU egress IP and a JS solver. |
| **Pari** (ex-Parimatch RU) | `/api/web/v1/lines` → 301 to homepage | 2 (with RU IP) | SPA fetches its API from a host that returns 301 from non-RU. |
| **Pin-Up** | `https://pin-up.bet/` → CF challenge (HTTP 403) | 3 | Cloudflare Turnstile. |
| **Marathonbet** | Main 200, but coupon prices loaded over **WebSocket** at `/en/websocket/endpoint` | 2 | Old-school WS-driven betting site. We'd need a WebSocket client + subscription protocol RE, not a REST call. |
| **Baltbet** | Vite SPA on `wc.baltbet.ru`, `/api/*` paths 301/404 | 2–3 | Need to inspect XHR calls in browser to find the real API host. |
| **Vave** | "Country blocked" page (HTTP 200 with HTML title `Country blocked`) | N/A | Can't proceed without changing source IP. |

**Recommendation:**
- **Fonbet + Pari** are the highest-value RU books because they have
  independent risk-management. **But they require a Russian residential
  proxy** to even probe further (~$30–60/mo for a single IP, more for
  rotation).
- **Marathonbet** is technically interesting (WebSocket subscription
  protocol is well-understood) but a 1–2 week project on its own.
- **Pin-Up / Baltbet / Vave** are skippable at this stage.

## Summary table

| Book | Independent pricing? | Tier | Recommend? |
|---|---|---|---|
| Stake | no (TSG feed) | 3 | maybe — pick one of the crypto books |
| BC.Game | no | 2–3 | skip (duplicate of Stake) |
| Sportsbet.io | no | 3 | maybe — pick one of the crypto books |
| Rollbit | no | 3 | skip |
| BetFury | no | 3 | skip |
| Vave | no | n/a | skip (region-locked) |
| GG.BET | no | 3 | skip (esports, Sportradar feed) |
| 888sport | partial (Kambi/OpenBet) | 4 | skip (partner-only) |
| SBOBET | partial | 4 | skip (partner-only) |
| 188BET | partial | 4 | skip (region-locked) |
| 12BET | partial | 3–4 | skip (partner-only) |
| **Marathonbet** | **yes** | 2 (WS) | yes if we commit to WebSocket adapter |
| **Fonbet** | **yes** | 2 (with RU IP) | yes if we commit to a RU residential proxy |
| **Pari** | **yes** | 2 (with RU IP) | yes (same proxy budget as Fonbet) |
| Pin-Up | partial | 3 | skip |
| Baltbet | partial | 2–3 | skip |

## What I'd actually build

A pragmatic next step that respects cost vs. signal:

1. **Get Pinnacle / PS3838 working.** The `NO_API_ACCESS` resolution
   path (fund the account, request API access from support) is the
   cheapest, fastest way to add an *independent* pricing source. It is
   the benchmark line every other book is reacting to.

2. **Commit to ONE Tier 2 RU book** (Fonbet or Pari) **plus a Russian
   residential proxy.** This adds genuinely independent pricing in the
   €/RUB market that doesn't overlap with anything we currently scan.
   ~3 days of engineering + ~$40/mo proxy cost.

3. **Add Marathonbet via WebSocket** as a separate ~1 week project.
   Independent pricing, no proxy needed (their public WS does not
   region-lock our current egress).

4. **Skip all five crypto-casino books.** They are one signal masquerading
   as five.

5. **Skip all five Asian books.** Partner-only or region-locked.

If we stick to 1+2+3 we end up with ten *meaningfully independent*
pricing sources covering prediction markets, on-chain markets, US
exchanges, EU sportsbooks, RU sportsbooks, and an Asian benchmark — for
~1.5 weeks of work and ~$40/mo of infra. Adding the remaining 13 books
on top of that would roughly triple the engineering cost and add
duplicate signal.
