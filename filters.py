"""Filter registry — extensible beyond sports.

A *filter* is a user-facing toggle (e.g. ``nfl``, ``bitcoin``) that maps to
one or more Polymarket tag slugs plus optional title keywords used as a
fallback when tags are missing.

Filters are grouped into *categories*. Each category has an optional parent
Polymarket tag which we use to scope the Gamma API query so we don't pull
the whole event firehose. ``parent_tag=None`` means "fetch everything".

To add a filter, append a :class:`Filter` to :data:`REGISTRY` (or a new
category to :data:`CATEGORIES`). No other file should need to change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    slug: str
    label: str
    parent_tag: str | None  # Gamma tag slug to scope queries; None = all events
    emoji: str = ""          # fallback emoji when a filter has none


@dataclass(frozen=True)
class Filter:
    slug: str                       # user-facing key
    category: str                   # category slug
    label: str                      # human label
    tag_slugs: frozenset[str]       # Polymarket tag slugs that match
    keywords: tuple[str, ...] = ()  # title-substring fallback (lowercase)
    emoji: str = ""                 # decoration prefix


CATEGORIES: dict[str, Category] = {
    "sports": Category("sports", "Sports", "sports", "🏟"),
    "crypto": Category("crypto", "Crypto", "crypto", "💰"),
    "politics": Category("politics", "Politics", "politics", "🗳"),
    "entertainment": Category("entertainment", "Entertainment", "entertainment", "🎬"),
    "weather": Category("weather", "Weather", "weather", "🌦"),
    "economics": Category("economics", "Economics", None, "📈"),
    "technology": Category("technology", "Technology", None, "🤖"),
}


def _f(slug: str, category: str, label: str, tags: set[str], keywords: tuple[str, ...] = (), emoji: str = "") -> Filter:
    return Filter(slug, category, label, frozenset(tags), keywords, emoji)


REGISTRY: dict[str, Filter] = {
    # ---- Sports ----
    "nfl": _f("nfl", "sports", "NFL", {"nfl"}, ("nfl",), "🏈"),
    "nba": _f("nba", "sports", "NBA", {"nba"}, ("nba",), "🏀"),
    "mlb": _f("mlb", "sports", "MLB", {"mlb"}, ("mlb",), "⚾"),
    "nhl": _f("nhl", "sports", "NHL", {"nhl"}, ("nhl",), "🏒"),
    "soccer": _f("soccer", "sports", "Soccer", {"soccer", "football"}, ("soccer", "football"), "⚽"),
    "world-cup": _f(
        "world-cup", "sports", "FIFA World Cup",
        {"world-cup", "fifa-world-cup", "world-cup-2026", "fifa-world-cup-2026"},
        ("world cup", "fifa world cup", "2026 world cup"),
        "🏆",
    ),
    "epl": _f("epl", "sports", "Premier League", {"epl", "premier-league"}, ("premier league",), "⚽"),
    "champions-league": _f(
        "champions-league", "sports", "Champions League",
        {"champions-league", "uefa-champions-league"},
        ("champions league",),  # dropped 'ucl' — too short, false-matched 'nuclear'
        "🏆",
    ),
    "mls": _f("mls", "sports", "MLS", {"mls"}, ("mls",), "⚽"),
    "ufc": _f("ufc", "sports", "UFC / MMA", {"ufc", "mma"}, ("ufc", "mma"), "🥊"),
    "tennis": _f("tennis", "sports", "Tennis", {"tennis"}, ("tennis",), "🎾"),
    "f1": _f("f1", "sports", "Formula 1", {"f1", "formula-1", "formula-one"}, ("formula 1", "grand prix"), "🏎"),
    "weather": _f("weather", "weather", "Weather", {"weather"}, ("weather", "temperature", "hurricane", "storm"), "🌦"),

    # ---- Crypto (examples; off by default) ----
    "bitcoin": _f("bitcoin", "crypto", "Bitcoin", {"bitcoin", "btc"}, ("bitcoin",), "₿"),
    "ethereum": _f("ethereum", "crypto", "Ethereum", {"ethereum", "eth"}, ("ethereum",), "Ξ"),

    # ---- Economics / technology / weather (examples; off by default) ----
    "fed-rates": _f(
        "fed-rates", "economics", "Federal Reserve / Rates",
        {"fed", "federal-reserve", "interest-rates", "fed-rates"},
        ("fed", "federal reserve", "interest rate", "rate cut", "rate hike"),
        "🏦",
    ),
    "ai": _f("ai", "technology", "AI", {"ai", "artificial-intelligence"}, ("ai", "artificial intelligence", "openai", "nvidia"), "🤖"),

    # ---- Politics (examples; off by default) ----
    "us-election": _f(
        "us-election", "politics", "US Elections",
        {"us-election", "elections-us", "2028-election"},
        ("election", "president"),
        "🗳",
    ),

    # ---- Entertainment (examples; off by default) ----
    "oscars": _f("oscars", "entertainment", "Oscars / Awards", {"oscars", "academy-awards"}, ("oscar", "academy award"), "🎬"),
}


def all_slugs() -> list[str]:
    return list(REGISTRY.keys())


def by_category() -> dict[str, list[Filter]]:
    """Return {category_slug: [filters...]} in registry insertion order."""
    out: dict[str, list[Filter]] = {c: [] for c in CATEGORIES}
    for f in REGISTRY.values():
        out.setdefault(f.category, []).append(f)
    return out


def group_active_by_category(active_slugs: list[str]) -> dict[str, list[Filter]]:
    """Group a list of active filter slugs by their category."""
    out: dict[str, list[Filter]] = {}
    for slug in active_slugs:
        f = REGISTRY.get(slug)
        if f is None:
            continue
        out.setdefault(f.category, []).append(f)
    return out


def _keyword_in_title(keyword: str, title: str) -> bool:
    """Match keyword against title. Single-word keywords use word boundaries
    (so 'ucl' doesn't match 'nuclear'); multi-word phrases use substring."""
    if " " in keyword:
        return keyword in title
    return re.search(r"\b" + re.escape(keyword) + r"\b", title) is not None


def match_event(event: dict, candidates: list[Filter]) -> Filter | None:
    """Return the first candidate filter that matches the event, or None."""
    tag_slugs = {(t.get("slug") or "").lower() for t in (event.get("tags") or []) if t}
    title = (event.get("title") or "").lower()
    for f in candidates:
        if f.tag_slugs & tag_slugs:
            return f
        if any(_keyword_in_title(kw, title) for kw in f.keywords):
            return f
    return None


def label_for(slug: str) -> str:
    f = REGISTRY.get(slug)
    return f.label if f else slug.upper()


def category_label(slug: str) -> str:
    c = CATEGORIES.get(slug)
    return c.label if c else slug.title()


def emoji_for(slug: str | None) -> str:
    """Return the filter's emoji, falling back to its category's emoji."""
    if not slug:
        return ""
    f = REGISTRY.get(slug)
    if f and f.emoji:
        return f.emoji
    if f:
        c = CATEGORIES.get(f.category)
        if c and c.emoji:
            return c.emoji
    return ""
