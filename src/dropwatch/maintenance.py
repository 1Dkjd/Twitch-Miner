"""Housekeeping for long-running installs (Docker, 2026-10-11): a database copy before an upgrade."""
from __future__ import annotations

import logging
import re
import sqlite3
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
