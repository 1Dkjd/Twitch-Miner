"""SQLite persistence (spec §7, phase-1 subset: session, lists, settings, events).

Synchronous sqlite3. Every call is a few milliseconds, so the runner calls it directly.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

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
CREATE TABLE IF NOT EXISTS claims (at TEXT NOT NULL, campaign_id TEXT NOT NULL, campaign TEXT NOT NULL,
  game TEXT NOT NULL, rewards TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS web_sessions (token_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seen_channels (login TEXT PRIMARY KEY, game TEXT NOT NULL,
  last_seen TEXT NOT NULL);
"""
CLAIM_DETAIL_COLUMNS = (("minutes", "INTEGER"), ("channel", "TEXT"), ("campaign_rewards", "INTEGER"),
                        ("campaign_ends", "TEXT"), ("box_art_url", "TEXT"))
EVENT_RETENTION = timedelta(days=7)
SESSION_TTL = timedelta(days=30)
SEEN_KEEP = timedelta(days=30)  # channels seen live, for the favourites add box
MIN_PASSWORD = 8
SETTINGS: dict[str, type] = {
    "mine_badges": bool, "claim_points": bool, "notify_target": str,
    "notify_claimed": bool, "notify_needs_you": bool, "notify_signin": bool,
}
SETTING_DEFAULTS = {"mine_badges": False, "claim_points": True, "notify_target": "",
                    "notify_claimed": True, "notify_needs_you": True, "notify_signin": True}
_ph = PasswordHasher()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        self._db = sqlite3.connect(path)
        if new and os.name == "posix":
            os.chmod(path, 0o600)
        self._db.executescript(SCHEMA)
        # 2026-10-10: claim details for History; rows from before read back as NULL (not recorded)
        have = {row[1] for row in self._db.execute("PRAGMA table_info(claims)")}
        for col, kind in CLAIM_DETAIL_COLUMNS:
            if col not in have:
                self._db.execute(f"ALTER TABLE claims ADD COLUMN {col} {kind}")
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
        return Prefs(pr, nv, fv, self.get_settings()["mine_badges"])

    def set_lists(
        self, priority: Sequence[str], never: Iterable[str], favourites: Sequence[str]
    ) -> None:
        pr = list(dict.fromkeys(priority))
        fv = list(dict.fromkeys(f.strip().lower() for f in favourites if f.strip()))
        with self._db:
            self._db.execute("DELETE FROM priority")
            self._db.execute("DELETE FROM never")
            self._db.execute("DELETE FROM favourites")
            self._db.executemany("INSERT INTO priority VALUES (?, ?)", enumerate(pr))
            self._db.executemany("INSERT INTO never VALUES (?)", [(g,) for g in dict.fromkeys(never)])
            self._db.executemany("INSERT INTO favourites VALUES (?, ?)", enumerate(fv))

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

    # --- typed settings
    def get_settings(self) -> dict:
        out = dict(SETTING_DEFAULTS)
        for key, kind in SETTINGS.items():
            raw = self.get_setting(key)
            if raw is not None:
                out[key] = (raw == "1") if kind is bool else raw
        return out

    def put_settings(self, values: dict) -> dict:
        for key, value in values.items():
            kind = SETTINGS.get(key)
            if kind is None:
                raise ValueError(f"unknown setting {key!r}")
            if type(value) is not kind:
                raise ValueError(f"{key} must be {kind.__name__}")
        for key, value in values.items():
            self.set_setting(key, ("1" if value else "0") if SETTINGS[key] is bool else value)
        return self.get_settings()

    # --- claims
    def add_claim(self, at: datetime, campaign_id: str, campaign: str, game: str,
                  rewards: list[tuple[str, str]], *, minutes: int | None = None, channel: str | None = None,
                  campaign_rewards: int | None = None, campaign_ends: datetime | None = None,
                  box_art_url: str | None = None) -> None:
        """minutes: the watch time the drop needed; channel: where it was mined (None when not known)."""
        payload = json.dumps([{"name": n, "image_url": u} for n, u in rewards])
        ends = campaign_ends.astimezone(UTC).isoformat() if campaign_ends else None
        with self._db:
            self._db.execute(
                "INSERT INTO claims (at, campaign_id, campaign, game, rewards, minutes, channel,"
                " campaign_rewards, campaign_ends, box_art_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (at.astimezone(UTC).isoformat(), campaign_id, campaign, game, payload, minutes, channel,
                 campaign_rewards, ends, box_art_url or None))

    def claims_since(self, since: datetime) -> list[dict]:
        rows = self._db.execute(
            "SELECT at, campaign_id, campaign, game, rewards, minutes, channel, campaign_rewards,"
            " campaign_ends, box_art_url FROM claims WHERE at >= ? ORDER BY at DESC",
            (since.astimezone(UTC).isoformat(),))
        return [{"at": datetime.fromisoformat(at), "campaign_id": cid, "campaign": camp, "game": game,
                 "rewards": json.loads(rw), "minutes": mins, "channel": ch, "campaign_rewards": total,
                 "campaign_ends": datetime.fromisoformat(ends) if ends else None, "box_art_url": art}
                for at, cid, camp, game, rw, mins, ch, total, ends, art in rows]

    # --- page password (argon2) and web sessions (sha256 of the token only)
    def has_password(self) -> bool:
        return self.get_setting("page_password_hash") is not None

    def set_password(self, plain: str) -> None:
        if len(plain) < MIN_PASSWORD:
            raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
        self.set_setting("page_password_hash", _ph.hash(plain))

    def check_password(self, plain: str) -> bool:
        h = self.get_setting("page_password_hash")
        if h is None:
            return False
        try:
            return _ph.verify(h, plain)
        except VerificationError:
            return False

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_web_session(self, now: datetime) -> str:
        token = secrets.token_urlsafe(32)
        with self._db:
            self._db.execute("INSERT INTO web_sessions VALUES (?, ?)",
                             (self._token_hash(token), (now + SESSION_TTL).astimezone(UTC).isoformat()))
            self._db.execute("DELETE FROM web_sessions WHERE expires_at < ?",
                             (now.astimezone(UTC).isoformat(),))
        return token

    def valid_web_session(self, token: str | None, now: datetime) -> bool:
        if not token:
            return False
        row = self._db.execute("SELECT expires_at FROM web_sessions WHERE token_hash = ?",
                               (self._token_hash(token),)).fetchone()
        return bool(row) and datetime.fromisoformat(row[0]) > now

    # --- channels seen live (favourites suggestions; spec §8 /api/suggestions)
    def record_seen(self, channels: list[tuple[str, str]], at: datetime) -> None:
        stamp = at.astimezone(UTC).isoformat()
        with self._db:
            self._db.executemany(
                "INSERT INTO seen_channels VALUES (?, ?, ?) ON CONFLICT(login) DO UPDATE SET "
                "game = excluded.game, last_seen = excluded.last_seen",
                [(lg, g, stamp) for lg, g in channels])
            self._db.execute("DELETE FROM seen_channels WHERE last_seen < ?",
                             ((at - SEEN_KEEP).astimezone(UTC).isoformat(),))

    def seen_channels(self, now: datetime) -> list[dict]:
        since = (now - SEEN_KEEP).astimezone(UTC).isoformat()
        rows = self._db.execute("SELECT login, game, last_seen FROM seen_channels WHERE last_seen >= ? "
                                "ORDER BY last_seen DESC, login", (since,))
        return [{"login": lg, "game": g, "last_seen": datetime.fromisoformat(t)} for lg, g, t in rows]

    def delete_web_session(self, token: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM web_sessions WHERE token_hash = ?", (self._token_hash(token),))
