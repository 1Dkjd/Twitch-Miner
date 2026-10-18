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
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .parse import ts

log = logging.getLogger("dropwatch.catalog")
CATALOG_URL = "https://twitch-drops-api.sunkwi.com/v2/drops"
MAX_BODY = 25 * 1024 * 1024  # the real catalogue is well under 1 MB; anything this big isn't it
# a fetch that suddenly lists far fewer campaigns than the last good one is more likely a broken or
# tampered catalogue than Twitch ending most campaigns at once: keep the last good copy instead
COLLAPSE_MIN, COLLAPSE_RATIO = 20, 0.2
IMAGE_HOST = "https://static-cdn.jtvnw.net/"  # the only image host taken from a third party
LISTED = ("ACTIVE", "UPCOMING")
FETCH_EVERY = timedelta(hours=1)
RETRY_AFTER = timedelta(minutes=5)
STALE_AFTER = timedelta(hours=6)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dropwatch)", "Accept": "application/json"}


def catalog_url() -> str | None:
    """DROPWATCH_CATALOG_URL: another catalogue with the same format (a mirror you run), or "off".
    Off means campaigns come only from Twitch, which shows the TV login just the ones in progress."""
    v = os.environ.get("DROPWATCH_CATALOG_URL", "").strip()
    if v.lower() in ("off", "none", "false", "0", "disabled"):
        return None
    return v or CATALOG_URL


def _image(url) -> str:
    return url if isinstance(url, str) and url.startswith(IMAGE_HOST) else ""


def _sanitize(raw: dict) -> dict:
    """A third party's record, cut down to what it can be trusted for: images only from Twitch's CDN
    (the page loads them, so another host would see every visit) and account links only over https."""
    raw["game"]["boxArtURL"] = _image(raw["game"].get("boxArtURL"))
    link = raw.get("accountLinkURL")
    raw["accountLinkURL"] = link if isinstance(link, str) and link.startswith("https://") else ""
    for d in raw.get("timeBasedDrops") or []:
        for b in (d.get("benefitEdges") or []) if isinstance(d, dict) else []:
            ben = b.get("benefit") if isinstance(b, dict) else None
            if isinstance(ben, dict):
                ben["imageAssetURL"] = _image(ben.get("imageAssetURL"))
    raw.pop("self", None)  # account state only ever comes from Twitch
    return raw


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
                if not isinstance(raw["id"], str) or not raw["id"]:
                    continue
                out[raw["id"]] = _sanitize(raw)
            except (KeyError, TypeError, ValueError, AttributeError):  # e.g. endAt null
                continue
    updated = body.get("lastUpdatedAt")
    return out, (ts(updated) if updated else None)


class Catalog:
    def __init__(self, transport, cache_path: Path, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC), url: str = CATALOG_URL):
        self._t, self._cache, self._clock, self._url = transport, cache_path, clock, url
        self._data: dict[str, dict] | None = None
        self._updated: datetime | None = None
        self._next_fetch: datetime | None = None
        self._status: tuple[str, datetime | None] = ("ok", None)

    @property
    def used(self) -> bool:
        """False until the first fetch: an Android session lists campaigns itself and never needs it."""
        return self._next_fetch is not None

    @property
    def status(self) -> tuple[str, datetime | None]:
        return self._status

    async def campaigns(self, *, force: bool = False) -> dict[str, dict]:
        now = self._clock()
        if force or self._next_fetch is None or now >= self._next_fetch:
            await self._fetch(now)
        # UPCOMING too: the page lists them under Coming up; the planner only mines started ones
        return {cid: raw for cid, raw in (self._data or {}).items()
                if raw.get("status") in LISTED and ts(raw["endAt"]) > now}

    async def _fetch(self, now: datetime) -> None:
        try:
            r = await self._t.request("GET", self._url, headers=dict(HEADERS))
            if r.status != 200:
                raise ValueError(f"HTTP {r.status}")
            if len(r.text) > MAX_BODY:
                raise ValueError(f"response too large ({len(r.text)} bytes)")
            body = json.loads(r.text)
            data, updated = flatten(body)
            before = len(self._data or {})
            if before >= COLLAPSE_MIN and len(data) < before * COLLAPSE_RATIO:
                raise ValueError(f"listed {len(data)} campaigns after {before}; keeping the last good list")
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
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {}, None

    def _save(self, body: dict) -> None:
        try:
            self._cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache.with_suffix(".tmp")
            tmp.write_bytes(json.dumps(body).encode("utf-8"))
            tmp.replace(self._cache)
        except OSError as exc:
            log.warning("Could not cache the catalogue: %s", exc)
