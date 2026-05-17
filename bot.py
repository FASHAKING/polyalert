"""Polymarket -> Telegram new-sports-market notifier with live commands."""
from __future__ import annotations

import html
import logging
import os
import signal
import sys
import time

import requests
from dotenv import load_dotenv

from polymarket import (
    ALL_LEAGUES,
    LEAGUE_LABELS,
    MarketEvent,
    fetch_new_sports_events,
)
from storage import SeenStore
from telegram_client import TelegramClient


COMMANDS = [
    ("status", "Show current filters and bot stats"),
    ("leagues", "List all available leagues with on/off state"),
    ("add", "Enable a league: /add nfl"),
    ("remove", "Disable a league: /remove nfl"),
    ("help", "Show available commands"),
]

TICK_SECONDS = 2  # how often we drain Telegram updates


# ---------- formatting helpers ----------

def _label(league: str) -> str:
    return LEAGUE_LABELS.get(league, league.upper())


def format_event(ev: MarketEvent) -> str:
    title = html.escape(ev.title)
    lines = [f"<b>[{_label(ev.league)}] New Polymarket event</b>", title]
    if ev.end_date:
        lines.append(f"Ends: {html.escape(ev.end_date)}")
    lines.append(ev.url)
    return "\n".join(lines)


def format_status(store: SeenStore, interval: int) -> str:
    leagues = store.get_leagues()
    if leagues:
        active = "\n".join(f"  • {_label(l)} (<code>{l}</code>)" for l in leagues)
    else:
        active = "  <i>(none — bot will not notify until you /add one)</i>"
    return (
        "<b>poltalert status</b>\n"
        f"Active leagues:\n{active}\n\n"
        f"Poll interval: {interval}s\n"
        f"Events notified so far: {store.count()}"
    )


def format_leagues_list(store: SeenStore) -> str:
    active = set(store.get_leagues())
    rows = []
    for slug in ALL_LEAGUES:
        mark = "✅" if slug in active else "▫️"
        rows.append(f"{mark} <code>{slug}</code> — {_label(slug)}")
    return (
        "<b>Available leagues</b>\n"
        + "\n".join(rows)
        + "\n\nUse <code>/add &lt;slug&gt;</code> or <code>/remove &lt;slug&gt;</code>."
    )


HELP_TEXT = (
    "<b>poltalert commands</b>\n"
    "/status — current filters and stats\n"
    "/leagues — list all leagues with on/off state\n"
    "/add &lt;slug&gt; — enable a league (e.g. <code>/add nfl</code>)\n"
    "/remove &lt;slug&gt; — disable a league\n"
    "/help — this message"
)


# ---------- command handlers ----------

def handle_command(
    cmd: str,
    args: list[str],
    store: SeenStore,
    tg: TelegramClient,
    interval: int,
    http: requests.Session,
    log: logging.Logger,
) -> str:
    cmd = cmd.lower()

    if cmd in ("start", "help"):
        return HELP_TEXT

    if cmd == "status":
        return format_status(store, interval)

    if cmd == "leagues":
        return format_leagues_list(store)

    if cmd == "add":
        if not args:
            return "Usage: <code>/add &lt;slug&gt;</code>. See /leagues for valid slugs."
        added, unknown, already = [], [], []
        current = set(store.get_leagues())
        for raw in args:
            slug = raw.lower().lstrip("/")
            if slug not in ALL_LEAGUES:
                unknown.append(slug)
            elif slug in current:
                already.append(slug)
            else:
                current.add(slug)
                added.append(slug)
        store.set_leagues(sorted(current))

        # Silently bootstrap newly added leagues so we don't blast the user
        # with the entire current backlog of that league.
        if added:
            try:
                events = fetch_new_sports_events(added, session=http)
                for ev in events:
                    if not store.has(ev.id):
                        store.add(ev.id, ev.league, ev.title)
                log.info("Bootstrapped %d existing event(s) for %s", len(events), added)
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
        current = set(store.get_leagues())
        for raw in args:
            slug = raw.lower().lstrip("/")
            if slug in current:
                current.discard(slug)
                removed.append(slug)
            else:
                missing.append(slug)
        store.set_leagues(sorted(current))
        parts = []
        if removed:
            parts.append("Removed: " + ", ".join(f"<code>{s}</code>" for s in removed))
        if missing:
            parts.append("Wasn't active: " + ", ".join(f"<code>{s}</code>" for s in missing))
        parts.append("")
        parts.append(format_status(store, interval))
        return "\n".join(parts)

    return f"Unknown command: <code>/{html.escape(cmd)}</code>. Try /help."


def parse_command(text: str) -> tuple[str, list[str]] | None:
    """Return (command, args) for messages like '/add nfl nba'."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    if not parts:
        return None
    cmd = parts[0]
    # Strip @botname suffix (Telegram appends it in groups).
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
            reply = handle_command(cmd, args, store, tg, interval, http, log)
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
    *,
    silent_bootstrap: bool,
) -> bool:
    """Fetch and notify. Returns True if bootstrap silenced this round."""
    leagues = store.get_leagues()
    if not leagues:
        log.info("No leagues active — skipping poll. Use /add via Telegram.")
        return False

    try:
        events = fetch_new_sports_events(leagues, session=http)
    except Exception as e:
        log.exception("Polymarket fetch failed: %s", e)
        return False

    log.info("Fetched %d matching event(s).", len(events))
    for ev in events:
        if store.has(ev.id):
            continue
        if silent_bootstrap:
            store.add(ev.id, ev.league, ev.title)
            continue
        msg = format_event(ev)
        if tg.send_message(msg):
            store.add(ev.id, ev.league, ev.title)
            log.info("Notified: [%s] %s", ev.league, ev.title)
        else:
            log.warning("Send failed, will retry next cycle: %s", ev.title)
    return silent_bootstrap


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

    # Seed leagues from env on first run only; afterwards leagues live in the DB
    # and are mutated by /add and /remove.
    if not store.get_leagues():
        env_leagues = [
            s.strip().lower()
            for s in os.environ.get("LEAGUES", "nfl,nba,mlb,soccer,epl,champions-league").split(",")
            if s.strip()
        ]
        store.set_leagues(env_leagues)
        log.info("Seeded leagues from env: %s", env_leagues)

    tg = TelegramClient(token, str(authorized_chat_id))
    http = requests.Session()

    # Register the command menu with Telegram (best-effort).
    try:
        tg.set_my_commands(COMMANDS)
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)

    log.info(
        "Starting: leagues=%s interval=%ss seen=%d",
        store.get_leagues(), interval, store.count(),
    )

    stop = {"flag": False}

    def _handle_signal(signum, _frame):
        log.info("Received signal %s, shutting down.", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # On first run (no seen events yet), silently mark current matches so the
    # user doesn't get a wall of notifications for the existing backlog.
    first_run = store.count() == 0
    last_poll = 0.0

    while not stop["flag"]:
        # 1) Drain Telegram commands every tick.
        drain_updates(tg, store, authorized_chat_id, http, interval, log)

        # 2) Poll Polymarket on the configured interval.
        now = time.time()
        if now - last_poll >= interval:
            silenced = poll_polymarket(store, tg, http, log, silent_bootstrap=first_run)
            if silenced:
                log.info("Bootstrap complete: %d event(s) marked as seen.", store.count())
                first_run = False
            last_poll = now

        # Short sleep so commands feel responsive.
        slept = 0
        while slept < TICK_SECONDS and not stop["flag"]:
            time.sleep(0.5)
            slept += 0.5

    log.info("Stopped.")


if __name__ == "__main__":
    run()
