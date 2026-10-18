"""In-page Twitch sign-in (2026-10-18): Chromium on a virtual screen, shown in the page over a WebSocket."""
import asyncio
import os
import shutil
import socket
import threading

import pytest
from apihelpers import make_app
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dropwatch.api.browser_signin import BrowserSignInManager
from dropwatch.desktop import Desktop
from dropwatch.events import EventBus
from dropwatch.twitch.auth_browser import SignInError
from dropwatch.twitch.session import TwitchSession

S = TwitchSession("tok", 42, "dk", "d", "kd1unb4b3q4t58fwlpcbzcbnm76a8fp", "s")


class Store:
    def __init__(self):
        self.session = None

    def set_session(self, s):
        self.session = s


class FakeSignIn:
    def __init__(self, result):
        self.result = result

    async def sign_in(self, cancel):
        if self.result == "wait":
            await cancel.wait()
            raise SignInError("Sign-in cancelled.")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def manager(result, events=None):
    stopped, restarted = [], []

    async def screen():
        d = Desktop(":95", 5999, [])

        async def stop():
            stopped.append(True)
        d.stop = stop
        return d

    async def close():
        pass

    async def on():
        restarted.append(True)
    bus = EventBus()
    m = BrowserSignInManager(Store(), bus, lambda: (None, close), on, start_screen=screen,
                             sign_in_factory=lambda t, display, report: FakeSignIn(result))
    m.available = lambda: []
    return m, stopped, restarted


async def test_a_sign_in_saves_the_android_session_restarts_mining_and_closes_the_browser():
    m, stopped, restarted = manager(S)
    assert (await m.start())["status"] == "starting"
    await m.wait()
    assert m._store.session == S and restarted == [True] and stopped == [True]
    assert m.status()["status"] == "done" and "dk" in m.status()["message"]
    assert m.desktop is None


async def test_a_failed_sign_in_says_why_and_changes_nothing():
    m, stopped, restarted = manager(SignInError("Twitch issued a token for WEB, not Android."))
    await m.start()
    await m.wait()
    assert m.status()["status"] == "failed" and "WEB" in m.status()["message"]
    assert m._store.session is None and restarted == [] and stopped == [True]


async def test_cancel_closes_it_quietly():
    m, stopped, _ = manager("wait")
    await m.start()
    await asyncio.sleep(0.05)
    assert m.status()["status"] == "open" and m.desktop is not None
    m.cancel()
    await m.wait()
    assert m.status()["status"] == "idle" and stopped == [True]


async def test_without_chromium_it_says_what_is_missing():
    m, _, _ = manager(S)
    m.available = lambda: ["Chromium"]
    st = await m.start()
    assert st["status"] == "failed" and "Chromium" in st["message"] and st["available"] is False


@pytest.fixture
def shared_sqlite(monkeypatch):
    """Starlette's TestClient runs the app on its own thread; the real server uses one event loop."""
    import sqlite3
    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real(*a, **{**k, "check_same_thread": False}))


def fake_vnc():
    """A one-shot TCP server that greets like a VNC server and echoes."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        c, _ = srv.accept()
        c.sendall(b"RFB 003.008\n")
        data = c.recv(100)
        c.sendall(b"echo:" + data)
        c.close()
        srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


def test_the_screen_socket_needs_the_page_login_and_relays_vnc(tmp_path, shared_sqlite):
    app, ctx = make_app(tmp_path)

    class B:
        desktop = Desktop(":95", fake_vnc(), [])
    ctx.browser = B()
    with TestClient(app, base_url="http://127.0.0.1") as c:
        with pytest.raises(WebSocketDisconnect) as no_login:  # no login cookie: closed before accepting
            with c.websocket_connect("/api/twitch/browser/vnc") as ws:
                ws.receive_bytes()
        assert no_login.value.code == 4401
        assert c.post("/api/login", json={"password": "correct horse"}).status_code == 204
        cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())  # TestClient doesn't send its jar on WS
        with pytest.raises(WebSocketDisconnect) as other_site:  # another site's page: refused
            with c.websocket_connect("/api/twitch/browser/vnc",
                                     headers={"origin": "https://evil.example", "cookie": cookie}) as ws:
                ws.receive_bytes()
        assert other_site.value.code == 4403
        # TestClient connects WebSockets as host "testserver", so that is the page's own origin here
        with c.websocket_connect("/api/twitch/browser/vnc", subprotocols=["binary"],
                                 headers={"origin": "http://testserver", "cookie": cookie}) as ws:
            assert ws.receive_bytes() == b"RFB 003.008\n"
            ws.send_bytes(b"hello")
            assert ws.receive_bytes() == b"echo:hello"


def test_browser_endpoints(tmp_path, shared_sqlite):
    app, ctx = make_app(tmp_path)
    m, _, _ = manager("wait")
    ctx.browser = m
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/api/twitch/browser").status_code == 401
        c.post("/api/login", json={"password": "correct horse"})
        assert c.get("/api/twitch/browser").json() == {"status": "idle", "message": "", "available": True}
        assert c.post("/api/twitch/browser").json()["status"] == "starting"
        assert c.delete("/api/twitch/browser").status_code == 204


REAL = shutil.which("Xvfb") and shutil.which("x11vnc") and os.environ.get("DROPWATCH_BROWSER")


@pytest.mark.skipif(not REAL, reason="needs Xvfb, x11vnc and DROPWATCH_BROWSER (the Docker image has them)")
async def test_the_real_screen_starts_serves_vnc_and_stops():
    from dropwatch.desktop import start_desktop
    d = await start_desktop(port=5931)
    try:
        r, w = await asyncio.open_connection("127.0.0.1", d.port)
        assert (await r.read(12)) == b"RFB 003.008\n"
        w.close()
    finally:
        await d.stop()
    assert all(p.returncode is not None for p in d.procs)
