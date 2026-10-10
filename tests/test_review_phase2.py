"""Regression tests for the phase-2 final review: I1-I5 (miner lifecycle under `serve`)."""
import asyncio
import logging
import socket
from datetime import timedelta

import httpx
import uvicorn
from apihelpers import NOW, logged_in, make_app
from test_runner import FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

from dropwatch.cli import server_config
from dropwatch.events import EventBus
from dropwatch.models import Campaign, Game, LiveChannel
from dropwatch.runner import Runner, State
from dropwatch.service import MinerService, Parts
from dropwatch.twitch.gql import AuthExpired
from dropwatch.twitch.session import TwitchSession

S = TwitchSession("tok", 42, "me", "dev", "cid", "sess")


class SessionStore(FakeStore):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def get_session(self):
        return self.session

    def clear_session(self):
        self.session = None


async def until(cond, limit=2.0):
    for _ in range(int(limit / 0.01)):
        if cond():
            return True
        await asyncio.sleep(0.01)
    return cond()


# I1: an expired Twitch session tears the miner down and forgets the dead token
async def test_i1_session_expiry_tears_down_and_clears_session():
    closed, st, bus = [], SessionStore(S), EventBus()
    q = bus.subscribe()

    def build(store, session, emit):
        c = FakeClient([camp()], [chan("a", 7)])
        c.fail = AuthExpired("401")
        r = Runner(c, FakeWatcher(), FakePubSub(), store, user_id=42, clock=lambda: NOW, emit=emit)

        async def close():
            closed.append(True)
        return Parts(r, FakePubSub(), close)

    svc = MinerService(st, bus, build=build)
    assert await svc.start()
    assert await until(lambda: not svc.running), "service still running after the session expired"
    assert closed == [True] and st.session is None
    seen = [q.get_nowait() for _ in range(q.qsize())]
    assert ("signin", {"status": "expired", "message": "Twitch session expired. Sign in again."}) in seen


async def test_i1_commands_refused_while_runner_signed_out(tmp_path):
    app, ctx = make_app(tmp_path)
    r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), ctx.store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    r.state = State.SIGNED_OUT
    ctx.service.runner = r
    c = await logged_in(app)
    assert (await c.post("/api/pause", json={"minutes": 5})).status_code == 409
    assert (await c.post("/api/resume")).status_code == 409
    await c.aclose()


# I2: an unexpected error in the first refresh must not silently end mining
async def test_i2_unexpected_refresh_error_keeps_loop_alive():
    bus = EventBus()
    q = bus.subscribe()

    class Drift(FakeClient):
        async def live_channels(self, campaigns, prefs, now):
            raise AttributeError("schema drift")

    def build(store, session, emit):
        r = Runner(Drift([camp()], []), FakeWatcher(), FakePubSub(), store, user_id=42, clock=lambda: NOW,
                   emit=emit)

        async def close():
            return None
        return Parts(r, FakePubSub(), close)

    svc = MinerService(SessionStore(S), bus, build=build)
    await svc.start()
    kind, data = await asyncio.wait_for(q.get(), 2)
    assert kind == "state" and data["state"] == "twitch_unreachable"
    assert svc.running and not svc._tasks[0].done()
    await svc.stop()


async def test_i2_crashed_loop_is_logged_and_stops_the_service(caplog):
    class Broken(Runner):
        async def safe_tick(self):
            raise RuntimeError("bug")

    def build(store, session, emit):
        r = Broken(FakeClient([camp()], []), FakeWatcher(), FakePubSub(), store, user_id=42,
                   clock=lambda: NOW, emit=emit)

        async def close():
            return None
        return Parts(r, FakePubSub(), close)

    svc = MinerService(SessionStore(S), EventBus(), build=build)
    with caplog.at_level(logging.ERROR, logger="dropwatch.service"):
        await svc.start()
        assert await until(lambda: not svc.running), "a crashed loop left the service 'running'"
    assert any("Mining loop crashed" in r.getMessage() for r in caplog.records)


# I3: a sign-out overlapping a sign-in restart must never leave an orphaned (second) miner
async def test_i3_overlapping_stop_and_restart_leave_one_miner():
    made, closed = [], []
    entered, release = asyncio.Event(), asyncio.Event()

    def build(store, session, emit):
        r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), store, user_id=42,
                   clock=lambda: NOW, emit=emit)
        made.append(r)

        async def close():
            if r not in closed:
                closed.append(r)
                if len(made) == 1:      # the sign-out's close of the first miner is slow
                    entered.set()
                    await release.wait()
        return Parts(r, FakePubSub(), close)

    svc = MinerService(SessionStore(S), EventBus(), build=build)
    await svc.start()

    async def signed_in():             # SignInManager's on_signed_in: stop() then start()
        await svc.stop()
        await svc.start()
    signout = asyncio.create_task(svc.stop())
    await entered.wait()               # sign-out is inside the slow close
    signin = asyncio.create_task(signed_in())
    await asyncio.sleep(0.05)          # let the sign-in path run as far as it can
    release.set()
    await asyncio.gather(signout, signin)
    live = [r for r in made if r not in closed]
    assert len(live) == (1 if svc.running else 0), (len(live), svc.running)
    if svc.running:
        assert svc.runner is live[0]
    await svc.stop()


# I4: Ctrl+C must not hang while the page holds an SSE stream open
async def test_i4_shutdown_not_blocked_by_open_sse(tmp_path):
    app, _ = make_app(tmp_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(server_config(app, "127.0.0.1", port))
    serving = asyncio.create_task(server.serve())
    assert await until(lambda: server.started, limit=5)
    base = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(base_url=base) as c:
        assert (await c.post("/api/login", json={"password": "correct horse"})).status_code == 204
        async with c.stream("GET", "/api/events") as resp:
            assert await anext(resp.aiter_text()) == ": connected\n\n"
            server.should_exit = True
            await asyncio.wait_for(asyncio.shield(serving), 8)


# I5: mine-now / channel must say so when the planner can't honour the request
async def _runner(ctx, campaigns, live):
    r = Runner(FakeClient(campaigns, live), FakeWatcher(), FakePubSub(), ctx.store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    return r


async def test_i5_mine_now_refuses_campaign_planner_wont_mine(tmp_path):
    app, ctx = make_app(tmp_path)
    g = Game(2, "Other", "other")
    locked = Campaign("c2", "Locked", g, NOW - timedelta(days=1), NOW + timedelta(days=2), False, "", (),
                      camp().drops)
    r = await _runner(ctx, [camp(), locked], [chan("a", 7)])
    c = await logged_in(app)
    resp = await c.post("/api/mine-now", json={"campaign_id": "c2"})
    assert resp.status_code == 409, resp.status_code
    assert r.plan.current.campaign_id == "c1"
    await c.aclose()


async def test_i5_channel_refuses_login_planner_wont_use(tmp_path):
    app, ctx = make_app(tmp_path)
    other_game = LiveChannel(9, "other", 2, 5, True, "b9", "Other")
    r = await _runner(ctx, [camp()], [chan("a", 7), other_game])
    c = await logged_in(app)
    resp = await c.post("/api/channel", json={"login": "other"})
    assert resp.status_code == 409, resp.status_code
    assert r.watching.login == "a"
    await c.aclose()
