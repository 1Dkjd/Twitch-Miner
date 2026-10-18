# /// script
# requires-python = ">=3.11"
# dependencies = ["zendriver==0.17.0", "aiohttp>=3.10"]
# ///
"""Dropwatch PC sign-in helper (2026-10-18). Not imported by Dropwatch: Settings hands it out as a download.

Twitch no longer issues Android-app tokens through its code sign-in (DevilXD/TwitchDropsMiner#1165), and its
login page needs a real browser. This opens Chrome (or Edge) on Twitch's own login page. You sign in there as
usual, password and verification code included. When Twitch answers the login, the helper asks for an
Android-app token instead of a website one (the same request rewrite as Dropwatch's `signin --browser`),
checks it with Twitch and writes it to dropwatch-session.json next to this file. Upload that file in
Dropwatch: Settings > Twitch > Import a PC sign-in.

Your password is typed into Twitch's page only. The helper reads Twitch's reply to the login, never your
password, and the file it writes holds only the token: keep it private and delete it after uploading.

Run with uv (it fetches Python and the two libraries itself):
    uv run dropwatch-signin.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
ANDROID_CLIENT_ID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"
LOGIN_URL = "https://www.twitch.tv/login"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
FORMAT = "dropwatch-session"


class HelperError(Exception):
    pass


def delegated_payload(url: str, method: str, body: str | None) -> str | None:
    """Twitch's login POST, asking for an Android token; None for every other request (sent unchanged)."""
    target = urlsplit(url)
    if (target.scheme != "https" or target.netloc != "passport.twitch.tv"
            or target.path not in ("/protected_login", "/protected_login/shim") or method != "POST"):
        return None
    try:
        payload = json.loads(body or "")
    except (ValueError, TypeError):
        raise HelperError("Twitch's login request was not JSON; stopped.") from None
    if not isinstance(payload, dict) or "username" not in payload or "password" not in payload:
        raise HelperError("Twitch's login request changed shape; stopped.")
    payload["client_id"] = WEB_CLIENT_ID
    payload["delegate_client_id"] = ANDROID_CLIENT_ID
    return json.dumps(payload, separators=(",", ":"))


def session_file(token: str, user_id: int, login: str, now: datetime | None = None) -> dict:
    return {"format": FORMAT, "version": 1, "login": login, "user_id": user_id,
            "client_id": ANDROID_CLIENT_ID, "access_token": token,
            "made_at": (now or datetime.now(UTC)).isoformat()}


def find_browser() -> str | None:
    if env := os.environ.get("DROPWATCH_BROWSER"):
        return env
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge"):
        if found := shutil.which(name):
            return found
    return None


async def validate(token: str) -> tuple[int, str]:
    import aiohttp
    auth = {"Authorization": f"OAuth {token}"}
    async with aiohttp.ClientSession() as s, s.get(VALIDATE_URL, headers=auth) as r:
        if r.status != 200:
            raise HelperError(f"Twitch rejected the new token (HTTP {r.status}).")
        data = await r.json()
    if data.get("client_id") != ANDROID_CLIENT_ID:
        raise HelperError("Twitch issued a website token, not an Android one. Nothing was saved.")
    return int(data["user_id"]), str(data.get("login", ""))


async def browser_token() -> str:
    import zendriver as zd
    logging.getLogger("zendriver").setLevel(logging.WARNING)  # its debug logs would carry the password
    exe = find_browser()
    if exe is None:
        raise HelperError("Couldn't find Chrome or Edge. Set DROPWATCH_BROWSER to the browser's .exe path.")
    browser = zd.Browser(zd.Config(browser_executable_path=exe, headless=False,
                                   browser_args=["--window-size=1100,900"],
                                   browser_connection_timeout=0.25, browser_connection_max_tries=60))
    await browser.start()
    outcome: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    intercepted: set[str] = set()
    try:
        tab = await browser.get("about:blank")

        async def paused(event) -> None:
            rid = event.request_id
            try:
                if event.response_status_code is None and event.response_error_reason is None:
                    body = delegated_payload(event.request.url, event.request.method, event.request.post_data)
                    if body is None:
                        await tab.send(zd.cdp.fetch.continue_request(rid))
                        return
                    intercepted.add(str(rid))
                    await tab.send(zd.cdp.fetch.continue_request(
                        rid, post_data=base64.b64encode(body.encode()).decode(), intercept_response=True))
                    return
                token = None
                if str(rid) in intercepted:
                    intercepted.discard(str(rid))
                    if event.response_status_code == 200:
                        body, encoded = await tab.send(zd.cdp.fetch.get_response_body(rid))
                        if encoded:
                            body = base64.b64decode(body).decode()
                        try:
                            result = json.loads(body)
                        except ValueError:
                            result = {}
                        tok = result.get("access_token") if isinstance(result, dict) else None
                        token = tok if isinstance(tok, str) and tok else None
                    if token is None:
                        print("Twitch wants more (a code, or a retry). Carry on in the browser window.")
                await tab.send(zd.cdp.fetch.continue_request(rid))
                if token and not outcome.done():
                    outcome.set_result(token)
            except HelperError as exc:
                if not outcome.done():
                    outcome.set_exception(exc)
            except Exception as exc:  # noqa: BLE001  never print request payloads: they hold the password
                if not outcome.done():
                    name = type(exc).__name__
                    outcome.set_exception(HelperError(f"Couldn't read Twitch's login reply ({name})."))

        tab.add_handler(zd.cdp.fetch.RequestPaused, paused)
        await tab.send(zd.cdp.fetch.enable(patterns=[
            zd.cdp.fetch.RequestPattern(url_pattern="https://passport.twitch.tv/protected_login*")]))
        await tab.get(LOGIN_URL)
        print("Sign in to Twitch in the browser window (password, then the verification code if asked).")
        while not outcome.done():
            if browser.stopped or tab.closed:
                raise HelperError("The browser window was closed before signing in.")
            await asyncio.wait({outcome}, timeout=0.5)
        return outcome.result()
    finally:
        try:
            await browser.stop()
        except Exception:  # noqa: BLE001
            pass


async def main() -> int:
    out = Path(__file__).with_name("dropwatch-session.json")
    try:
        token = await browser_token()
        user_id, login = await validate(token)
    except HelperError as exc:
        print(f"\nSign-in didn't finish: {exc}")
        return 1
    out.write_text(json.dumps(session_file(token, user_id, login), indent=2), encoding="utf-8")
    print(f"\nSigned in as {login}. Saved: {out}")
    print("Upload it in Dropwatch: Settings > Twitch > Import a PC sign-in.")
    print("Then delete the file: it holds your Twitch token.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
