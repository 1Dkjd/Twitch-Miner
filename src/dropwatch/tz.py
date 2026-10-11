"""Time zones by IANA name, from the tzdata package where the OS has no database (Windows, slim images)."""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def zone_or_none(name: str) -> ZoneInfo | None:
    if not name or len(name) > 64 or ".." in name or name.startswith(("/", "\\")):
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):  # OSError: a region such as "Europe" is a folder
        return None
