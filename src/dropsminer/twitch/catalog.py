"""The public drops catalogue: the campaign list Twitch hides from the TV login (spec §4, 2026-10-10).

The catalogue republishes Twitch's own campaign records (same ids and fields), refreshed every 60 s by
an anonymous third party. It is only ever sent a plain GET: no Twitch headers, cookies or account data
(the caller gives it its own transport). Twitch's Inventory is merged over it by the client, so the
account's own state always wins. When the catalogue is down, the last good copy (memory, then
catalog.json) keeps already-known campaigns visible and the status says since when.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .parse import ts

log = logging.getLogger("dropsminer.catalog")
CATALOG_URL = "https://twitch-drops-api.sunkwi.com/v2/drops"
FETCH_EVERY = timedelta(hours=1)
RETRY_AFTER = timedelta(minutes=5)
STALE_AFTER = timedelta(hours=6)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; drops-miner)", "Accept": "application/json"}


def flatten(body: dict) -> tuple[dict[str, dict], datetime | None]:
    """Campaign id -> Twitch-shaped raw record. Malformed records are skipped one by one."""
    out: dict[str, dict] = {}
    for game in body["data"]:
        for r in game.get("rewards") or []:
            try:
                raw = dict(r)
                g = dict(raw["game"])
                if not g.get("boxArtURL") and game.get("gameBoxArtURL"):
                    g["boxArtURL"] = game["gameBoxArtURL"]
                raw["game"] = g
                ts(raw["endAt"])
                out[raw["id"]] = raw
            except (KeyError, TypeError, ValueError):
                continue
    updated = body.get("lastUpdatedAt")
    return out, (ts(updated) if updated else None)


class Catalog:
    def __init__(self, transport, cache_path: Path, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._t, self._cache, self._clock = transport, cache_path, clock
        self._data: dict[str, dict] | None = None
        self._updated: datetime | None = None
        self._next_fetch: datetime | None = None
        self._status: tuple[str, datetime | None] = ("ok", None)

    @property
    def status(self) -> tuple[str, datetime | None]:
        return self._status

    async def campaigns(self, *, force: bool = False) -> dict[str, dict]:
        now = self._clock()
        if force or self._next_fetch is None or now >= self._next_fetch:
            await self._fetch(now)
        return {cid: raw for cid, raw in (self._data or {}).items()
                if raw.get("status") == "ACTIVE" and ts(raw["endAt"]) > now}

    async def _fetch(self, now: datetime) -> None:
        try:
            r = await self._t.request("GET", CATALOG_URL, headers=dict(HEADERS))
            if r.status != 200:
                raise ValueError(f"HTTP {r.status}")
            body = json.loads(r.text)
            data, updated = flatten(body)
        except Exception as exc:  # noqa: BLE001  a broken catalogue must never stop mining
            log.warning("Campaign catalogue unavailable: %s: %s", type(exc).__name__, exc)
            self._next_fetch = now + RETRY_AFTER
            if self._status[0] != "unreachable":
                self._status = ("unreachable", now)
            if self._data is None:
                self._data, self._updated = self._load()
            return
        self._data, self._updated, self._next_fetch = data, updated, now + FETCH_EVERY
        self._save(body)
        if updated is not None and now - updated > STALE_AFTER:
            self._status = ("stale", updated)
        else:
            self._status = ("ok", None)
        log.info("Campaign catalogue: %d campaigns", len(data))

    def _load(self) -> tuple[dict[str, dict], datetime | None]:
        try:
            return flatten(json.loads(self._cache.read_bytes()))
        except (OSError, ValueError, KeyError, TypeError):
            return {}, None

    def _save(self, body: dict) -> None:
        try:
            self._cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache.with_suffix(".tmp")
            tmp.write_bytes(json.dumps(body).encode("utf-8"))
            tmp.replace(self._cache)
        except OSError as exc:
            log.warning("Could not cache the catalogue: %s", exc)
