"""Browser sign-in that yields an Android-app token (spec §4).

Ported from reference/fireph-webui/webui/browser_login.py (MIT). The owner signs in on the real
Twitch page. The protected_login POST is rewritten to carry delegate_client_id=ANDROID_APP, so
Twitch issues an Android token, which can list campaigns (the TV client cannot).
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import secrets
import shutil
from collections.abc import Callable
from urllib.parse import urlsplit

from .constants import ANDROID_APP, WEB
from .session import TwitchSession, base_headers
from .transport import HttpTransport

LOGIN_URL = "https://www.twitch.tv/login"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
WINDOWS_BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


class SignInError(Exception):
    pass


def delegated_payload(url: str, method: str, body: str | None) -> str | None:
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or target.netloc != "passport.twitch.tv"
        or target.path not in ("/protected_login", "/protected_login/shim")
        or method != "POST"
    ):
        return None
    try:
        payload = json.loads(body or "")
    except (ValueError, TypeError):
        raise SignInError("Twitch's login request was not JSON; sign-in stopped.") from None
    if not isinstance(payload, dict) or "username" not in payload or "password" not in payload:
        raise SignInError("Twitch's login request format changed; sign-in stopped.")
    payload["client_id"] = WEB.client_id
    payload["delegate_client_id"] = ANDROID_APP.client_id
    return json.dumps(payload, separators=(",", ":"))


async def validate_token(transport: HttpTransport, token: str, expect: str = ANDROID_APP.client_id,
                         expect_name: str = "Android") -> tuple[int, str]:
    r = await transport.request("GET", VALIDATE_URL, headers={"Authorization": f"OAuth {token}"})
    if r.status != 200:
        raise SignInError(f"Twitch rejected token validation (HTTP {r.status}).")
    data = r.json()
    cid = data.get("client_id")
    if cid != expect:
        kind = "WEB" if cid == WEB.client_id else "a different client"
        raise SignInError(f"Twitch issued a token for {kind}, not {expect_name}. It was not saved.")
    if not str(data.get("user_id", "")).isdigit():
        raise SignInError("Twitch returned a token without a valid user ID.")
    return int(data["user_id"]), str(data.get("login", ""))


async def device_id(transport: HttpTransport) -> str:
    """The reference reads twitch.tv's unique_id cookie. aiohttp keeps it in the jar; fall back to random."""
    await transport.request("GET", ANDROID_APP.client_url, headers=base_headers(None, ANDROID_APP))
    jar = getattr(getattr(transport, "session", None), "cookie_jar", None)
    if jar is not None:
        for cookie in jar:
            if cookie.key == "unique_id":
                return cookie.value
    return secrets.token_hex(16)


