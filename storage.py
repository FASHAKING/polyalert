"""SQLite tracker for events already announced to Telegram."""
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
