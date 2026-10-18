"""Sign in on Twitch's real login page, inside Dropwatch's page (2026-10-18).

Twitch shows the TV code sign-in no campaign list and no account links, and stopped issuing Android-app tokens
through its code sign-in (DevilXD/TwitchDropsMiner#1165): it now only does that on its real login page, in a
real browser. So for one sign-in the container starts Chromium on a virtual screen (desktop.py) and the page
shows that screen live. The owner signs in as usual; BrowserSignIn asks Twitch for an Android token, which is
checked and saved, and mining restarts on it. The browser and screen stop as soon as it's over.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable

from ..desktop import HEIGHT, WIDTH, Desktop, browser_path, missing, start_desktop
from ..twitch.auth_browser import BrowserSignIn, SignInError

log = logging.getLogger("dropwatch.browser_signin")
TIMEOUT_S = 15 * 60  # a sign-in left open stops by itself


class BrowserSignInManager:
    """status() -> {status, message, available}; status: idle | starting | open | done | failed."""

    def __init__(self, store, bus, transport_factory, on_signed_in: Callable[[], Awaitable[None]],
                 start_screen=start_desktop, sign_in_factory=None):
        self._store, self._bus, self._transport, self._on = store, bus, transport_factory, on_signed_in
        self._start_screen = start_screen
        self._make = sign_in_factory or self._default_sign_in
        self._state = {"status": "idle", "message": ""}
        self._task: asyncio.Task | None = None
        self._cancel: asyncio.Event | None = None
        self.desktop: Desktop | None = None

    @staticmethod
    def _default_sign_in(transport, display: str, report: Callable[[str], None]):
        return BrowserSignIn(transport, display=display, executable=browser_path(), report=report,
                             sandbox=False, window=(WIDTH, HEIGHT), kiosk=True)

    def available(self) -> list[str]:
        return missing()

    def status(self) -> dict:
        return {**self._state, "available": not self.available()}

    def _set(self, status: str, message: str = "") -> None:
        self._state = {"status": status, "message": message}
        self._bus.publish("browser_signin", self.status())

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> dict:
        if self.running:
            return self.status()
        if lack := self.available():
            self._set("failed", f"This install can't run the sign-in browser (missing: {', '.join(lack)}).")
            return self.status()
        self._cancel = asyncio.Event()
        self._set("starting", "Starting the sign-in browser…")
        self._task = asyncio.create_task(self._run(self._cancel))
        return self.status()

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    async def wait(self) -> None:
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self, cancel: asyncio.Event) -> None:
        transport, close = self._transport()
        try:
            # Chromium writes under $HOME; the container's user (99) may not own one
            home = os.environ.get("HOME", "")
            if not home or not await asyncio.to_thread(os.access, home, os.W_OK):
                os.environ["HOME"] = "/tmp"
            self.desktop = await self._start_screen()
            self._set("open", "Sign in to Twitch below (password, then the code if Twitch asks).")
            signin = self._make(transport, self.desktop.display, lambda m: log.info("Sign-in: %s", m))
            session = await asyncio.wait_for(signin.sign_in(cancel), TIMEOUT_S)
            self._store.set_session(session)
            self._set("done", f"Signed in as {session.login}. Dropwatch now sees every campaign.")
            await self._on()
        except SignInError as exc:
            if cancel.is_set():
                self._set("idle")
            else:
                self._set("failed", str(exc))
        except TimeoutError:
            self._set("failed", "The sign-in was left open too long and was closed. Start it again.")
        except Exception as exc:  # noqa: BLE001  the status must never stay "open"
            log.exception("Browser sign-in crashed")
            self._set("failed", f"The sign-in browser couldn't run ({type(exc).__name__}).")
        finally:
            if self.desktop is not None:
                await self.desktop.stop()
                self.desktop = None
            with contextlib.suppress(Exception):
                await close()