def _find_browser(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if env := os.environ.get("DROPSMINER_BROWSER"):
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    return next((p for p in WINDOWS_BROWSERS if os.path.exists(p)), None)


class BrowserSignIn:
    def __init__(
        self,
        transport: HttpTransport,
        *,
        display: str | None = None,
        executable: str | None = None,
        report: Callable[[str], None] = print,
    ):
        self._t, self._display, self._exe, self._report = transport, display, executable, report

    async def sign_in(self, cancel: asyncio.Event) -> TwitchSession:
        token = await self._browser_token(cancel)
        user_id, login = await validate_token(self._t, token)
        dev = await device_id(self._t)
        self._report(f"Signed in as {login}.")
        return TwitchSession(token, user_id, login, dev, ANDROID_APP.client_id, secrets.token_hex(8))

    async def _browser_token(self, cancel: asyncio.Event) -> str:
        try:
            import zendriver as zd
        except ImportError:
            raise SignInError("zendriver is not installed.") from None
        logging.getLogger("zendriver").setLevel(logging.WARNING)  # CDP logs contain credentials
        browser = None
        tasks: list[asyncio.Task] = []
        outcome: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        intercepted: set[str] = set()
        report = self._report

        def fail(message: str) -> None:
            if not outcome.done():
                outcome.set_exception(SignInError(message))

        async def login_in_browser() -> str:
            nonlocal browser
            report("Starting a browser for Twitch sign-in...")
            args = ["--window-size=1280,900"]
            if self._display:
                args += [f"--display={self._display}", "--ozone-platform=x11"]
            config = zd.Config(
                browser_executable_path=_find_browser(self._exe),
                headless=False,
                browser_connection_timeout=0.25,
                browser_connection_max_tries=60,
                browser_args=args,
            )
            browser = zd.Browser(config)
            await browser.start()
            tab = await browser.get("about:blank")

            async def paused(event) -> None:
                # Port of reference browser_login.py lines 163-240, logic unchanged:
                # rewrite the login POST, capture access_token from the intercepted response.
                request_id = event.request_id
                try:
                    if event.response_status_code is None and event.response_error_reason is None:
                        body = delegated_payload(
                            event.request.url, event.request.method, event.request.post_data
                        )
                        if body is None:
                            await tab.send(zd.cdp.fetch.continue_request(request_id))
                            return
                        intercepted.add(str(request_id))
                        await tab.send(zd.cdp.fetch.continue_request(
                            request_id,
                            post_data=base64.b64encode(body.encode()).decode(),
                            intercept_response=True,
                        ))
                        return
                    candidate = None
                    if str(request_id) in intercepted:
                        intercepted.discard(str(request_id))
                        if event.response_error_reason is not None:
                            report("The login request failed to reach Twitch. Retry in the browser.")
                        elif event.response_status_code not in (301, 302, 303, 307, 308):
                            body, encoded = await tab.send(zd.cdp.fetch.get_response_body(request_id))
                            if encoded:
                                body = base64.b64decode(body).decode()
                            try:
                                result = json.loads(body)
                            except ValueError:
                                result = {}
                            if isinstance(result, dict):
                                tok = result.get("access_token")
                                if event.response_status_code == 200 and isinstance(tok, str) and tok:
                                    candidate = tok
                                else:
                                    code = result.get("error_code")
                                    suffix = f", Twitch error {code}" if isinstance(code, int) else ""
                                    report(f"Login response: HTTP {event.response_status_code}{suffix}. "
                                           "Continue in the browser.")
                    await tab.send(zd.cdp.fetch.continue_request(request_id))
                    if candidate and not outcome.done():
                        outcome.set_result(candidate)
                except SignInError as exc:
                    with contextlib.suppress(Exception):
                        await tab.send(zd.cdp.fetch.fail_request(
                            request_id, zd.cdp.network.ErrorReason.ABORTED))
                    fail(str(exc))
                except Exception as exc:  # noqa: BLE001  CDP errors may contain credentials
                    with contextlib.suppress(Exception):
                        await tab.send(zd.cdp.fetch.continue_request(request_id))
                    fail(f"Could not inspect the login response ({type(exc).__name__}).")

            tab.add_handler(zd.cdp.fetch.RequestPaused, paused)
            await tab.send(zd.cdp.fetch.enable(patterns=[
                zd.cdp.fetch.RequestPattern(url_pattern="https://passport.twitch.tv/protected_login*"),
            ]))
            await tab.get(LOGIN_URL)
            report("Sign in to Twitch in the browser window (password and verification code).")
            while not outcome.done():
                if browser.stopped or tab.closed:
                    raise SignInError("The sign-in browser was closed.")
                await asyncio.wait({outcome}, timeout=0.5)
            return outcome.result()

        try:
            login_task = asyncio.create_task(login_in_browser())
            cancel_task = asyncio.create_task(cancel.wait())
            tasks = [login_task, cancel_task]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done:
                raise SignInError("Sign-in cancelled.")
            return await login_task
        except SignInError:
            raise
        except Exception as exc:  # noqa: BLE001  never surface CDP payloads
            raise SignInError(f"Browser sign-in could not run ({type(exc).__name__}).") from None
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if not outcome.done():
                outcome.cancel()
            elif not outcome.cancelled():
                outcome.exception()
            if browser is not None:
                # Verbatim cleanup from reference lines 298-325 (zendriver 0.17 leaks pipes/listeners)
                process = getattr(browser, "_process", None)
                connections = [getattr(browser, "connection", None), *getattr(browser, "targets", [])]
                listeners = [
                    c.listener.task for c in connections
                    if c is not None and c.listener is not None and c.listener.task is not None
                ]
                try:
                    await browser.stop()
                except Exception as exc:  # noqa: BLE001
                    report(f"Browser cleanup failed ({type(exc).__name__}).")
                finally:
                    for listener in listeners:
                        if not listener.done():
                            listener.cancel()
                    await asyncio.gather(*listeners, return_exceptions=True)
                    if process is not None:
                        for stream in (process.stdin, process.stdout, process.stderr):
                            if stream is not None:
                                stream.close()
