"""A short-lived screen for the in-page Twitch sign-in (2026-10-18).

Twitch only issues an Android-app token (the one that lists campaigns and account links) through its real
login page, which needs a real browser. The image ships Chromium; this starts a virtual screen (Xvfb) for it
and a VNC server (x11vnc) that only listens inside the container. The page sees that screen through
Dropwatch's own WebSocket (api/browser_signin.py), behind the page password. Everything stops after the
sign-in, so nothing runs the rest of the time.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import os
import shutil
from dataclasses import dataclass

log = logging.getLogger("dropwatch.desktop")
WIDTH, HEIGHT = 1280, 860
VNC_PORT = 5925
BROWSERS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")


def browser_path() -> str | None:
    if env := os.environ.get("DROPWATCH_BROWSER"):
        return env if os.path.exists(env) else None
    return next((p for name in BROWSERS if (p := shutil.which(name))), None)


def missing() -> list[str]:
    """What this install lacks for the in-page sign-in (empty: it can run)."""
    out = [name for name in ("Xvfb", "x11vnc") if shutil.which(name) is None]
    if browser_path() is None:
        out.append("Chromium")
    if importlib.util.find_spec("zendriver") is None:
        out.append("zendriver")
    return out


@dataclass
class Desktop:
    display: str
    port: int
    procs: list[asyncio.subprocess.Process]

    async def stop(self) -> None:
        for p in reversed(self.procs):
            with contextlib.suppress(ProcessLookupError):
                p.terminate()
        for p in self.procs:
            try:
                await asyncio.wait_for(p.wait(), 5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    p.kill()


async def _port_open(port: int, wait_s: float) -> bool:
    loop = asyncio.get_running_loop()
    end = loop.time() + wait_s
    while loop.time() < end:
        try:
            _, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            return True
        except OSError:
            await asyncio.sleep(0.2)
    return False


async def _spawn(*cmd: str) -> asyncio.subprocess.Process:
    env = {**os.environ, "HOME": os.environ.get("HOME") or "/tmp"}
    return await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.DEVNULL, env=env)


async def start_desktop(port: int = VNC_PORT) -> Desktop:
    """Xvfb on the first free display from :90, and x11vnc on localhost only, without a password: the only
    way in is Dropwatch's WebSocket, which checks the page login."""
    procs: list[asyncio.subprocess.Process] = []
    try:
        def taken() -> set[int]:
            return {n for n in range(90, 110) if os.path.exists(f"/tmp/.X{n}-lock")}
        locks = await asyncio.to_thread(taken)
        display = None
        for n in (n for n in range(90, 110) if n not in locks):
            x = await _spawn("Xvfb", f":{n}", "-screen", "0", f"{WIDTH}x{HEIGHT}x24", "-nolisten", "tcp")
            await asyncio.sleep(0.6)
            if x.returncode is None:
                procs.append(x)
                display = f":{n}"
                break
        if display is None:
            raise RuntimeError("no free display for the sign-in browser")
        procs.append(await _spawn("x11vnc", "-display", display, "-localhost", "-rfbport", str(port), "-nopw",
                                  "-forever", "-shared", "-noxdamage", "-quiet", "-noipv6"))
        if not await _port_open(port, 10):
            raise RuntimeError("the sign-in screen did not start")
        log.info("Sign-in screen on %s (VNC on localhost:%d)", display, port)
        return Desktop(display, port, procs)
    except BaseException:
        await Desktop("", port, procs).stop()
        raise
