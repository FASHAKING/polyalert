"""Polymarket -> Telegram notifier with live commands and free-text search."""
from __future__ import annotations

import html
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

import filters as flt
from polymarket import (
    MarketEvent,
    fetch_matching_events,
    list_filter_events,
    search_events,
    top_events,
)
from storage import SeenStore
from telegram_client import TelegramClient


COMMANDS = [
    ("status", "Show current filters and stats"),
    ("filters", "List all available filters by category"),
    ("add", "Enable a filter: /add nfl"),
    ("remove", "Disable a filter: /remove nfl"),
    ("search", "Search markets: /search [scope] query"),
    ("markets", "List markets in a filter: /markets nba chicago bulls"),
    ("top", "Top live markets by volume: /top [filter]"),
    ("watch", "Add keyword alert: /watch world-cup"),
    ("watches", "List keyword alerts"),
    ("unwatch", "Remove keyword alert: /unwatch world-cup"),
    ("pause", "Pause new-market notifications"),
    ("resume", "Resume new-market notifications"),
    ("interval", "Set poll interval: /interval 600"),
    ("recent", "Show notified events, grouped by day: /recent [filter] [day] [count]"),
    ("help", "Show available commands"),
]

POLYMARKET_EVENT_URL = "https://polymarket.com/event"


def _title_link(title: str, slug: str) -> str:
    """Return the title as a clickable HTML link if slug is non-empty,
    otherwise plain bold text. The URL itself is not rendered."""
    safe_title = html.escape(title)
    if slug:
        return f'<a href="{POLYMARKET_EVENT_URL}/{html.escape(slug)}"><b>{safe_title}</b></a>'
    return f"<b>{safe_title}</b>"


def _emoji_label(slug: str | None) -> str:
    """Return e.g. '🏈 NFL' for known slugs or a keyword-watch label."""
    if not slug:
        return ""
    if slug.startswith("watch:"):
        return f"🔎 Watch: {slug.split(':', 1)[1]}"
    em = flt.emoji_for(slug)
    label = flt.label_for(slug)
    return f"{em} {label}".strip()


def _poll_interval(store: SeenStore, fallback: int) -> int:
    return store.get_poll_interval(fallback)


TICK_SECONDS = 2


# ---------- formatting helpers ----------

def format_event(ev: MarketEvent) -> str:
    label = _emoji_label(ev.filter_slug) or "🆕 Polymarket"
    lines = [f"🆕 <b>{html.escape(label)}</b>", _title_link(ev.title, ev.slug)]
    if ev.end_date:
        lines.append(f"🕒 Ends {html.escape(ev.end_date)}")
    if ev.volume:
        lines.append(f"📊 24h volume ${ev.volume:,.0f}")
    return "\n".join(lines)


def format_search_hit(i: int, ev: MarketEvent) -> str:
    label = _emoji_label(ev.filter_slug)
    bracket = f"[{html.escape(label)}] " if label else ""
    extras = []
    if ev.end_date:
        extras.append(f"ends {html.escape(ev.end_date)}")
    if ev.volume:
        extras.append(f"vol ${ev.volume:,.0f}")
    suffix = f"\n   <i>{' · '.join(extras)}</i>" if extras else ""
    return f"{i}. {bracket}{_title_link(ev.title, ev.slug)}{suffix}"


def format_status(store: SeenStore, interval: int) -> str:
    active = store.get_filters()
    watches = store.get_keyword_watches()
    if not active:
        body = "  <i>(none — bot will not notify until you /add one)</i>"
    else:
        grouped = flt.group_active_by_category(active)
        rows = []
        for cat_slug, fs in grouped.items():
            cat = flt.CATEGORIES.get(cat_slug)
            cat_em = cat.emoji if cat else ""
            rows.append(f"<b>{cat_em} {flt.category_label(cat_slug)}</b>".strip())
            for f in fs:
                em = f.emoji or (cat.emoji if cat else "")
                rows.append(f"  {em} {f.label} (<code>{f.slug}</code>)")
        body = "\n".join(rows)
    watch_body = "  <i>(none)</i>" if not watches else "\n".join(f"  🔎 <code>{html.escape(w)}</code>" for w in watches)
    state = "⏸ Paused" if store.is_paused() else "▶️ Running"
    return (
        "📡 <b>polyalert status</b>\n\n"
        f"State: {state}\n"
        f"<b>Active filters</b>\n{body}\n\n"
        f"<b>Keyword watches</b>\n{watch_body}\n\n"
        f"⏱ Poll interval: {interval}s\n"
        f"🔔 Events notified so far: {store.count()}"
    )


