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


def backup_on_upgrade(store, build: str) -> Path | None:
    """When the running build differs from the last one that started on this database, copy the database
    first (drops.db.before-<build>) so an upgrade can be rolled back. Returns the copy, or None."""
    last = store.get_setting("last_build")
    if last == build:
        return None
    made = None
    if last is not None:
        src: Path = store.path
        made = src.with_name(f"{src.name}.before-{re.sub(r'[^A-Za-z0-9._-]', '_', build)}")
        dst = sqlite3.connect(made)
        try:
            store._db.backup(dst)  # consistent even while the store is open
        finally:
            dst.close()
        log.info("Database copied to %s before running %s (was %s)", made.name, build, last)
        copies = sorted(src.parent.glob(f"{src.name}.before-*"), key=lambda p: p.stat().st_mtime,
                        reverse=True)
        for old in copies[BACKUP_KEEP:]:
            old.unlink(missing_ok=True)
    store.set_setting("last_build", build)
    return made


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
    miner (Unraid runs no autoheal container). Only on when DROPWATCH_EXIT_WHEN_STUCK=1 (the image sets it);
    on a PC there is nothing to restart it."""

    STRIKES = 2

    def __init__(self, health: Callable[[], tuple[bool, str]], exit: Callable[[int], None] = os._exit):
        self._health, self._exit, self._strikes = health, exit, 0

    def check(self) -> None:
        ok, why = self._health()
        self._strikes = 0 if ok else self._strikes + 1
        if self._strikes >= self.STRIKES:
            log.error("Miner unhealthy twice in a row (%s); exiting so Docker restarts it", why)
            self._exit(3)
