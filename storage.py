"""SQLite store for seen events and runtime-mutable settings."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_events (
    id TEXT PRIMARY KEY,
    league TEXT NOT NULL,
    title TEXT NOT NULL,
    first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SeenStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- seen events ----

    def has(self, event_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("SELECT 1 FROM seen_events WHERE id = ?", (event_id,))
            return cur.fetchone() is not None

    def add(self, event_id: str, league: str, title: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO seen_events (id, league, title) VALUES (?, ?, ?)",
                (event_id, league, title),
            )

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM seen_events").fetchone()[0]

    # ---- settings (key/value) ----

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ---- filters helper ----

    def get_filters(self) -> list[str]:
        # Backward compat: older installs stored this under 'leagues'.
        raw = self.get_setting("filters")
        if raw is None:
            raw = self.get_setting("leagues") or ""
            if raw:
                self.set_setting("filters", raw)
        return [s.strip().lower() for s in (raw or "").split(",") if s.strip()]

    def set_filters(self, slugs: list[str]) -> None:
        clean = sorted({s.strip().lower() for s in slugs if s.strip()})
        self.set_setting("filters", ",".join(clean))

    # Backward-compatible aliases (older code paths in this repo).
    get_leagues = get_filters
    set_leagues = set_filters