def format_filters_list(store: SeenStore) -> str:
    active = set(store.get_filters())
    lines = ["<b>Available filters</b>"]
    for cat_slug, fs in flt.by_category().items():
        if not fs:
            continue
        cat = flt.CATEGORIES.get(cat_slug)
        cat_em = cat.emoji if cat else ""
        lines.append(f"\n<b>{cat_em} {flt.category_label(cat_slug)}</b>".strip())
        for f in fs:
            mark = "✅" if f.slug in active else "▫️"
            em = f.emoji or (cat.emoji if cat else "")
            lines.append(f"  {mark} {em} <code>{f.slug}</code> — {f.label}")
    lines.append("\nUse <code>/add &lt;slug&gt;</code> or <code>/remove &lt;slug&gt;</code>.")
    return "\n".join(lines)


HELP_TEXT = (
    "<b>polyalert commands</b>\n"
    "/status — current filters and stats\n"
    "/filters — list all filters by category\n"
    "/add &lt;slug&gt; — enable a filter (e.g. <code>/add nfl</code>)\n"
    "/remove &lt;slug&gt; — disable a filter\n"
    "/search [filter|category] &lt;query&gt; — search live markets; hyphens are normalized "
    "(e.g. <code>/search soccer world-cup</code>, <code>/search world-cup</code>)\n"
    "/markets &lt;filter&gt; [query] — list live markets in a filter "
    "(e.g. <code>/markets world-cup</code>, <code>/markets nba chicago bulls</code>)\n"
    "/top [filter|category] — top live markets by 24h volume\n"
    "/watch &lt;keyword&gt; — alert on any new market matching custom text (e.g. <code>/watch world-cup</code>)\n"
    "/unwatch &lt;keyword&gt; — remove a custom keyword watch\n"
    "/pause and /resume — pause/resume notification polling without losing commands\n"
    "/interval &lt;seconds&gt; — change poll interval live (minimum 30)\n"
    "/recent [filter] [day] [count] — events the bot has already notified, grouped by day. "
    "Day can be <code>today</code>, <code>yesterday</code>, <code>Nd</code> (last N days), or <code>YYYY-MM-DD</code>. "
    "Examples: <code>/recent</code>, <code>/recent today</code>, <code>/recent nfl 7d</code>\n"
    "/help — this message"
)


# ---------- /recent helpers ----------

def _parse_day_arg(token: str) -> tuple[str, str] | None:
    """Recognise day-spec tokens. Return (kind, YYYY-MM-DD) where kind is
    'on' (single day) or 'since' (inclusive lower bound). None if not a
    day spec."""
    today = datetime.now().date()
    if token == "today":
        return ("on", today.isoformat())
    if token == "yesterday":
        return ("on", (today - timedelta(days=1)).isoformat())
    if len(token) > 1 and token.endswith("d") and token[:-1].isdigit():
        n = int(token[:-1])
        if n >= 1:
            return ("since", (today - timedelta(days=n - 1)).isoformat())
    if len(token) == 10 and token[4] == "-" and token[7] == "-":
        try:
            datetime.strptime(token, "%Y-%m-%d")
            return ("on", token)
        except ValueError:
            pass
    return None


def _day_label(day_iso: str) -> str:
    """Human label for a YYYY-MM-DD: 'Today', 'Yesterday', or 'Mon 15'."""
    today = datetime.now().date()
    if day_iso == today.isoformat():
        return "Today"
    if day_iso == (today - timedelta(days=1)).isoformat():
        return "Yesterday"
    try:
        dt = datetime.strptime(day_iso, "%Y-%m-%d")
        return f"{dt.strftime('%b')} {dt.day}"  # %-d isn't portable on Windows
    except ValueError:
        return day_iso


