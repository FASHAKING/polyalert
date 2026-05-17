"""Polymarket -> Telegram new-sports-market notifier."""
from __future__ import annotations

import html
import logging
import os
import signal
import sys
import time

import requests
from dotenv import load_dotenv

from polymarket import MarketEvent, fetch_new_sports_events
from storage import SeenStore
from telegram_client import TelegramClient


LEAGUE_LABELS = {
    "nfl": "NFL",
    "nba": "NBA",
    "mlb": "MLB",
    "soccer": "Soccer",
    "epl": "EPL",
    "champions-league": "Champions League",
}


def _format_message(ev: MarketEvent) -> str:
    label = LEAGUE_LABELS.get(ev.league, ev.league.upper())
    title = html.escape(ev.title)
    lines = [f"<b>[{label}] New Polymarket event</b>", title]
    if ev.end_date:
        lines.append(f"Ends: {html.escape(ev.end_date)}")
    lines.append(ev.url)
    return "\n".join(lines)


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
    chat_id = _require_env("TELEGRAM_CHAT_ID")
    leagues = [
        s.strip().lower()
        for s in os.environ.get("LEAGUES", "nfl,nba,mlb,soccer,epl,champions-league").split(",")
        if s.strip()
    ]
    interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
    db_path = os.environ.get("DB_PATH", "seen.db")

    store = SeenStore(db_path)
    tg = TelegramClient(token, chat_id)
    http = requests.Session()

    log.info("Starting poller: leagues=%s interval=%ss seen=%d", leagues, interval, store.count())

    stop = {"flag": False}

    def _handle_signal(signum, _frame):
        log.info("Received signal %s, shutting down after current cycle.", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Bootstrap: on first run, mark currently-listed events as seen so we don't
    # spam-notify on the entire backlog. Skip this if the DB already has rows.
    first_run = store.count() == 0

    while not stop["flag"]:
        try:
            events = fetch_new_sports_events(leagues, session=http)
            log.info("Fetched %d matching event(s).", len(events))
        except Exception as e:  # network / API errors shouldn't kill the loop
            log.exception("Fetch failed: %s", e)
            events = []

        for ev in events:
            if store.has(ev.id):
                continue
            if first_run:
                store.add(ev.id, ev.league, ev.title)
                continue
            msg = _format_message(ev)
            if tg.send_message(msg):
                store.add(ev.id, ev.league, ev.title)
                log.info("Notified: [%s] %s", ev.league, ev.title)
            else:
                log.warning("Send failed, will retry next cycle: %s", ev.title)

        if first_run:
            log.info("Bootstrap complete: %d existing event(s) marked as seen.", store.count())
            first_run = False

        # Sleep in small chunks so signals are responsive.
        slept = 0
        while slept < interval and not stop["flag"]:
            time.sleep(min(2, interval - slept))
            slept += 2

    log.info("Stopped.")


if __name__ == "__main__":
    run()
