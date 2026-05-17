"""Polymarket Gamma API client."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import requests

from filters import CATEGORIES, REGISTRY, group_active_by_category, match_event

log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_EVENT_URL = "https://polymarket.com/event"


@dataclass
class MarketEvent:
    id: str
    title: str
    slug: str
    filter_slug: str | None      # which filter matched (None for search results)
    end_date: str | None
    volume: float | None

    @classmethod
    def from_dict(cls, ev: dict, filter_slug: str | None) -> "MarketEvent":
        return cls(
            id=str(ev.get("id")),
            title=ev.get("title") or "(untitled)",
            slug=ev.get("slug") or "",
            filter_slug=filter_slug,
            end_date=ev.get("endDate"),
            volume=ev.get("volume"),
        )

    @property
    def url(self) -> str:
        return f"{POLYMARKET_EVENT_URL}/{self.slug}" if self.slug else POLYMARKET_EVENT_URL


def _fetch(session: requests.Session, params: dict) -> list[dict]:
    resp = session.get(f"{GAMMA_BASE}/events", params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def fetch_matching_events(
    active_slugs: Iterable[str],
    *,
    limit: int = 100,
    session: requests.Session | None = None,
) -> list[MarketEvent]:
    """Fetch open events that match any of the active filter slugs.

    One Gamma call per category (so we don't pull the firehose). Within a
    category, each event is matched against that category's active filters
    by tag-slug intersection first, then title-keyword fallback.
    """
    sess = session or requests.Session()
    grouped = group_active_by_category(list(active_slugs))
    out: list[MarketEvent] = []

    for cat_slug, filters in grouped.items():
        cat = CATEGORIES.get(cat_slug)
        params: dict = {
            "closed": "false",
            "active": "true",
            "limit": limit,
            "order": "startDate",
            "ascending": "false",
        }
        if cat and cat.parent_tag:
            params["tag_slug"] = cat.parent_tag

        try:
            events = _fetch(sess, params)
        except Exception as e:
            log.exception("Fetch failed for category %s: %s", cat_slug, e)
            continue

        for ev in events:
            matched = match_event(ev, filters)
            if matched is None:
                continue
            out.append(MarketEvent.from_dict(ev, matched.slug))

    return out


def list_filter_events(
    filter_slug: str,
    query: str | None = None,
    *,
    session: requests.Session | None = None,
    page_size: int = 200,
    max_results: int = 10,
) -> tuple[list[MarketEvent], str | None]:
    """List currently-available events for a specific filter, optional sub-query.

    Returns ``(events, error)``. On success ``error`` is None. On unknown
    filter slug ``error`` describes the problem and ``events`` is empty.
    Events are scoped to the filter's category (one Gamma call), matched
    against the filter's tag/keyword rules, then optionally narrowed by a
    case-insensitive substring match in title/slug/description.
    """
    f = REGISTRY.get(filter_slug.lower())
    if f is None:
        return [], f"Unknown filter: {filter_slug!r}. Use /filters to see valid slugs."

    cat = CATEGORIES.get(f.category)
    params: dict = {
        "closed": "false",
        "active": "true",
        "limit": page_size,
        "order": "volume24hr",
        "ascending": "false",
    }
    if cat and cat.parent_tag:
        params["tag_slug"] = cat.parent_tag

    sess = session or requests.Session()
    try:
        events = _fetch(sess, params)
    except Exception as e:
        log.exception("list fetch failed: %s", e)
        return [], f"Failed to reach Polymarket: {e}"

    q = (query or "").strip().lower()
    out: list[MarketEvent] = []
    for ev in events:
        if match_event(ev, [f]) is None:
            continue
        if q:
            title = (ev.get("title") or "").lower()
            slug = (ev.get("slug") or "").lower()
            description = (ev.get("description") or "").lower()
            if q not in title and q not in slug and q not in description:
                continue
        out.append(MarketEvent.from_dict(ev, f.slug))
        if len(out) >= max_results:
            break
    return out, None


def search_events(
    query: str,
    *,
    session: requests.Session | None = None,
    page_size: int = 200,
    max_results: int = 10,
) -> list[MarketEvent]:
    """Free-text search across currently-listed events.

    Substring-matches the query against event title and slug. Useful for
    finding markets about a specific player, manager, club, candidate, or
    coin. Only searches active, open markets.
    """
    q = (query or "").strip().lower()
    if not q:
        return []

    sess = session or requests.Session()
    try:
        events = _fetch(
            sess,
            {
                "closed": "false",
                "active": "true",
                "limit": page_size,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
    except Exception as e:
        log.exception("search fetch failed: %s", e)
        return []

    hits: list[MarketEvent] = []
    for ev in events:
        title = (ev.get("title") or "").lower()
        slug = (ev.get("slug") or "").lower()
        description = (ev.get("description") or "").lower()
        if q in title or q in slug or q in description:
            # Try to attribute it to a filter for nicer display, but don't require one.
            attribution = match_event(ev, list(REGISTRY.values()))
            hits.append(MarketEvent.from_dict(ev, attribution.slug if attribution else None))
            if len(hits) >= max_results:
                break
    return hits
