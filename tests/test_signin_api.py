"""Twitch sign-in through the API: a code to enter at twitch.tv/activate (phase 2b, spec §4/§8)."""
import asyncio
from datetime import UTC, datetime

from apihelpers import logged_in, make_app

from dropwatch.api.signin import SignInManager
from dropwatch.events import EventBus
from dropwatch.twitch.auth_browser import SignInError
from dropwatch.twitch.auth_device import DeviceCode
from dropwatch.twitch.session import TwitchSession

S = TwitchSession("tok", 42, "kp", "d", "c", "s")
CODE = DeviceCode("BKDQMDGP", "https://www.twitch.tv/activate", datetime(2026, 10, 10, 12, 30, tzinfo=UTC),
                  5, "dc")


class Store:
    def __init__(self):
        self.session = None

    def set_session(self, s):
        self.session = s


def factory(result, start_error=None, closed=None):
    class P:
        async def start(self):
            if start_error:
                raise start_error
            return CODE

        async def wait(self, code, cancel):
            if isinstance(result, Exception):
                raise result
            if result == "wait":
                await cancel.wait()
                raise SignInError("Sign-in cancelled.")
            return result

    async def close():
        if closed is not None:
            closed.append(True)
    return lambda: (P(), close)


async def test_start_returns_the_code_then_signs_in():
    started, closed = [], []

    async def on_signed_in():
        started.append(True)
    bus, st = EventBus(), Store()
    q = bus.subscribe()
    m = SignInManager(st, bus, factory(S, closed=closed), on_signed_in)
    status = await m.start()
    assert status["status"] == "waiting" and status["code"] == "BKDQMDGP"
    assert status["verification_uri"] == "https://www.twitch.tv/activate"
    assert status["expires_at"] == CODE.expires_at
    await m.wait()
    assert st.session == S and started == [True] and closed == [True]
    assert m.status()["status"] == "done" and m.status()["message"] == "Signed in as kp."
    kinds = [q.get_nowait() for _ in range(q.qsize())]
    assert [d["status"] for k, d in kinds if k == "signin"] == ["waiting", "done"]


async def test_expired_code_reports_expired():
    st = Store()
    m = SignInManager(st, EventBus(), factory(SignInError("That code expired. Get a new one.")),
                      lambda: asyncio.sleep(0))
    await m.start()
    await m.wait()
    assert st.session is None and m.status()["status"] == "expired"


async def test_failure_reports_message_without_saving():
    st = Store()
    m = SignInManager(st, EventBus(), factory(SignInError("Twitch refused the sign-in (x).")),
                      lambda: asyncio.sleep(0))
    await m.start()
    await m.wait()
    assert st.session is None and m.status()["status"] == "failed"
    assert m.status()["message"] == "Twitch refused the sign-in (x)."


async def test_start_failure_is_failed_and_closes():
    closed = []
    m = SignInManager(Store(), EventBus(), factory(S, SignInError("Twitch wouldn't start a sign-in (x)."),
                                                   closed), lambda: asyncio.sleep(0))
    status = await m.start()
    assert status["status"] == "failed" and closed == [True]


async def test_crash_after_sign_in_is_failed_not_stuck():
    async def boom():
        raise RuntimeError("restart failed")
    m = SignInManager(Store(), EventBus(), factory(S), boom)
    await m.start()
    await m.wait()
    assert m.status()["status"] == "failed"


async def test_cancel_and_no_double_start():
    m = SignInManager(Store(), EventBus(), factory("wait"), lambda: asyncio.sleep(0))
    assert (await m.start())["status"] == "waiting"
    assert await m.start() is None
    m.cancel()
    await m.wait()
    assert m.status()["status"] == "idle"  # cancelling is not a failure (phase-3 review)


async def test_endpoints(tmp_path):
    app, ctx = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.post("/api/twitch/signin")
    assert r.status_code == 202 and r.json()["code"] == "BKDQMDGP"
    assert (await c.post("/api/twitch/signin")).status_code == 409
    assert (await c.get("/api/twitch/signin")).json()["status"] == "waiting"
    assert (await c.delete("/api/twitch/signin")).status_code == 204 and ctx.signin.cancelled == 1
    ctx.store.set_session(S)
    r = await c.post("/api/twitch/signout")
    assert r.status_code == 204 and ctx.store.get_session() is None and ctx.service.stopped == 1
    await c.aclose()
