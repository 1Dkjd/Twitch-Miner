"""Watching a stream: simulated HLS playback plus the minute-watched heartbeat.

Spade heartbeat from reference channel.py (fireph/DevilXD, MIT). Playback simulation from
JourneyDocker/TwitchDropsMiner 870c8b5 (MIT), see reference/journeydocker/channel.py.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin, urlsplit

import aiohttp

from ..models import LiveChannel
from .constants import ANDROID_APP, WATCH_INTERVAL, client_for
from .gql import GqlError, op
from .session import TwitchSession, base_headers
from .transport import HttpTransport

log = logging.getLogger("dropsminer.watch")
USHER = "https://usher.ttvnw.net/api/channel/hls"
# Per-step bounds, as in the JourneyDocker reference: a slow CDN edge must not stall playback.
POLL_TIMEOUT, MEDIA_TIMEOUT, HEAD_TIMEOUT, SPADE_TIMEOUT = 10.0, 5.0, 3.0, 5.0
NET_ERRORS = (OSError, TimeoutError, aiohttp.ClientError, UnicodeDecodeError, ValueError)
SETTINGS_RE = re.compile(r'src="(https://[\w.]+/config/settings\.[0-9a-f]{32}\.js)"', re.I)
SPADE_RE = re.compile(r'"spade_?url": ?"(https://[.\w\-/]+)"', re.I)


def find_spade_url(text: str) -> str | None:
    m = SPADE_RE.search(text)
    return m.group(1) if m else None


def find_settings_js(html: str) -> str | None:
    m = SETTINGS_RE.search(html)
    return m.group(1) if m else None


def watch_payload(channel: LiveChannel, user_id: int, now: datetime) -> dict:
    events = [{
        "event": "minute-watched",
        "properties": {
            "broadcast_id": channel.broadcast_id,
            "channel_id": str(channel.id),
            "channel": channel.login,
            # exact reference utils.isonow() format: milliseconds and a literal Z
            "client_time": now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "game": channel.game_name,
            "game_id": str(channel.game_id) if channel.game_id is not None else "",
            "hidden": False,
            "is_live": True,
            "live": True,
            "logged_in": True,
            "minutes_logged": 1,
            "muted": False,
            "user_id": user_id,
        },
    }]
    raw = json.dumps(events, separators=(",", ":")).encode("utf-8")
    return {"data": base64.b64encode(raw).decode("utf-8")}


def playlist_urls(playlist: str, base: str, *, master: bool = False) -> list[str]:
    """URIs that follow the expected HLS tag; [] for anything malformed.

    Port of JourneyDocker Stream.playlist_urls (870c8b5, MIT).
    """
    if not playlist.lstrip().startswith("#EXTM3U"):
        return []
    tag = "#EXT-X-STREAM-INF:" if master else "#EXTINF:"
    urls: list[str] = []
    pending = False
    for raw in playlist.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith(tag):
                pending = True
            continue
        if not pending:
            return []
        try:
            url = urljoin(base, line)
            parts = urlsplit(url)
            _ = parts.hostname
        except ValueError:  # e.g. an invalid IPv6 literal; never let a body reach a traceback
            return []
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username
                or (master and not parts.path.endswith(".m3u8"))):
            return []
        urls.append(url)
        pending = False
    return [] if pending else urls


class Watcher:
    """Simulated playback plus the minute-watched heartbeat.

    Since ~2026-10 Twitch credits drop minutes only while the account appears to play the
    stream (upstream DevilXD#1183). So, ported from JourneyDocker 870c8b5 (MIT), every call:
    - re-reads the lowest-quality media playlist;
    - sends a HEAD request for each segment not seen yet, so no video is downloaded;
    - while playback succeeds, posts the spade minute-watched event at most once per
      WATCH_INTERVAL.
    The runner calls send() every PLAY_INTERVAL seconds.
    """

    def __init__(self, transport: HttpTransport, session: Callable[[], TwitchSession], gql,
                 *, clock: Callable[[], float] = time.monotonic):
        self._t, self._session, self._gql, self._clock = transport, session, gql, clock
        self._spade: dict[str, str] = {}
        self._media: dict[str, str] = {}          # login -> media playlist URL
        self._broadcast: str | None = None
        self._segments: OrderedDict[str, None] = OrderedDict()
        self._last_spade: float | None = None

    async def _media_url(self, channel: LiveChannel) -> str | None:
        if channel.login in self._media:
            return self._media[channel.login]
        resp = await self._gql.run(op("PlaybackAccessToken", login=channel.login))
        data = resp.get("data") if isinstance(resp, dict) else None
        tok = data.get("streamPlaybackAccessToken") if isinstance(data, dict) else None
        if not isinstance(tok, dict) or not tok.get("value") or not tok.get("signature"):
            log.info("No playback token for %s", channel.login)
            return None
        master_url = f"{USHER}/{channel.login}.m3u8?" + urlencode(
            {"sig": tok["signature"], "token": tok["value"]})
        r = await self._t.request("GET", master_url, headers={"User-Agent": ANDROID_APP.user_agent})
        if r.status != 200:
            return None
        qualities = playlist_urls(r.text, master_url, master=True)
        if not qualities:
            return None
        self._media[channel.login] = qualities[-1]  # last is normally the lowest bandwidth
        return qualities[-1]

    async def _play(self, channel: LiveChannel) -> bool:
        if self._broadcast != channel.broadcast_id:
            self._broadcast = channel.broadcast_id
            self._segments.clear()
            self._last_spade = None
            self._media.pop(channel.login, None)  # a new broadcast needs a new playback token
        url = await self._media_url(channel)
        if url is None:
            return False
        headers = {"User-Agent": ANDROID_APP.user_agent}
        r = await asyncio.wait_for(self._t.request("GET", url, headers=headers), MEDIA_TIMEOUT)
        if r.status != 200:
            if r.status in (401, 403, 404):
                self._media.pop(channel.login, None)
            return False
        segments = playlist_urls(r.text, url)
        if not segments:
            return False
        ok = True
        for seg in segments:
            if seg in self._segments:
                continue
            try:
                h = await asyncio.wait_for(self._t.request("HEAD", seg, headers=headers), HEAD_TIMEOUT)
            except NET_ERRORS:
                ok = False  # one bad segment must not stop the others
                continue
            if h.status == 200:
                self._segments[seg] = None
                if len(self._segments) > 256:
                    self._segments.popitem(last=False)
            else:
                ok = False
                if h.status in (401, 403, 404):
                    self._media.pop(channel.login, None)
        return ok

    async def _spade_url(self, login: str) -> str | None:
        if login in self._spade:
            return self._spade[login]
        headers = base_headers(None, ANDROID_APP)
        page = await self._t.request("GET", f"https://www.twitch.tv/{login}", headers=headers)
        url = find_spade_url(page.text)
        if url is None and (js := find_settings_js(page.text)):
            url = find_spade_url((await self._t.request("GET", js, headers=headers)).text)
        if url:
            self._spade[login] = url
        return url

    def forget(self, login: str) -> None:
        self._spade.pop(login, None)
        self._media.pop(login, None)

    async def _post_spade(self, channel: LiveChannel, now: datetime) -> None:
        url = await self._spade_url(channel.login)
        if url is None:
            log.warning("No spade URL for %s", channel.login)
            return
        s = self._session()
        # the page and playlists stay Android (proven 2026-10-10); the event goes as the token's own client
        r = await self._t.request("POST", url, headers=base_headers(s, client_for(s.client_id)),
                                  data=watch_payload(channel, s.user_id, now))
        if r.status != 204:
            log.info("Heartbeat to %s returned HTTP %s", channel.login, r.status)

    async def send(self, channel: LiveChannel, now: datetime) -> bool:
        """True when playback succeeded. Network/GQL errors count as a failed send, never raise."""
        try:
            if not await asyncio.wait_for(self._play(channel), POLL_TIMEOUT):
                return False
        except (*NET_ERRORS, GqlError) as exc:
            log.warning("Watching %s failed: %s", channel.login, type(exc).__name__)
            return False
        t = self._clock()
        if self._last_spade is None or t - self._last_spade >= WATCH_INTERVAL:
            self._last_spade = t
            try:  # auxiliary: playback is what earns credit, so a spade failure never fails the send
                await asyncio.wait_for(self._post_spade(channel, now), SPADE_TIMEOUT)
            except (*NET_ERRORS, GqlError) as exc:
                log.info("Heartbeat to %s failed: %s", channel.login, type(exc).__name__)
        return True
