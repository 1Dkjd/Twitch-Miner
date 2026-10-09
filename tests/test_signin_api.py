import asyncio

from apihelpers import logged_in, make_app

from dropsminer.api.signin import SignInManager
from dropsminer.events import EventBus
from dropsminer.twitch.auth_browser import SignInError
from dropsminer.twitch.session import TwitchSession

S = TwitchSession("tok", 42, "kp", "d", "c", "s")


class Store:
    def __init__(self):
        self.session = None

    def set_session(self, s):
        self.session = s


def factory(result):
    class P:
        async def sign_in(self, cancel):
            if isinstance(result, Exception):
                raise result
            if result == "wait":
                await cancel.wait()
                raise SignInError("Sign-in cancelled.")
            return result

    async def close():
        return None
    return lambda: (P(), close)


async def test_successful_sign_in_saves_session_and_starts_miner():
    started = []

    async def on_signed_in():
        started.append(True)
    bus, st = EventBus(), Store()
    q = bus.subscribe()
    m = SignInManager(st, bus, factory(S), on_signed_in)
    assert m.start() is True
    await m.wait()
    assert st.session == S and started == [True]
    assert m.status() == {"status": "done", "message": "Signed in as kp."}
    assert (await q.get())[0] == "signin"


async def test_failure_reports_message_without_saving():
    st = Store()
    m = SignInManager(st, EventBus(), factory(SignInError("Twitch issued a WEB token.")),
                      lambda: asyncio.sleep(0))
    m.start()
    await m.wait()
    assert st.session is None and m.status() == {"status": "failed", "message": "Twitch issued a WEB token."}


async def test_cancel_and_no_double_start():
    m = SignInManager(Store(), EventBus(), factory("wait"), lambda: asyncio.sleep(0))
    assert m.start() is True and m.start() is False
    m.cancel()
    await m.wait()
    assert m.status()["status"] == "failed" and "cancelled" in m.status()["message"]


async def test_endpoints(tmp_path):
    app, ctx = make_app(tmp_path)
    c = await logged_in(app)
    assert (await c.post("/api/twitch/signin")).status_code == 202
    assert (await c.post("/api/twitch/signin")).status_code == 409
    assert (await c.get("/api/twitch/signin")).json()["status"] == "running"
    assert (await c.delete("/api/twitch/signin")).status_code == 204 and ctx.signin.cancelled == 1
    ctx.store.set_session(S)
    r = await c.post("/api/twitch/signout")
    assert r.status_code == 204 and ctx.store.get_session() is None and ctx.service.stopped == 1
    await c.aclose()