def _row_local_parts(first_seen: str) -> tuple[str, str]:
    """Convert a seen_events.first_seen UTC string -> (local YYYY-MM-DD, HH:MM)."""
    if not isinstance(first_seen, str):
        return ("?", "")
    try:
        # SQLite CURRENT_TIMESTAMP yields "YYYY-MM-DD HH:MM:SS" in UTC.
        dt_utc = datetime.strptime(first_seen.split(".")[0], "%Y-%m-%d %H:%M:%S")
        local = dt_utc.replace(tzinfo=timezone.utc).astimezone()
        return (local.date().isoformat(), local.strftime("%H:%M"))
    except (ValueError, AttributeError):
        return (first_seen[:10], first_seen[11:16] if len(first_seen) > 16 else "")


RECENT_USAGE = (
    "Usage: <code>/recent [filter] [day] [count]</code>\n"
    "Args are order-insensitive. Day can be:\n"
    "  <code>today</code> | <code>yesterday</code> | <code>Nd</code> (last N days) | <code>YYYY-MM-DD</code>\n"
    "Examples:\n"
    "  <code>/recent</code> — last 10, grouped by day\n"
    "  <code>/recent today</code> — only today\n"
    "  <code>/recent nfl yesterday</code>\n"
    "  <code>/recent 7d 50</code> — last 50 from the last 7 days\n"
    "  <code>/recent nba 2026-05-15</code>"
)


def _handle_recent(args: list[str], store: SeenStore) -> str:
    filter_slug: str | None = None
    limit = 10
    on_date: str | None = None
    since_date: str | None = None

    for raw in args:
        a = raw.lower().lstrip("/")
        if a.isdigit():
            limit = max(1, min(int(a), 50))
            continue
        if a in flt.REGISTRY:
            filter_slug = a
            continue
        parsed = _parse_day_arg(a)
        if parsed:
            if on_date or since_date:
                return f"Multiple day specs given. {RECENT_USAGE}"
            kind, value = parsed
            if kind == "on":
                on_date = value
            else:
                since_date = value
            continue
        return f"Unknown argument: <code>{html.escape(a)}</code>\n{RECENT_USAGE}"

    rows = store.recent(
        limit=limit, filter_slug=filter_slug,
        on_date=on_date, since_date=since_date,
    )

    # Header / empty messages
    scope_bits: list[str] = []
    if filter_slug:
        scope_bits.append(html.escape(flt.label_for(filter_slug)))
    if on_date:
        scope_bits.append(f"on {_day_label(on_date)}")
    elif since_date:
        scope_bits.append(f"since {_day_label(since_date)}")
    scope = (" — " + " ".join(scope_bits)) if scope_bits else ""

    if not rows:
        return (
            f"💤 No notified events{scope}.\n"
            "<i>The list populates as new markets get listed.</i>"
        )

    header = f"🔔 <b>Recent notifications</b>{scope} ({len(rows)} shown)"

    def _row_prefix(fs: str | None) -> str:
        label = _emoji_label(fs)
        if filter_slug:
            return f"{html.escape(label)} " if label else ""
        if fs:
            return f"[{html.escape(label or flt.label_for(fs))}] "
        return ""

    # When the query is scoped to a single day, render flat. Otherwise group.
    if on_date:
        lines = [header, ""]
        for i, (_id, fs, title, slug, first_seen) in enumerate(rows, 1):
            _, time_str = _row_local_parts(first_seen)
            entry = f"{i}. {_row_prefix(fs)}{_title_link(title, slug)}"
            if time_str:
                entry += f"  <i>🕒 {time_str}</i>"
            lines.append(entry)
        return "\n".join(lines)

    # Grouped by day (rows are already newest-first)
    groups: dict[str, list[tuple]] = {}
    order: list[str] = []
    for row in rows:
        day_iso, time_str = _row_local_parts(row[4])
        if day_iso not in groups:
            order.append(day_iso)
            groups[day_iso] = []
        groups[day_iso].append((row, time_str))

    lines = [header]
    counter = 0
    for day_iso in order:
        lines.append(f"\n📅 <b>{_day_label(day_iso)}</b>")
        for (row, time_str) in groups[day_iso]:
            counter += 1
            _id, fs, title, slug, _first_seen = row
            entry = f"  {counter}. {_row_prefix(fs)}{_title_link(title, slug)}"
            if time_str:
                entry += f"  <i>🕒 {time_str}</i>"
            lines.append(entry)
    return "\n".join(lines)


