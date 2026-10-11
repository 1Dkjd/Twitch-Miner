"""Housekeeping for long-running installs (Docker, 2026-10-11): a database copy before an upgrade, and the
miner's health (the Docker health check and the watchdog that exits a stuck miner so Docker restarts it)."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

log = logging.getLogger("dropwatch.maintenance")

BACKUP_KEEP = 2  # copies made before upgrades that are kept (oldest removed first)


def backup_on_upgrade(path: Path, build: str) -> Path | None:
    """Before the Store opens (and migrates) the database: when it was last run by another build, or never
    recorded one but already holds data, copy it to drops.db.before-<build> so the upgrade can be rolled
    back, then record this build. Returns the copy, or None (new install, or the same build)."""
    if not path.exists():
        return None
    db = sqlite3.connect(path)
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "settings" not in tables:
            return None
        row = db.execute("SELECT value FROM settings WHERE key = 'last_build'").fetchone()
        last = row[0] if row else None
        if last == build:
            return None
        made = path.with_name(f"{path.name}.before-{re.sub(r'[^A-Za-z0-9._-]', '_', build)}")
        dst = sqlite3.connect(made)
        try:
            db.backup(dst)
        finally:
            dst.close()
        if os.name == "posix":
            os.chmod(made, 0o600)  # holds the Twitch token, like drops.db
        db.execute("INSERT INTO settings VALUES ('last_build', ?) ON CONFLICT(key) DO UPDATE SET value = ?",
                   (build, build))
        db.commit()
    finally:
        db.close()
    log.info("Database copied to %s before running %s (was %s)", made.name, build, last or "an older build")
    copies = sorted(path.parent.glob(f"{path.name}.before-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in copies[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)
    return made


def safe_backup_on_upgrade(path: Path, build: str) -> Path | None:
    """backup_on_upgrade that never stops the miner from starting (a full disk, permissions)."""
    try:
        return backup_on_upgrade(path, build)
    except Exception as exc:  # noqa: BLE001 - a missing copy must not mean no mining
        log.warning("Couldn't copy the database before this upgrade: %s: %s", type(exc).__name__, exc)
        return None


def miner_health(service, now: datetime) -> tuple[bool, str]:
    """(healthy, why). Mining crashed, or no tick for HEALTH_STALL, is unhealthy; signed out, paused or idle
    are not faults."""
    from .runner import HEALTH_STALL
    if crashed := getattr(service, "crashed", None):
        return False, f"mining loop crashed ({crashed})"
    runner = service.runner
    last = getattr(runner, "last_tick", None) if runner else None
    if last is not None and now - last > HEALTH_STALL:
        return False, f"no tick since {last.isoformat()}"
    return True, "mining" if runner else "not mining"


class Watchdog:
    """Exits the process after two unhealthy checks in a row, so Docker's restart policy starts a fresh
    miner (Unraid runs no autoheal container). Needs a restart policy on the container (the Unraid template
    sets --restart unless-stopped). Only on when DROPWATCH_EXIT_WHEN_STUCK=1 (the image sets it); on a PC
    there is nothing to restart it."""

    STRIKES = 2

    def __init__(self, health: Callable[[], tuple[bool, str]], exit: Callable[[int], None] = os._exit):
        self._health, self._exit, self._strikes = health, exit, 0

    def check(self) -> None:
        ok, why = self._health()
        self._strikes = 0 if ok else self._strikes + 1
        if self._strikes >= self.STRIKES:
            log.error("Miner unhealthy twice in a row (%s); exiting so Docker restarts it", why)
            self._exit(3)
