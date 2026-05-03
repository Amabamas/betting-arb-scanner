"""Heuristic matcher: groups markets across venues that refer to the same real-world event.

Strategy:
- For sport markets: token_set_ratio over normalized titles + start_time within ±window.
- For prediction markets: token_set_ratio over titles only (no reliable start_time).

Returns a list of groups (each group is a list of NormalizedMarket instances).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import timedelta

from rapidfuzz import fuzz

from .models import NormalizedMarket

_TEAM_ALIASES = {
    "man utd": "manchester united",
    "manu": "manchester united",
    "mufc": "manchester united",
    "man city": "manchester city",
    "city": "manchester city",
    "psg": "paris saint germain",
    "atletico": "atletico madrid",
    "real": "real madrid",
    "barca": "barcelona",
    "spurs": "tottenham",
    "wolves": "wolverhampton",
    # Crypto + finance shorthand
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    # Common phrasing synonyms
    "exceed": "above",
    "exceeds": "above",
    "greater than": "above",
    "more than": "above",
    "less than": "below",
    "under": "below",
    "at least": "above",
    # Country/league shorthand
    "u s ": "usa ",
    "us presidential": "usa presidential",
    "epl": "english premier league",
    "ucl": "champions league",
}

_STOPWORDS = {
    "fc",
    "afc",
    "cf",
    "fk",
    "sk",
    "vs",
    "v",
    "the",
    "match",
    "winner",
    "to",
    "будет",
    "ли",
    "выиграет",
}

# Pure boilerplate/wrappers that appear in nearly every prediction market title.
# These are dropped before matching but kept in the original title for display.
_BOILERPLATE_PATTERNS = [
    r"^will\s+",
    r"^who\s+will\s+",
    r"^when\s+will\s+",
    r"\bbe\s+the\b",
    r"\bbecome\s+the\b",
]

# Phrases that change semantics — if one title has them and the other doesn't,
# we should refuse to match (e.g. "run for" vs "win").
_SEMANTIC_GUARDS = (
    "run for",
    "trailer",
    "before gta vi",
    "next pope",
    "supervolcano",
    "1st round",
    "2nd round",
    "first round",
    "second round",
    "2nd place",
    "third place",
    "group stage",
    "vp ",
    "vice president",
    "by june",
    "by july",
    "by march",
    "by december",
    "by january",
    "by february",
    "by april",
    "by august",
    "by october",
    "by november",
)


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_title(title: str) -> str:
    s = _strip_accents(title.lower())
    for pat in _BOILERPLATE_PATTERNS:
        s = re.sub(pat, " ", s)
    # Match latin a-z, digits, the cyrillic block (U+0400..U+04FF), and spaces.
    s = re.sub(r"[^a-z0-9\u0400-\u04FF ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for alias, target in _TEAM_ALIASES.items():
        s = re.sub(rf"\b{re.escape(alias)}\b", target, s)
    tokens = [t for t in s.split() if t not in _STOPWORDS and len(t) > 1]
    return " ".join(tokens)


_DISCRIMINATIVE_MIN_LEN = 5


def title_similarity(a: str, b: str) -> int:
    """Combined fuzzy score that penalizes one-sided subset matches and
    competition/league mix-ups.

    `token_set_ratio` alone is too generous for prediction markets — Kalshi's
    "Who will run for the 2028 Democratic nomination — Newsom" scores 100
    against Polymarket's "Will Newsom win the 2028 Democratic nomination",
    but those mean different things. Likewise "Premier League" vs "Champions
    League" futures share most tokens but are different competitions.

    Strategy:
      1. Hard guards: a few obvious semantic-shifters ("run for", "trailer").
      2. Discriminative-token coverage: every ≥5-char token that appears in
         exactly one side disqualifies the match unless it has a fuzzy match
         on the other side. This catches "Premier" vs "Champions".
      3. Blended set+sort ratio.
    """
    al = a.lower()
    bl = b.lower()
    for guard in _SEMANTIC_GUARDS:
        if (guard in al) != (guard in bl):
            return 0

    na = normalize_title(a)
    nb = normalize_title(b)
    if not na or not nb:
        return 0

    # Discriminative tokens (long, content-bearing) must appear (or fuzzy-match)
    # on the other side. We allow 1 unmatched token to absorb minor variation
    # like "presidential" vs "president".
    def _disc_tokens(s: str) -> set[str]:
        return {t for t in s.split() if len(t) >= _DISCRIMINATIVE_MIN_LEN}

    da = _disc_tokens(na)
    db = _disc_tokens(nb)
    if da and db:
        # Each side must be largely covered by the other. We allow up to
        # 1 token of slack to absorb minor wording differences (e.g.
        # "presidential" vs "president"); two unmatched discriminative tokens
        # almost always means a different competition (Premier vs Champions),
        # different country (Spain vs France), etc.
        unmatched = 0
        for t in da:
            if t in nb:
                continue
            if max((fuzz.ratio(t, u) for u in db), default=0) >= 80:
                continue
            unmatched += 1
        for t in db:
            if t in na:
                continue
            if max((fuzz.ratio(t, u) for u in da), default=0) >= 80:
                continue
            unmatched += 1
        if unmatched > 1:
            return 0

    set_score = fuzz.token_set_ratio(na, nb)
    sort_score = fuzz.token_sort_ratio(na, nb)
    return int(min(set_score, sort_score) * 0.6 + max(set_score, sort_score) * 0.4)


def _start_compatible(
    a: NormalizedMarket, b: NormalizedMarket, window: timedelta
) -> bool:
    if a.domain != b.domain:
        return False
    # Prediction markets resolve at arbitrary times across venues (e.g. Kalshi
    # closes at 23:59 UTC the day before, Polymarket at 12:00 UTC the day of)
    # — gating on a 2h window suppresses real matches. We rely on title alone.
    if a.domain == "prediction":
        return True
    if a.start_time is None or b.start_time is None:
        return False
    return abs(a.start_time - b.start_time) <= window


_MIN_INDEX_TOKEN_LEN = 4
# Tokens that match >TOKEN_DF_CAP markets are considered too common
# (eg "2026", "election", "win") and are skipped from the inverted index lookup
# to keep candidate sets small.
_TOKEN_DF_CAP = 200
# Hard cap on how many candidate groups we evaluate per market — cutoff after
# this many to keep the worst case bounded.
_MAX_CANDIDATES = 200


def _index_tokens(title: str) -> set[str]:
    """Extract significant tokens for inverted-index blocking."""
    norm = normalize_title(title)
    return {t for t in norm.split() if len(t) >= _MIN_INDEX_TOKEN_LEN}


def group_markets(
    markets: list[NormalizedMarket],
    title_threshold: int = 82,
    time_window_hours: float = 2.0,
) -> list[list[NormalizedMarket]]:
    """Greedy grouping with token-blocking for tractability on 10⁴-scale catalogs.

    For each market we look up candidate groups whose representative shares at
    least one ≥4-char token. We also drop very common tokens (>600 occurrences)
    from the candidate lookup to avoid quadratic blow-up on stop-words like
    "presidential" or "2026". Title comparisons cache normalized + sort/set
    forms per group representative.
    """
    window = timedelta(hours=time_window_hours)
    # Bucket sports markets by sport+date for cheaper pairwise compares.
    buckets: dict[object, list[NormalizedMarket]] = defaultdict(list)
    for m in markets:
        key: object
        if m.domain == "sport" and m.start_time is not None:
            key = (m.domain, m.sport or "any", m.start_time.date())
        else:
            key = (m.domain, "any", None)
        buckets[key].append(m)

    groups: list[list[NormalizedMarket]] = []
    for bucket_markets in buckets.values():
        # Pre-compute df for each token; tokens above the cap will be skipped
        # in the candidate lookup but still added to the index for completeness.
        df: defaultdict[str, int] = defaultdict(int)
        token_cache: list[set[str]] = []
        for m in bucket_markets:
            toks = _index_tokens(m.title)
            token_cache.append(toks)
            for t in toks:
                df[t] += 1

        local_groups: list[list[NormalizedMarket]] = []
        token_to_groups: dict[str, set[int]] = defaultdict(set)
        for idx, m in enumerate(bucket_markets):
            tokens = token_cache[idx]
            if not tokens:
                local_groups.append([m])
                continue
            # Use only the ≤_TOKEN_DF_CAP-frequent tokens to bound candidate set.
            informative = {t for t in tokens if df[t] <= _TOKEN_DF_CAP}
            if not informative:
                # Fall back to the rarest few tokens regardless of cap.
                informative = set(sorted(tokens, key=lambda t: df[t])[:3])
            candidate_groups: set[int] = set()
            for tok in informative:
                candidate_groups.update(token_to_groups.get(tok, ()))
                if len(candidate_groups) > _MAX_CANDIDATES:
                    break
            placed = False
            for gi in candidate_groups:
                g = local_groups[gi]
                rep = g[0]
                if not _start_compatible(rep, m, window):
                    continue
                if title_similarity(rep.title, m.title) >= title_threshold:
                    g.append(m)
                    placed = True
                    break
            if not placed:
                gi = len(local_groups)
                local_groups.append([m])
                # Index against ALL tokens so future lookups can find this rep.
                for tok in tokens:
                    token_to_groups[tok].add(gi)
        groups.extend(local_groups)

    # Only keep groups that have >= 2 venues (otherwise no arb possible).
    multi_venue_groups: list[list[NormalizedMarket]] = []
    for g in groups:
        venues = {m.venue for m in g}
        if len(venues) >= 2:
            multi_venue_groups.append(g)
    return multi_venue_groups
