"""Twitch TV code sign-in (spec §4, 2026-10-10).

The owner gets an 8-letter code, enters it at twitch.tv/activate on any device and clicks Authorize.
It uses Twitch's own TV client (SMARTBOX): its device-code flow still works and its token earns watch
minutes, though Twitch hides the campaign list from it (twitch/catalog.py fills that gap).

Polling has no timeout of its own: only Twitch's expiry (expires_in) or Cancel ends it.
"""
from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .auth_browser import SignInError, device_id, validate_token
from .constants import SMARTBOX
from .session import TwitchSession
from .transport import HttpTransport

DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"


@dataclass(frozen=True)
class DeviceCode:
    user_code: str
    verification_uri: str
    expires_at: datetime
    interval: float
    device_code: str


async def _pause(cancel: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(cancel.wait(), seconds)


class DeviceCodeSignIn:
    def __init__(self, transport: HttpTransport, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 pause: Callable[[asyncio.Event, float], Awaitable[None]] = _pause):
        self._t, self._clock, self._pause = transport, clock, pause
        self._device_id: str | None = None

    def _headers(self) -> dict[str, str]:
        h = {"Client-Id": SMARTBOX.client_id, "User-Agent": SMARTBOX.user_agent, "Accept": "application/json",
             "Origin": SMARTBOX.client_url, "Referer": SMARTBOX.client_url}
        if self._device_id:
            h["X-Device-Id"] = self._device_id
        return h

    async def start(self) -> DeviceCode:
        self._device_id = await device_id(self._t)
        r = await self._t.request("POST", DEVICE_URL, headers=self._headers(),
                                  data={"client_id": SMARTBOX.client_id, "scopes": ""})
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status != 200 or "device_code" not in body:
            why = body.get("message") or f"HTTP {r.status}"
            raise SignInError(f"Twitch wouldn't start a sign-in ({why}).")
        return DeviceCode(body["user_code"], body["verification_uri"],
                          self._clock() + timedelta(seconds=int(body.get("expires_in", 1800))),
                          float(body.get("interval", 5)), body["device_code"])

    async def wait(self, code: DeviceCode, cancel: asyncio.Event) -> TwitchSession:
        interval = code.interval
        token = None
        while token is None:
            if self._clock() >= code.expires_at:
                raise SignInError("That code expired. Get a new one.")
            await self._pause(cancel, interval)
            if cancel.is_set():
                raise SignInError("Sign-in cancelled.")
            r = await self._t.request("POST", TOKEN_URL, headers=self._headers(), data={
                "client_id": SMARTBOX.client_id, "device_code": code.device_code, "grant_type": GRANT})
            try:
                body = r.json()
            except ValueError:
                body = {}
            message = str(body.get("message") or "")
            if body.get("access_token"):
                token = body["access_token"]
            elif message == "authorization_pending":
                continue
            elif message == "slow_down":
                interval += 5
            elif "invalid device code" in message or "expired" in message:
                raise SignInError("That code expired. Get a new one.")
            else:
                raise SignInError(f"Twitch refused the sign-in ({message or f'HTTP {r.status}'}).")
        user_id, login = await validate_token(self._t, token, SMARTBOX.client_id, "the TV app")
        return TwitchSession(token, user_id, login, self._device_id or secrets.token_hex(16),
                             SMARTBOX.client_id, secrets.token_hex(8))
