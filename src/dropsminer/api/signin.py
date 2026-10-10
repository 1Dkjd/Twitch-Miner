"""Twitch sign-in as a background job: get a code, wait for the owner to authorize it (spec §4, §8)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..twitch.auth_browser import SignInError

log = logging.getLogger("dropsminer.signin")


class SignInManager:
    """provider_factory() -> (provider, close). provider.start() -> DeviceCode;
    provider.wait(code, cancel) -> TwitchSession."""

    def __init__(self, store, bus, provider_factory, on_signed_in: Callable[[], Awaitable[None]]):
        self._store, self._bus, self._factory, self._on = store, bus, provider_factory, on_signed_in
        self._state: dict = {"status": "idle", "message": ""}
        self._cancel: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._starting = False

    def status(self) -> dict:
        return dict(self._state)

    def _set(self, status: str, message: str = "", code=None) -> None:
        self._state = {"status": status, "message": message}
        if code is not None:
            self._state.update(code=code.user_code, verification_uri=code.verification_uri,
                               expires_at=code.expires_at)
        self._bus.publish("signin", {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                                     for k, v in self._state.items()})

    async def start(self) -> dict | None:
        """The waiting status with the code, or None when a sign-in is already in progress."""
        if self._starting or (self._task is not None and not self._task.done()):
            return None
        self._starting = True
        try:
            provider, close = self._factory()
            try:
                code = await provider.start()
            except Exception as exc:  # noqa: BLE001  never surface raw payloads
                await close()
                self._set("failed", str(exc) if isinstance(exc, SignInError)
                          else f"Sign-in could not start ({type(exc).__name__}).")
                return self.status()
            self._cancel = asyncio.Event()
            self._set("waiting", code=code)
            self._task = asyncio.create_task(self._run(provider, close, code, self._cancel))
            return self.status()
        finally:
            self._starting = False

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    async def _run(self, provider, close, code, cancel: asyncio.Event) -> None:
        try:
            try:
                session = await provider.wait(code, cancel)
            finally:
                await close()
            self._store.set_session(session)
            await self._on()
            self._set("done", f"Signed in as {session.login}.")
        except SignInError as exc:
            self._set("expired" if "expired" in str(exc) else "failed", str(exc))
        except Exception as exc:  # noqa: BLE001  the status must never stay "waiting"
            log.exception("Sign-in crashed")
            self._set("failed", f"Sign-in could not finish ({type(exc).__name__}).")
