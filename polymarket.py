"""Polymarket Gamma API client."""
from __future__ import annotations

import logging
import re
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
            volume=_as_float(ev.get("volume24hr") or ev.get("volume")),
        )

    @property
    def url(self) -> str:
        return f"{POLYMARKET_EVENT_URL}/{self.slug}" if self.slug else POLYMARKET_EVENT_URL


def _as_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_query(value: str) -> str:
    """Normalize user/API text so 'world-cup', 'World Cup', and 'worldcup' match."""
    compact = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return re.sub(r"\s+", " ", compact)


def _squash(value: str) -> str:
    return normalize_query(value).replace(" ", "")


def _event_text(ev: dict) -> str:
    parts = [
        ev.get("title") or "",
        ev.get("slug") or "",
        ev.get("description") or "",
    ]
    for tag in ev.get("tags") or []:
        if tag:
            parts.append(tag.get("slug") or "")
            parts.append(tag.get("label") or tag.get("name") or "")
    return " ".join(parts)


def event_matches_query(ev: dict, query: str) -> bool:
    """Return True when all query words match normalized event text.

    A squashed fallback lets hyphenated terms match natural-language titles,
    e.g. ``world-cup`` -> ``World Cup``.
    """
    normalized_query = normalize_query(query)
    if not normalized_query:
        return True
    normalized_text = normalize_query(_event_text(ev))
    query_terms = normalized_query.split()
    if all(term in normalized_text for term in query_terms):
        return True
    return _squash(normalized_query) in _squash(normalized_text)


def _fetch(session: requests.Session, params: dict) -> list[dict]:
    resp = session.get(f"{GAMMA_BASE}/events", params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _base_params(*, limit: int, order: str = "startDate") -> dict:
    return {
        "closed": "false",
        "active": "true",
        "limit": limit,
        "order": order,
        "ascending": "false",
    }


def _scope_params(scope: str | None, *, limit: int, order: str) -> tuple[dict, str | None, str | None]:
    """Build Gamma params for an optional filter/category scope.

    Returns ``(params, filter_scope, error)``. A filter scope narrows the API
    call to the filter's category parent tag, but does not require the query
    result to match that filter. That keeps commands like
    ``/search soccer world-cup`` useful even when Polymarket tags the event as
    World Cup rather than generic Soccer.
    """
    params = _base_params(limit=limit, order=order)
    filter_scope: str | None = None
    if not scope:
        return params, filter_scope, None

    normalized_scope = scope.lower().strip()
    if normalized_scope in REGISTRY:
        f = REGISTRY[normalized_scope]
        filter_scope = f.slug
        cat = CATEGORIES.get(f.category)
        if cat and cat.parent_tag:
            params["tag_slug"] = cat.parent_tag
        return params, filter_scope, None

    if normalized_scope in CATEGORIES:
        cat = CATEGORIES[normalized_scope]
        if cat.parent_tag:
            params["tag_slug"] = cat.parent_tag
        return params, filter_scope, None

    return params, filter_scope, f"Unknown search scope: {scope!r}. Use a filter slug, category, or omit the scope."


def fetch_matching_events(
    active_slugs: Iterable[str],
    *,
    keyword_watches: Iterable[str] = (),
    limit: int = 100,
    session: requests.Session | None = None,
) -> list[MarketEvent]:
    """Fetch open events that match active filter slugs or keyword watches.

    One Gamma call per active category avoids pulling the firehose for normal
    filters. Keyword watches do one all-events pass because they are arbitrary
    free text.
    """
    sess = session or requests.Session()
    grouped = group_active_by_category(list(active_slugs))
    out: list[MarketEvent] = []
    seen_ids: set[str] = set()

    for cat_slug, filters in grouped.items():
        cat = CATEGORIES.get(cat_slug)
        params = _base_params(limit=limit, order="startDate")
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
            event_id = str(ev.get("id"))
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)
            out.append(MarketEvent.from_dict(ev, matched.slug))

    watches = [w.strip() for w in keyword_watches if w.strip()]
    if watches:
        try:
            events = _fetch(sess, _base_params(limit=limit, order="startDate"))
        except Exception as e:
            log.exception("Keyword watch fetch failed: %s", e)
            events = []
        for ev in events:
            event_id = str(ev.get("id"))
            if event_id in seen_ids:
                continue
            for watch in watches:
                if event_matches_query(ev, watch):
                    seen_ids.add(event_id)
                    out.append(MarketEvent.from_dict(ev, f"watch:{watch}"))
                    break

    return out


