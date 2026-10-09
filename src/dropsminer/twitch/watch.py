"""Minute-watched heartbeat (reference channel.py send_watch / spade_payload, MIT)."""
from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime

from ..models import LiveChannel
from .constants import ANDROID_APP
from .session import TwitchSession, base_headers
from .transport import HttpTransport

log = logging.getLogger("dropsminer.watch")
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
            "client_time": now.isoformat(),
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


class Watcher:
    def __init__(self, transport: HttpTransport, session: Callable[[], TwitchSession]):
        self._t, self._session = transport, session
        self._spade: dict[str, str] = {}

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

    async def send(self, channel: LiveChannel, now: datetime) -> bool:
        url = await self._spade_url(channel.login)
        if url is None:
            log.warning("No spade URL for %s", channel.login)
            return False
        s = self._session()
        r = await self._t.request("POST", url, headers=base_headers(s, ANDROID_APP),
                                  data=watch_payload(channel, s.user_id, now))
        if r.status != 204:
            log.info("Heartbeat to %s returned HTTP %s", channel.login, r.status)
        return r.status == 204
