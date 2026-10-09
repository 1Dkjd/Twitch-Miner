"""SQLite persistence (spec §7, phase-1 subset: session, lists, settings, events).

Synchronous sqlite3. Every call is a few milliseconds, so the runner calls it directly.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Prefs
from .twitch.session import TwitchSession

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS session (
  id INTEGER PRIMARY KEY CHECK (id = 1), access_token TEXT NOT NULL, user_id INTEGER NOT NULL,
  login TEXT NOT NULL, device_id TEXT NOT NULL, client_id TEXT NOT NULL, session_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS priority (position INTEGER PRIMARY KEY, game_name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS never (game_name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS favourites (position INTEGER PRIMARY KEY, channel_login TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS events (at TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
"""
EVENT_RETENTION = timedelta(days=7)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        self._db = sqlite3.connect(path)
        if new and os.name == "posix":
            os.chmod(path, 0o600)
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- session
    def get_session(self) -> TwitchSession | None:
        row = self._db.execute(
            "SELECT access_token, user_id, login, device_id, client_id, session_id FROM session"
        ).fetchone()
        return TwitchSession(*row) if row else None

    def set_session(self, s: TwitchSession) -> None:
        with self._db:
            self._db.execute("DELETE FROM session")
            self._db.execute(
                "INSERT INTO session VALUES (1, ?, ?, ?, ?, ?, ?)",
                (s.access_token, s.user_id, s.login, s.device_id, s.client_id, s.session_id),
            )

    def clear_session(self) -> None:
        with self._db:
            self._db.execute("DELETE FROM session")

    # --- lists and settings
    def get_prefs(self) -> Prefs:
        pr = tuple(r[0] for r in self._db.execute("SELECT game_name FROM priority ORDER BY position"))
        nv = frozenset(r[0] for r in self._db.execute("SELECT game_name FROM never"))
        fv = tuple(
            r[0] for r in self._db.execute("SELECT channel_login FROM favourites ORDER BY position")
        )
        return Prefs(pr, nv, fv, self.get_setting("mine_badges") == "1")

    def set_lists(
        self, priority: Sequence[str], never: Iterable[str], favourites: Sequence[str]
    ) -> None:
        with self._db:
            self._db.execute("DELETE FROM priority")
            self._db.execute("DELETE FROM never")
            self._db.execute("DELETE FROM favourites")
            self._db.executemany("INSERT INTO priority VALUES (?, ?)", enumerate(priority))
            self._db.executemany("INSERT INTO never VALUES (?)", [(g,) for g in never])
            self._db.executemany("INSERT INTO favourites VALUES (?, ?)", enumerate(favourites))

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # --- events
    def log_event(self, kind: str, data: dict) -> None:
        now = datetime.now(UTC)
        with self._db:
            self._db.execute(
                "INSERT INTO events VALUES (?, ?, ?)", (now.isoformat(), kind, json.dumps(data))
            )
            self._db.execute(
                "DELETE FROM events WHERE at < ?", ((now - EVENT_RETENTION).isoformat(),)
            )

    def recent_events(self, limit: int = 100) -> list[tuple[str, str, dict]]:
        rows = self._db.execute(
            "SELECT at, kind, data FROM events ORDER BY at DESC LIMIT ?", (limit,)
        )
        return [(kind, at, json.loads(data)) for at, kind, data in rows]