def list_filter_events(
    filter_slug: str,
    query: str | None = None,
    *,
    session: requests.Session | None = None,
    page_size: int = 200,
    max_results: int = 10,
) -> tuple[list[MarketEvent], str | None]:
    """List currently-available events for a specific filter, optional sub-query."""
    f = REGISTRY.get(filter_slug.lower())
    if f is None:
        return [], f"Unknown filter: {filter_slug!r}. Use /filters to see valid slugs."

    cat = CATEGORIES.get(f.category)
    params = _base_params(limit=page_size, order="volume24hr")
    if cat and cat.parent_tag:
        params["tag_slug"] = cat.parent_tag

    sess = session or requests.Session()
    try:
        events = _fetch(sess, params)
    except Exception as e:
        log.exception("list fetch failed: %s", e)
        return [], f"Failed to reach Polymarket: {e}"

    out: list[MarketEvent] = []
    for ev in events:
        if match_event(ev, [f]) is None:
            continue
        if query and not event_matches_query(ev, query):
            continue
        out.append(MarketEvent.from_dict(ev, f.slug))
        if len(out) >= max_results:
            break
    return out, None


def search_events(
    query: str,
    *,
    scope: str | None = None,
    session: requests.Session | None = None,
    page_size: int = 200,
    max_results: int = 10,
) -> tuple[list[MarketEvent], str | None]:
    """Free-text search across currently-listed events.

    Hyphens/punctuation are normalized, so ``world-cup`` matches ``World Cup``.
    Pass ``scope`` as a filter or category slug to narrow the API query while
    still searching the remaining query text broadly inside that scope.
    """
    q = (query or "").strip()
    if not q:
        return [], None

    params, _filter_scope, err = _scope_params(scope, limit=page_size, order="volume24hr")
    if err:
        return [], err

    sess = session or requests.Session()
    try:
        events = _fetch(sess, params)
    except Exception as e:
        log.exception("search fetch failed: %s", e)
        return [], f"Failed to reach Polymarket: {e}"

    hits: list[MarketEvent] = []
    for ev in events:
        if event_matches_query(ev, q):
            attribution = match_event(ev, list(REGISTRY.values()))
            hits.append(MarketEvent.from_dict(ev, attribution.slug if attribution else None))
            if len(hits) >= max_results:
                break
    return hits, None


def top_events(
    *,
    scope: str | None = None,
    session: requests.Session | None = None,
    page_size: int = 200,
    max_results: int = 10,
) -> tuple[list[MarketEvent], str | None]:
    """Return top open events by 24h volume, optionally scoped to a filter/category."""
    params, filter_scope, err = _scope_params(scope, limit=page_size, order="volume24hr")
    if err:
        return [], err

    sess = session or requests.Session()
    try:
        events = _fetch(sess, params)
    except Exception as e:
        log.exception("top fetch failed: %s", e)
        return [], f"Failed to reach Polymarket: {e}"

    hits: list[MarketEvent] = []
    filter_obj = REGISTRY.get(filter_scope or "")
    for ev in events:
        attribution = match_event(ev, [filter_obj]) if filter_obj else match_event(ev, list(REGISTRY.values()))
        if filter_obj and attribution is None:
            continue
        hits.append(MarketEvent.from_dict(ev, attribution.slug if attribution else None))
        if len(hits) >= max_results:
            break
    return hits, None
