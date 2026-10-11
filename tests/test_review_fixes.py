"""Regression tests for the phase-1 final review findings (C1, I1-I6, M1, M2, M8)."""
import asyncio
import json
from datetime import timedelta

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
from test_runner import NOW, FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

from dropwatch.models import Campaign, Drop, Game, LiveChannel, Prefs, Reward, drop_earnable_now
from dropwatch.planner import plan
from dropwatch.runner import Runner, State
from dropwatch.twitch.client import TwitchClient
from dropwatch.twitch.gql import Gql, GqlError, op
from dropwatch.twitch.pubsub import PubSub, StreamDown, StreamUp
from dropwatch.twitch.session import TwitchSession
from dropwatch.twitch.transport import HttpResponse
from dropwatch.twitch.watch import Watcher

R = Reward("r", "Reward", "", "DIRECT_ENTITLEMENT")
S = TwitchSession("tok", 42, "me", "dev", "cid", "sess")
G1, G2 = Game(1, "Palia", "palia"), Game(2, "Phasmophobia", "phasmophobia")


def mk(cid, game, *, need=120, cur=0, end_h=10, linked=True, allowed=()):
    d = Drop(f"{cid}-d", "d", (R,), NOW - timedelta(days=1), NOW + timedelta(hours=end_h),
             need, cur, False, None)
    return Campaign(cid, cid, game, NOW - timedelta(days=1), NOW + timedelta(hours=end_h),
                    linked, "", tuple(allowed), (d,))


def live(login, game, viewers=100):
    return LiveChannel(abs(hash(login)) % 99999, login, game.id, viewers, True, "b" + login, game.name)


def runner(client, watcher=None):
    return Runner(client, watcher or FakeWatcher(), FakePubSub(), FakeStore(), user_id=42, clock=lambda: NOW)


# --- C1: a network or GQL error must never escape the loop
class RaisingWatcher(FakeWatcher):
    async def send(self, channel, now):
        raise OSError("connection reset")


async def test_c1_watcher_transport_error_returns_false():
    class T:
        async def request(self, method, url, *, headers, json=None, data=None):
            raise OSError("reset")

    class G:
        async def run(self, payload):
            return {"data": {"streamPlaybackAccessToken": {"value": "v", "signature": "s"}}}
    assert await Watcher(T(), lambda: S, G()).send(chan("a", 7), NOW) is False


async def test_c1_refresh_survives_plain_gql_error():
    c = FakeClient([camp()], [chan("a", 7)])
    c.fail = GqlError("service timeout")
    r = runner(c)
    await r.refresh()
    assert r.state == State.TWITCH_UNREACHABLE


async def test_c1_safe_tick_never_raises_and_backs_off():
    r = runner(FakeClient([camp()], [chan("a", 7)]), RaisingWatcher())
    await r.refresh()
    first = await r.safe_tick()
    second = await r.safe_tick()
    assert r.state == State.TWITCH_UNREACHABLE
    assert first >= 60 and second > first


async def test_c1_current_drop_error_is_swallowed():
    class C(FakeClient):
        async def current_drop(self, channel_id):
            raise GqlError("service error")
    r = runner(C([camp()], [chan("a", 7)]))
    await r.refresh()
    from dropwatch.runner import STALL_TICKS
    for _ in range(STALL_TICKS + 1):
        await r.tick()
    assert r.state == State.MINING


# --- I1: an exception while handling one event must not stop later events
async def test_i1_safe_handle_survives_errors():
    class BrokenPubSub(FakePubSub):
        calls = 0

        def set_topics(self, topics):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("pubsub broke")
            super().set_topics(topics)
    r = Runner(FakeClient([camp()], [chan("a", 7), chan("b", 8)]), FakeWatcher(), BrokenPubSub(),
               FakeStore(), user_id=42, clock=lambda: NOW)
    await r.refresh()
    await r.safe_handle(StreamDown(r.watching.id))  # handling raises inside; must not escape
    assert r.state == State.TWITCH_UNREACHABLE


# --- I2: concurrent refresh + claim event claims once
async def test_i2_concurrent_claims_happen_once():
    c = FakeClient([camp(cur=60, claim_id="inst")], [chan("a", 7)])
    r = runner(c)
    from dropwatch.twitch.pubsub import DropClaimable
    await asyncio.gather(r.refresh(), r.handle(DropClaimable("d1", "inst")))
    assert c.claims == ["inst"]
    assert sum(1 for k, _ in r._store.events if k == "claimed") == 1


# --- I3: fewer GQL calls
class CountingGql:
    def __init__(self):
        self.ops = []

    async def run(self, payload):
        self.ops.append((payload["operationName"], payload.get("variables", {})))
        return {"data": {"game": {"streams": {"edges": []}}}}

    async def run_many(self, payloads):
        for p in payloads:
            self.ops.append((p["operationName"], p.get("variables", {})))
        return [{"data": {"user": None}} for _ in payloads]


async def test_i3_live_channels_only_for_minable_campaigns():
    g = CountingGql()
    unlinked = mk("u", G1, linked=False)
    acl_only = mk("a", G2, allowed=("dnd",))
    await TwitchClient(g, 42).live_channels([unlinked, acl_only], Prefs(), NOW)
    dirs = [v["slug"] for name, v in g.ops if name == "DirectoryPage_Game"]
    infos = [v["channel"] for name, v in g.ops if name == "VideoPlayerStreamInfoOverlayChannel"]
    # unlinked game skipped. Since 2026-10-10 an ACL-only game gets a directory look too (its allowed
    # channels are asked about by name only when the directory shows none of them)
    assert dirs == [G2.slug]
    assert infos == ["dnd"]