# ---------- command handlers ----------

def handle_command(
    cmd: str,
    args: list[str],
    raw_text: str,
    store: SeenStore,
    interval: int,
    http: requests.Session,
    log: logging.Logger,
) -> str:
    cmd = cmd.lower()

    if cmd in ("start", "help"):
        return HELP_TEXT

    if cmd == "status":
        return format_status(store, interval)

    if cmd in ("filters", "leagues"):  # /leagues kept as alias
        return format_filters_list(store)

    if cmd == "pause":
        store.set_paused(True)
        return "⏸ New-market notifications paused. Commands still work; use /resume to restart polling."

    if cmd == "resume":
        store.set_paused(False)
        return "▶️ New-market notifications resumed."

    if cmd == "interval":
        if not args or not args[0].isdigit():
            return "Usage: <code>/interval &lt;seconds&gt;</code> (minimum 30)."
        seconds = max(30, int(args[0]))
        store.set_poll_interval(seconds)
        return f"⏱ Poll interval set to {seconds}s."

    if cmd in ("watch", "watches"):
        if cmd == "watches" or not args:
            watches = store.get_keyword_watches()
            if not watches:
                return "No keyword watches yet. Add one with <code>/watch world-cup</code>."
            return "<b>Keyword watches</b>\n" + "\n".join(f"  🔎 <code>{html.escape(w)}</code>" for w in watches)
        keyword = " ".join(args).strip()
        added = store.add_keyword_watch(keyword)
        status = "Added" if added else "Already watching"
        return f"🔎 {status}: <code>{html.escape(keyword.lower())}</code>"

    if cmd == "unwatch":
        if not args:
            return "Usage: <code>/unwatch &lt;keyword&gt;</code>."
        keyword = " ".join(args).strip()
        removed = store.remove_keyword_watch(keyword)
        if removed:
            return f"Removed keyword watch: <code>{html.escape(keyword.lower())}</code>"
        return f"Was not watching: <code>{html.escape(keyword.lower())}</code>"

    if cmd == "add":
        if not args:
            return "Usage: <code>/add &lt;slug&gt;</code>. See /filters for valid slugs."
        added, unknown, already = [], [], []
        current = set(store.get_filters())
        for raw in args:
            slug = raw.lower().lstrip("/")
            if slug not in flt.REGISTRY:
                unknown.append(slug)
            elif slug in current:
                already.append(slug)
            else:
                current.add(slug)
                added.append(slug)
        store.set_filters(sorted(current))

        # Silently bootstrap newly added filters so we don't blast the user
        # with the entire current backlog of that filter.
        if added:
            try:
                events = fetch_matching_events(added, session=http)
                for ev in events:
                    if not store.has(ev.id):
                        store.add(ev.id, ev.filter_slug or "", ev.title, ev.slug or "")
                log.info("Bootstrapped %d event(s) for %s", len(events), added)
            except Exception as e:
                log.warning("Bootstrap fetch failed for %s: %s", added, e)

        parts = []
        if added:
            parts.append("Added: " + ", ".join(f"<code>{s}</code>" for s in added))
        if already:
            parts.append("Already on: " + ", ".join(f"<code>{s}</code>" for s in already))
        if unknown:
            parts.append("Unknown: " + ", ".join(f"<code>{s}</code>" for s in unknown))
        parts.append("")
        parts.append(format_status(store, interval))
        return "\n".join(parts)

    if cmd == "remove":
        if not args:
            return "Usage: <code>/remove &lt;slug&gt;</code>."
        removed, missing = [], []
        current = set(store.get_filters())
        for raw in args:
            slug = raw.lower().lstrip("/")
            if slug in current:
                current.discard(slug)
                removed.append(slug)
            else:
                missing.append(slug)
        store.set_filters(sorted(current))
        parts = []
        if removed:
            parts.append("Removed: " + ", ".join(f"<code>{s}</code>" for s in removed))
        if missing:
            parts.append("Wasn't active: " + ", ".join(f"<code>{s}</code>" for s in missing))
        parts.append("")
        parts.append(format_status(store, interval))
        return "\n".join(parts)

    if cmd == "search":
        # Supports both plain searches and scoped searches such as
        # /search soccer world-cup. The first arg is treated as an optional
        # filter/category scope only when a second arg exists.
        query = raw_text.split(None, 1)[1].strip() if " " in raw_text else ""
        if not query:
            return (
                "Usage: <code>/search [filter|category] &lt;query&gt;</code>\n"
                "Examples:\n"
                "  <code>/search world-cup</code>\n"
                "  <code>/search soccer world-cup</code>\n"
                "  <code>/search Manchester United</code>"
            )
        scope = None
        search_query = query
        if len(args) >= 2 and args[0].lower().lstrip("/") in {**flt.REGISTRY, **flt.CATEGORIES}:
            scope = args[0].lower().lstrip("/")
            search_query = " ".join(args[1:]).strip()
        hits, err = search_events(search_query, scope=scope, session=http)
        if err:
            return f"⚠️ {html.escape(err)}"
        scope_label = f" in <b>{html.escape(flt.label_for(scope) if scope in flt.REGISTRY else flt.category_label(scope))}</b>" if scope else ""
        if not hits:
            return f"💤 No live markets found{scope_label} matching <i>{html.escape(search_query)}</i>."
        rows = [format_search_hit(i, ev) for i, ev in enumerate(hits, 1)]
        return (
            f"🔍 <b>Search results{scope_label} for <i>{html.escape(search_query)}</i></b> "
            f"({len(hits)} match{'es' if len(hits) != 1 else ''})\n\n"
            + "\n\n".join(rows)
        )

    if cmd == "markets":
        if not args:
            return (
                "Usage: <code>/markets &lt;filter&gt; [query]</code>\n"
                "Examples:\n"
                "  <code>/markets nba</code> — top live NBA markets\n"
                "  <code>/markets nba chicago bulls</code>\n"
                "  <code>/markets soccer manunited</code>\n"
                "  <code>/markets nfl tom brady</code>\n\n"
                "See /filters for valid filter slugs."
            )
        filter_slug = args[0].lower().lstrip("/")
        query = " ".join(args[1:]).strip() or None

        hits, err = list_filter_events(filter_slug, query, session=http)
        if err:
            return f"⚠️ {html.escape(err)}"

        header_label = flt.label_for(filter_slug)
        em = flt.emoji_for(filter_slug)
        scope = f" matching <i>{html.escape(query)}</i>" if query else ""
        if not hits:
            return f"💤 No live {em} <b>{html.escape(header_label)}</b> markets found{scope}."
        rows = [format_search_hit(i, ev) for i, ev in enumerate(hits, 1)]
        return (
            f"{em} <b>{html.escape(header_label)} markets</b>{scope} "
            f"({len(hits)} result{'s' if len(hits) != 1 else ''})\n\n"
            + "\n\n".join(rows)
        ).lstrip()

    if cmd == "top":
        scope = args[0].lower().lstrip("/") if args else None
        hits, err = top_events(scope=scope, session=http)
        if err:
            return f"⚠️ {html.escape(err)}"
        scope_label = ""
        if scope:
            scope_label = f" — {html.escape(flt.label_for(scope) if scope in flt.REGISTRY else flt.category_label(scope))}"
        if not hits:
            return f"💤 No live top markets found{scope_label}."
        rows = [format_search_hit(i, ev) for i, ev in enumerate(hits, 1)]
        return f"📊 <b>Top live markets by 24h volume{scope_label}</b>\n\n" + "\n\n".join(rows)

    if cmd == "recent":
        return _handle_recent(args, store)

    return f"Unknown command: <code>/{html.escape(cmd)}</code>. Try /help."


