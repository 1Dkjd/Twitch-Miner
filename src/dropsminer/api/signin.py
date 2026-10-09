"""Browser sign-in as a background job the page can start, watch and cancel."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..twitch.auth_browser import SignInError

log = logging.getLogger("dropsminer.signin")


class SignInManager:
    def __init__(self, store, bus, provider_factory, on_signed_in: Callable[[], Awaitable[None]]):
        self._store, self._bus, self._factory, self._on = store, bus, provider_factory, on_signed_in
        self._state = {"status": "idle", "message": ""}
        self._cancel: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    def status(self) -> dict:
        return dict(self._state)

    def _set(self, status: str, message: str = "") -> None:
        self._state = {"status": status, "message": message}
        self._bus.publish("signin", dict(self._state))

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._cancel = asyncio.Event()
        self._set("running")
        self._task = asyncio.create_task(self._run(self._cancel))
        return True

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    async def _run(self, cancel: asyncio.Event) -> None:
        provider, close = self._factory()
        try:
            session = await provider.sign_in(cancel)
        except SignInError as exc:
            self._set("failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001  never surface browser payloads
            log.exception("Sign-in crashed")
            self._set("failed", f"Sign-in could not run ({type(exc).__name__}).")
            return
        finally:
            await close()
        self._store.set_session(session)
        await self._on()
        self._set("done", f"Signed in as {session.login}.")
