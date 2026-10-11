"""What is running: the package version and, when known, the branch and commit (Settings › About)."""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    VERSION = version("dropwatch")
except PackageNotFoundError:  # running from a source tree that was never installed
    VERSION = "0.0.0"


@lru_cache(maxsize=1)
def build_info() -> str | None:
    """"branch@sha". A Docker image has no .git, so its build sets DROPWATCH_COMMIT; a checkout asks git."""
    if env := os.environ.get("DROPWATCH_COMMIT", "").strip():
        return env
    repo = Path(__file__).resolve().parents[2]
    if not (repo / ".git").exists():
        return None
    try:
        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                                  timeout=5, check=True).stdout.strip()
        return f"{git('rev-parse', '--abbrev-ref', 'HEAD')}@{git('rev-parse', '--short', 'HEAD')}"
    except (OSError, subprocess.SubprocessError):
        return None


def server_tz() -> str:
    """The zone the server's clock is in: TZ when set (Docker), else the abbreviation and offset."""
    if tz := os.environ.get("TZ", "").strip():
        return tz
    from datetime import datetime
    local = datetime.now().astimezone()
    off = local.utcoffset()
    mins = int(off.total_seconds() // 60) if off else 0
    sign = "+" if mins >= 0 else "-"
    return f"{local.tzname()} (UTC{sign}{abs(mins) // 60:02d}:{abs(mins) % 60:02d})"