async def test_i3_gql_rate_limited_to_5_per_second():
    t = [0.0]
    sleeps = []

    async def sleep(s):
        sleeps.append(s)
        t[0] += s

    class Tr:
        async def request(self, method, url, *, headers, json=None, data=None):
            return HttpResponse(200, '{"data": {}}')

    g = Gql(Tr(), lambda: S, sleep=sleep, clock=lambda: t[0])
    for _ in range(7):
        await g.run(op("Inventory"))
    assert sum(sleeps) >= 1.0


async def test_i3_campaigns_fetched_hourly_not_every_refresh():
    calls = []

    class C(FakeClient):
        async def campaigns(self):
            calls.append(1)
            return await super().campaigns()
    now = [NOW]
    r = Runner(C([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), FakeStore(),
               user_id=42, clock=lambda: now[0])
    await r.refresh()
    now[0] = NOW + timedelta(minutes=10)
    await r.refresh()
    assert len(calls) == 1
    now[0] = NOW + timedelta(minutes=61)
    await r.refresh()
    assert len(calls) == 2


# --- I4: no ping-pong between near-equal non-priority campaigns
def test_i4_keeps_current_campaign_when_challenger_barely_more_urgent():
    a, b = mk("a", G1, need=120), mk("b", G2, need=118)
    chans = [live("x", G1), live("y", G2)]
    first = plan([a, b], chans, Prefs(), NOW).current.campaign_id
    other = "a" if first == "b" else "b"
    # we are mining `other`; `first` is only slightly more urgent (not by the 20% margin) -> stay
    p = plan([a, b], chans, Prefs(), NOW, current_campaign=other)
    assert p.current.campaign_id == other
    assert first in p.queue


def test_i4_switches_when_challenger_much_more_urgent():
    calm, urgent = mk("calm", G1, need=60, end_h=48), mk("urgent", G2, need=300, end_h=6)
    p = plan([calm, urgent], [live("x", G1), live("y", G2)], Prefs(), NOW, current_campaign="calm")
    assert p.current.campaign_id == "urgent"


def test_i4_priority_still_wins_immediately():
    a, b = mk("a", G1), mk("b", G2)
    p = plan([a, b], [live("x", G1), live("y", G2)], Prefs(priority=("Phasmophobia",)), NOW,
             current_campaign="a")
    assert p.current.campaign_id == "b"


# --- I5: stream-down takes effect even if the directory still lists the stream
async def test_i5_stream_down_excludes_channel_until_up():
    c = FakeClient([camp()], [chan("a", 7), chan("b", 8)])  # fake keeps listing both
    r = runner(c)
    await r.refresh()
    gone = r.watching
    await r.handle(StreamDown(gone.id))
    assert r.watching.login != gone.login
    await r.handle(StreamUp(gone.id))
    assert gone.login not in r._excluded


# --- I6: reference retry rules
class Seq:
    def __init__(self, replies):
        self.replies = list(replies)

    async def request(self, method, url, *, headers, json=None, data=None):
        return self.replies.pop(0)


async def nosleep(_):
    return None


async def test_i6_service_timeout_retried():
    t = Seq([HttpResponse(200, json.dumps({"errors": [{"message": "service timeout"}]})),
             HttpResponse(200, '{"data": {"ok": 1}}')])
    assert (await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory")))["data"] == {"ok": 1}


async def test_i6_429_retried():
    t = Seq([HttpResponse(429, "slow down"), HttpResponse(200, '{"data": {}}')])
    assert await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory")) == {"data": {}}


async def test_i6_top_level_error_body_raises_gql_error():
    t = Seq([HttpResponse(400, '{"error": "Bad Request", "status": 400, "message": "nope"}')])
    try:
        await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory"))
    except GqlError as exc:
        assert "nope" in str(exc) or "Bad Request" in str(exc)
    else:
        raise AssertionError("expected GqlError")


# --- M1 (re-graded Important): a completed but unclaimed drop is not mined further
def test_m1_completed_unclaimed_drop_not_earnable():
    d = Drop("d", "d", (R,), NOW - timedelta(days=1), NOW + timedelta(days=1), 60, 60, False, None)
    c = Campaign("c", "c", G1, NOW - timedelta(days=1), NOW + timedelta(days=1), True, "", (), (d,))
    assert not drop_earnable_now(c, d, NOW)
    assert plan([c], [live("x", G1)], Prefs(), NOW).current is None


# --- M2 (re-graded Important): catch-up claims whenever a claim id exists
async def test_m2_catch_up_claims_even_if_minutes_lag():
    c = FakeClient([camp(cur=59, claim_id="inst")], [chan("a", 7)])
    await runner(c).refresh()
    assert c.claims == ["inst"]


# --- M8 (re-graded Important): a malformed frame doesn't kill the PubSub reader
async def test_m8_malformed_frame_is_skipped():
    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == WSMsgType.TEXT and json.loads(msg.data)["type"] == "LISTEN":
                await ws.send_str("not json at all")
                await ws.send_json({"type": "MESSAGE"})  # missing data
                await ws.send_json({"type": "MESSAGE", "data": {
                    "topic": "video-playback-by-id.7", "message": json.dumps({"type": "stream-down"})}})
        return ws

    app = web.Application()
    app.router.add_get("/", handler)
    async with TestServer(app) as server:
        ps = PubSub(lambda: "tok", str(server.make_url("/")).replace("http", "ws"))
        ps.set_topics({"video-playback-by-id.7"})
        ev = await asyncio.wait_for(anext(ps.events()), 5)
        await ps.close()
    assert ev == StreamDown(7)
