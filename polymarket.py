"""Polymarket Gamma API client."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import requests

log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_EVENT_URL = "https://polymarket.com/event"

# League slug -> set of tag slugs Polymarket uses. The first slug is the
# canonical filter; the rest catch alternate spellings seen on the site.
LEAGUE_TAG_SLUGS: dict[str, set[str]] = {
    "nfl": {"nfl"},
    "nba": {"nba"},
    "mlb": {"mlb"},
    "nhl": {"nhl"},
    "soccer": {"soccer", "football"},
    "epl": {"epl", "premier-league"},
    "champions-league": {"champions-league", "uefa-champions-league"},
    "mls": {"mls"},
    "ufc": {"ufc", "mma"},
    "tennis": {"tennis"},
    "f1": {"f1", "formula-1", "formula-one"},
}

# Keywords used as a fallback when tags aren't present on an event.
LEAGUE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "nfl": ("nfl",),
    "nba": ("nba",),
    "mlb": ("mlb",),
    "nhl": ("nhl",),
    "soccer": ("soccer",),
    "epl": ("premier league", "epl"),
    "champions-league": ("champions league", "ucl"),
    "mls": ("mls",),
    "ufc": ("ufc", "mma"),
    "tennis": ("tennis", "atp", "wta"),
    "f1": ("f1", "formula 1", "formula one", "grand prix"),
}

# Human-friendly labels for display.
LEAGUE_LABELS: dict[str, str] = {
    "nfl": "NFL",
    "nba": "NBA",
    "mlb": "MLB",
    "nhl": "NHL",
    "soccer": "Soccer",
    "epl": "Premier League",
    "champions-league": "Champions League",
    "mls": "MLS",
    "ufc": "UFC / MMA",
    "tennis": "Tennis",
    "f1": "Formula 1",
}

ALL_LEAGUES: list[str] = list(LEAGUE_TAG_SLUGS.keys())


@dataclass
class MarketEvent:
    id: str
    title: str
    slug: str
    league: str
    end_date: str | None
    volume: float | None

    @property
    def url(self) -> str:
        return f"{POLYMARKET_EVENT_URL}/{self.slug}"


def _match_league(event: dict, leagues: Iterable[str]) -> str | None:
    """Return the first league key from `leagues` that matches the event."""
    tag_slugs = {t.get("slug", "").lower() for t in event.get("tags", []) if t}
    title = (event.get("title") or "").lower()

    for league in leagues:
        if LEAGUE_TAG_SLUGS.get(league, set()) & tag_slugs:
            return league
        if any(kw in title for kw in LEAGUE_KEYWORDS.get(league, ())):
            return league
    return None


def fetch_new_sports_events(
    leagues: Iterable[str],
    *,
    limit: int = 100,
    session: requests.Session | None = None,
) -> list[MarketEvent]:
    """Fetch active, open sports events matching the requested leagues."""
    sess = session or requests.Session()
    params = {
        "closed": "false",
        "active": "true",
        "limit": limit,
        "order": "startDate",
        "ascending": "false",
        "tag_slug": "sports",
    }
    resp = sess.get(f"{GAMMA_BASE}/events", params=params, timeout=20)
    resp.raise_for_status()
    events = resp.json()
    if not isinstance(events, list):
        log.warning("Unexpected response shape from Gamma API: %r", type(events))
        return []

    leagues = list(leagues)
    out: list[MarketEvent] = []
    for ev in events:
        league = _match_league(ev, leagues)
        if not league:
            continue
        out.append(
            MarketEvent(
                id=str(ev.get("id")),
                title=ev.get("title") or "(untitled)",
                slug=ev.get("slug") or "",
                league=league,
                end_date=ev.get("endDate"),
                volume=ev.get("volume"),
            )
        )
    return out
