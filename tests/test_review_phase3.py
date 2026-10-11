"""Regression tests for the phase-3 final review (backend side): C1, I1, I4, cancel-as-idle, UNC paths."""
import asyncio
import pathlib

import httpx
from apihelpers import NOW, logged_in, make_app
from test_phase3_backend import web_app
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan
from test_signin_api import Store as SignStore
from test_signin_api import factory

from dropwatch.api.signin import SignInManager
from dropwatch.events import EventBus
from dropwatch.runner import Runner


class CountingClient(FakeClient):
    def __init__(self, *a):
        super().__init__(*a)
        self.fetches = 0

    async def campaigns(self):
        self.fetches += 1
        return await super().campaigns()

    async def live_channels(self, campaigns, prefs, now):
        self.fetches += 1
        return await super().live_channels(campaigns, prefs, now)


async def runner_on(store):
    r = Runner(CountingClient([camp()], [chan("a", 7), chan("b", 8)]), FakeWatcher(), FakePubSub(), store,
               user_id=42, clock=lambda: NOW)
    await r.refresh()
    r._client.fetches = 0
    return r


# I1: a list change takes effect at once, without waiting on Twitch
async def test_put_lists_replans_immediately_without_fetching(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_on(ctx.store)
    assert ctx.service.runner.plan.current.campaign_id == "c1"
    c = await logged_in(app)
    r = await c.put("/api/lists", json={"priority": [], "never": ["Palia"], "favourites": []})
    assert r.status_code == 200
    assert ctx.service.runner.plan.current is None          # Palia is on Never now
    assert ctx.service.runner._client.fetches == 0          # no network round trip
    await c.aclose()


async def test_mine_now_and_channel_replan_without_fetching(tmp_path):
    app, ctx = make_app(tmp_path)
    r = ctx.service.runner = await runner_on(ctx.store)
    other = "b" if r.watching.login == "a" else "a"
    c = await logged_in(app)
    assert (await c.post("/api/channel", json={"login": other})).status_code == 204
    assert (await c.post("/api/mine-now", json={"campaign_id": "c1"})).status_code == 204
    assert r.watching.login == other and r._client.fetches == 0
    await c.aclose()


# C1: after a sign-out the sign-in status starts over (not a stale "done")
async def test_signout_resets_sign_in_status(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.signin.state = {"status": "done", "message": "Signed in as kp."}
    c = await logged_in(app)
    assert (await c.post("/api/twitch/signout")).status_code == 204
    assert (await c.get("/api/twitch/signin")).json()["status"] == "idle"
    await c.aclose()


async def test_manager_reset_returns_to_idle():
    m = SignInManager(SignStore(), EventBus(), factory("wait"), lambda: asyncio.sleep(0))
    await m.start()
    m.reset()
    await m.wait()
    assert m.status()["status"] == "idle"


# minor re-graded: Cancel is not a failure
async def test_cancel_is_idle_not_failed():
    m = SignInManager(SignStore(), EventBus(), factory("wait"), lambda: asyncio.sleep(0))
    await m.start()
    m.cancel()
    await m.wait()
    assert m.status() == {"status": "idle", "message": ""}


# I4: a rebuilt page is never served from a stale cache
async def test_index_is_not_cached(tmp_path):
    app = web_app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        for path in ("/", "/priorities"):
            assert (await c.get(path)).headers["cache-control"] == "no-cache"


# minor re-graded: Windows network paths never reach the filesystem
async def test_network_paths_never_touch_the_filesystem(tmp_path, monkeypatch):
    app = web_app(tmp_path)
    real = pathlib.Path.resolve
    touched = []

    inside = str(tmp_path)

    def spy(self, *a, **k):
        # anything outside the page folder (a UNC share, another drive) is the danger
        if "evil" in str(self) and not str(self).startswith(inside):
            touched.append(str(self))
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "resolve", spy)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        for path in ("///evil.host/share/x", "/%5C%5Cevil.host%5Cshare%5Cx", "/%2F%2Fevil.host/share",
                     "/c:%5Cevil"):
            r = await c.get(path)
            assert r.status_code == 200 and "<title>Dropwatch</title>" in r.text
    assert touched == []
