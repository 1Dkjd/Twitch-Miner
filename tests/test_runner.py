from datetime import UTC, datetime, timedelta

from dropwatch.models import Campaign, Drop, Game, LiveChannel, Prefs, Reward
from dropwatch.runner import Runner, State
from dropwatch.twitch.gql import AuthExpired, TwitchUnreachable
from dropwatch.twitch.pubsub import DropClaimable, DropProgress, StreamDown

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
G = Game(1, "Palia", "palia")


def camp(cur=0, claim_id=None, claimed=False):
    d = Drop("d1", "Glasses", (Reward("r", "Palcat Glasses", "", "DIRECT_ENTITLEMENT"),),
             NOW - timedelta(days=1), NOW + timedelta(days=4), 60, cur, claimed, claim_id)
    return Campaign("c1", "Frights", G, NOW - timedelta(days=1), NOW + timedelta(days=4),
                    True, "", (), (d,))


def chan(login, cid):
    return LiveChannel(cid, login, 1, 100, True, f"b{cid}", "Palia")


class FakeClient:
    def __init__(self, campaigns, live):
        self.camps, self.live, self.claims, self.fail = campaigns, live, [], None

    async def campaigns(self):
        if self.fail:
            raise self.fail
        return list(self.camps)

    async def live_channels(self, campaigns, prefs, now):
        return list(self.live)

    async def claim(self, claim_id):
        self.claims.append(claim_id)
        self.camps = [camp(cur=60, claimed=True)]
        return True

    async def waiting_points_claim(self, login):
        return None  # no channel points chest waiting

    async def claim_points(self, channel_id, claim_id):
        return True

    async def current_drop(self, channel_id):
        return ("d1", 30)


class FakeWatcher:
    def __init__(self, ok=True):
        self.ok, self.sent, self.forgotten = ok, [], []

    async def send(self, channel, now):
        self.sent.append(channel.login)
        return self.ok

    def forget(self, login):
        self.forgotten.append(login)


class FakePubSub:
    def __init__(self):
        self.topics = set()

    def set_topics(self, topics):
        self.topics = set(topics)


class FakeStore:
    def __init__(self):
        self.events = []

    def get_prefs(self):
        return Prefs()

    def log_event(self, kind, data):
        self.events.append((kind, data))


def runner(client, watcher=None, clock=lambda: NOW):
    return Runner(client, watcher or FakeWatcher(), FakePubSub(), FakeStore(), user_id=42, clock=clock)


async def test_refresh_picks_channel_and_subscribes():
    r = runner(FakeClient([camp()], [chan("a", 7)]))
    await r.refresh()
    assert r.state == State.MINING and r.watching.login == "a"
    assert "video-playback-by-id.7" in r._pubsub.topics
    assert "user-drop-events.42" in r._pubsub.topics


async def test_tick_sends_heartbeat():
    w = FakeWatcher()
    r = runner(FakeClient([camp()], [chan("a", 7)]), w)
    await r.refresh()
    await r.tick()
    assert w.sent == ["a"]


async def test_claim_on_event_and_logged():
    c = FakeClient([camp(cur=60, claim_id="inst")], [chan("a", 7)])
    r = runner(c)
    await r.refresh()  # catch-up claim happens here
    assert c.claims == ["inst"]
    # game added 2026-10-10 for Activity
    want = ("claimed", {"campaign": "Frights", "reward": "Palcat Glasses", "game": "Palia"})
    assert want in r._store.events
    c2 = FakeClient([camp(cur=50)], [chan("a", 7)])
    r2 = runner(c2)
    await r2.refresh()
    await r2.handle(DropClaimable("d1", "inst2"))
    assert c2.claims == ["inst2"]


async def test_progress_updates_minutes():
    r = runner(FakeClient([camp()], [chan("a", 7)]))
    await r.refresh()
    await r.handle(DropProgress("d1", 33, 60))
    assert r.campaigns[0].drop("d1").current_minutes == 33


async def test_stream_down_switches_channel():
    c = FakeClient([camp()], [chan("a", 7), chan("b", 8)])
    r = runner(c)
    await r.refresh()
    first = r.watching.login
    c.live = [x for x in c.live if x.login != first]
    await r.handle(StreamDown(r.watching.id))
    assert r.watching.login != first
    assert r.state == State.SWITCHED


async def test_three_heartbeat_failures_drop_the_channel():
    c = FakeClient([camp()], [chan("a", 7), chan("b", 8)])
    w = FakeWatcher(ok=False)
    r = runner(c, w)
    await r.refresh()
    bad = r.watching.login
    from dropwatch.runner import FAILS_BEFORE_SWITCH
    for _ in range(FAILS_BEFORE_SWITCH):
        await r.tick()
    assert w.forgotten == [bad]
    assert r.watching.login != bad


async def test_pause_and_resume():
    w = FakeWatcher()
    r = runner(FakeClient([camp()], [chan("a", 7)]), w)
    await r.refresh()
    r.pause(NOW + timedelta(hours=1))
    await r.tick()
    assert r.state == State.PAUSED and w.sent == []
    r.resume()
    await r.tick()
    assert w.sent == ["a"]


async def test_pause_expires_by_clock():
    now = [NOW]
    w = FakeWatcher()
    r = runner(FakeClient([camp()], [chan("a", 7)]), w, clock=lambda: now[0])
    await r.refresh()
    r.pause(NOW + timedelta(minutes=30))
    now[0] = NOW + timedelta(minutes=31)
    await r.tick()
    assert w.sent == ["a"]


async def test_auth_expired_sets_signed_out():
    c = FakeClient([camp()], [chan("a", 7)])
    c.fail = AuthExpired("401")
    r = runner(c)
    await r.refresh()
    assert r.state == State.SIGNED_OUT


async def test_unreachable_state():
    c = FakeClient([camp()], [chan("a", 7)])
    c.fail = TwitchUnreachable("down")
    r = runner(c)
    await r.refresh()
    assert r.state == State.TWITCH_UNREACHABLE


async def test_idle_when_nothing_live():
    r = runner(FakeClient([camp()], []))
    await r.refresh()
    assert r.state == State.IDLE and r.watching is None


async def test_safe_tick_paces_at_play_interval():
    from dropwatch.twitch.constants import PLAY_INTERVAL
    r = runner(FakeClient([camp()], [chan("a", 7)]))
    await r.refresh()
    assert await r.safe_tick() == PLAY_INTERVAL


async def test_completed_drop_is_claimed_at_next_refresh_not_hourly():
    # Twitch may never send drop-claim on PubSub: a drop reaching its minutes must trigger a
    # campaign re-fetch (to pick up the claim id) at the next 5-minute refresh, not an hour later.
    now = [NOW]

    class C(FakeClient):
        fetches = 0

        async def campaigns(self):
            C.fetches += 1
            if C.fetches > 1:   # Twitch has issued the claim id by the next fetch
                return [camp(cur=60, claim_id="inst")]
            return [camp(cur=50)]
    c = C([camp(cur=50)], [chan("a", 7)])
    r = Runner(c, FakeWatcher(), FakePubSub(), FakeStore(), user_id=42, clock=lambda: now[0])
    await r.refresh()
    await r.handle(DropProgress("d1", 60, 60))
    now[0] = NOW + timedelta(minutes=6)
    await r.tick()
    assert c.claims == ["inst"]