def parse_command(text: str) -> tuple[str, list[str]] | None:
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    if not parts:
        return None
    cmd = parts[0]
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    return cmd, parts[1:]


def drain_updates(
    tg: TelegramClient,
    store: SeenStore,
    authorized_chat_id: int,
    http: requests.Session,
    interval: int,
    log: logging.Logger,
) -> None:
    offset_raw = store.get_setting("tg_offset")
    offset = int(offset_raw) + 1 if offset_raw else None
    try:
        updates = tg.get_updates(offset=offset, timeout=0, allowed_updates=["message"])
    except Exception as e:
        log.warning("get_updates failed: %s", e)
        return

    for upd in updates:
        store.set_setting("tg_offset", str(upd["update_id"]))
        msg = upd.get("message")
        if not msg:
            continue
        chat_id = msg.get("chat", {}).get("id")
        if chat_id != authorized_chat_id:
            log.info("Ignoring message from unauthorized chat %s", chat_id)
            continue
        text = msg.get("text") or ""
        parsed = parse_command(text)
        if not parsed:
            continue
        cmd, args = parsed
        log.info("Command: /%s %s", cmd, " ".join(args))
        try:
            reply = handle_command(cmd, args, text, store, interval, http, log)
        except Exception as e:
            log.exception("Command handler crashed")
            reply = f"⚠️ Internal error: {html.escape(str(e))}"
        tg.send_message(reply, chat_id=chat_id, disable_preview=True)


