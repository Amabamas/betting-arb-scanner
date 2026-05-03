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
    "win",
    "будет",
    "ли",
    "выиграет",
}


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_title(title: str) -> str:
    s = _strip_accents(title.lower())
    # Match latin a-z, digits, the cyrillic block (U+0400..U+04FF), and spaces.
    s = re.sub(r"[^a-z0-9\u0400-\u04FF ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for alias, target in _TEAM_ALIASES.items():
        s = re.sub(rf"\b{re.escape(alias)}\b", target, s)
    tokens = [t for t in s.split() if t not in _STOPWORDS and len(t) > 1]
    return " ".join(tokens)


def title_similarity(a: str, b: str) -> int:
    return int(fuzz.token_set_ratio(normalize_title(a), normalize_title(b)))


def _start_compatible(
    a: NormalizedMarket, b: NormalizedMarket, window: timedelta
) -> bool:
    if a.domain != b.domain:
        return False
    if a.start_time is None or b.start_time is None:
        # Prediction markets often have no start_time; allow when both missing
        # OR one is missing and we only key on title.
        return a.domain == "prediction"
    return abs(a.start_time - b.start_time) <= window


def group_markets(
    markets: list[NormalizedMarket],
    title_threshold: int = 82,
    time_window_hours: float = 2.0,
) -> list[list[NormalizedMarket]]:
    """Greedy grouping: each market is added to the first group whose representative
    matches it under the title+time criteria, otherwise a new group is created."""
    window = timedelta(hours=time_window_hours)
    # Bucket sports markets by sport+date for cheaper pairwise compares
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
        local_groups: list[list[NormalizedMarket]] = []
        for m in bucket_markets:
            placed = False
            for g in local_groups:
                rep = g[0]
                if not _start_compatible(rep, m, window):
                    continue
                if title_similarity(rep.title, m.title) >= title_threshold:
                    g.append(m)
                    placed = True
                    break
            if not placed:
                local_groups.append([m])
        groups.extend(local_groups)

    # Only keep groups that have >= 2 venues (otherwise no arb possible)
    multi_venue_groups: list[list[NormalizedMarket]] = []
    for g in groups:
        venues = {m.venue for m in g}
        if len(venues) >= 2:
            multi_venue_groups.append(g)
    return multi_venue_groups