# ---------- polling ----------

def poll_polymarket(
    store: SeenStore,
    tg: TelegramClient,
    http: requests.Session,
    log: logging.Logger,
) -> None:
    if store.is_paused():
        log.info("Notifications paused — skipping poll. Use /resume via Telegram.")
        return

    active = store.get_filters()
    watches = store.get_keyword_watches()
    if not active and not watches:
        log.info("No filters or keyword watches active — skipping poll. Use /add or /watch via Telegram.")
        return

    try:
        events = fetch_matching_events(active, keyword_watches=watches, session=http)
    except Exception as e:
        log.exception("Polymarket fetch failed: %s", e)
        return

    log.info("Fetched %d matching event(s).", len(events))
    for ev in events:
        if store.has(ev.id):
            continue
        msg = format_event(ev)
        if tg.send_message(msg):
            store.add(ev.id, ev.filter_slug or "", ev.title, ev.slug or "")
            log.info("Notified: [%s] %s", ev.filter_slug, ev.title)
        else:
            log.warning("Send failed, will retry next cycle: %s", ev.title)


# ---------- entry ----------

def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: required env var {name} is not set", file=sys.stderr)
        sys.exit(1)
    return val


def run() -> None:
    load_dotenv()

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("bot")

    token = _require_env("TELEGRAM_BOT_TOKEN")
    chat_id_raw = _require_env("TELEGRAM_CHAT_ID")
    try:
        authorized_chat_id = int(chat_id_raw)
    except ValueError:
        print(f"ERROR: TELEGRAM_CHAT_ID must be an integer, got: {chat_id_raw!r}", file=sys.stderr)
        sys.exit(1)

    interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
    db_path = os.environ.get("DB_PATH", "seen.db")

    store = SeenStore(db_path)

    # Seed filters on first run only. Afterwards the DB is the source of truth.
    if not store.get_filters():
        env_filters = [
            s.strip().lower()
            for s in os.environ.get(
                "FILTERS",
                os.environ.get("LEAGUES", "nfl,nba,mlb,soccer,world-cup,epl,champions-league"),
            ).split(",")
            if s.strip()
        ]
        store.set_filters(env_filters)
        log.info("Seeded filters from env: %s", env_filters)

    tg = TelegramClient(token, str(authorized_chat_id))
    http = requests.Session()

    try:
        tg.set_my_commands(COMMANDS)
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)

    log.info(
        "Starting: filters=%s interval=%ss seen=%d",
        store.get_filters(), interval, store.count(),
    )

    stop = {"flag": False}

    def _handle_signal(signum, _frame):
        log.info("Received signal %s, shutting down.", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    last_poll = 0.0

    while not stop["flag"]:
        current_interval = _poll_interval(store, interval)
        drain_updates(tg, store, authorized_chat_id, http, current_interval, log)

        now = time.time()
        if now - last_poll >= current_interval:
            poll_polymarket(store, tg, http, log)
            last_poll = now

        slept = 0
        while slept < TICK_SECONDS and not stop["flag"]:
            time.sleep(0.5)
            slept += 0.5

    log.info("Stopped.")


if __name__ == "__main__":
    run()
