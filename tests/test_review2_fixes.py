"""Regression tests for the second (playback) review: R1-R3 Important, R4-R7 re-graded."""
import asyncio
from datetime import timedelta

from test_playback import CH, NOW, FakeGql, Net, S, media
from test_runner import FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

import dropwatch.twitch.watch as watch_mod
from dropwatch.models import LiveChannel
from dropwatch.runner import FAILS_BEFORE_SWITCH, STALL_TICKS, Runner, State
from dropwatch.twitch.constants import PLAY_INTERVAL
from dropwatch.twitch.gql import GqlError
from dropwatch.twitch.pubsub import DropProgress
from dropwatch.twitch.transport import HttpResponse
from dropwatch.twitch.watch import Watcher, playlist_urls


# R1: a new broadcast on the same login must get a new playback token / media URL
async def test_r1_new_broadcast_refetches_media_url():
    gql = FakeGql()
    net = Net([media("a.ts"), media("b.ts")])
    w = Watcher(net, lambda: S, gql, clock=lambda: 0.0)
    assert await w.send(CH, NOW)
    restarted = LiveChannel(77, "streamer", 1, 10, True, "b999", "Palia")
    assert await w.send(restarted, NOW)
    assert gql.calls == 2


# R2: bounded requests; one bad segment doesn't abort the rest; spade can't fail a send
class SlowNet(Net):
    def __init__(self, medias, slow=(), broken=()):
        super().__init__(medias)
        self.slow, self.broken = slow, broken

    async def request(self, method, url, *, headers, json=None, data=None):
        if method == "HEAD" and any(url.endswith(s) for s in self.slow):
            self.calls.append((method, url))
            await asyncio.sleep(5)
        if method == "HEAD" and any(url.endswith(s) for s in self.broken):
            self.calls.append((method, url))
            raise OSError("reset")
        return await super().request(method, url, headers=headers, json=json, data=data)


async def test_r2_slow_head_is_bounded_and_others_still_heads(monkeypatch):
    monkeypatch.setattr(watch_mod, "HEAD_TIMEOUT", 0.05)
    net = SlowNet([media("slow.ts", "b.ts")], slow=("slow.ts",))
    w = Watcher(net, lambda: S, FakeGql(), clock=lambda: 0.0)
    ok = await asyncio.wait_for(w.send(CH, NOW), 2)
    assert ok is False
    assert ("HEAD", "https://video.example/160p/b.ts") in net.calls


async def test_r2_broken_head_does_not_abort_loop():
    net = SlowNet([media("bad.ts", "b.ts")], broken=("bad.ts",))
    w = Watcher(net, lambda: S, FakeGql(), clock=lambda: 0.0)
    assert await w.send(CH, NOW) is False
    assert ("HEAD", "https://video.example/160p/b.ts") in net.calls


async def test_r2_spade_error_does_not_fail_send():
    class SpadeDown(Net):
        async def request(self, method, url, *, headers, json=None, data=None):
            if "www.twitch.tv" in url:
                raise OSError("twitch.tv unreachable")
            return await super().request(method, url, headers=headers, json=json, data=data)
    assert await Watcher(SpadeDown([media("a.ts")]), lambda: S, FakeGql(), clock=lambda: 0.0).send(CH, NOW)


async def test_r2_safe_tick_compensates_for_tick_duration():
    now = [camp().starts_at + timedelta(days=1)]

    class SlowWatcher(FakeWatcher):
        async def send(self, channel, t):
            now[0] += timedelta(seconds=4)
            return True
    r = Runner(FakeClient([camp()], [chan("a", 7)]), SlowWatcher(), FakePubSub(), FakeStore(),
               user_id=42, clock=lambda: now[0])
    await r.refresh()
    assert await r.safe_tick() == PLAY_INTERVAL - 4


# R3: channel exclusion needs ~90 s of failures, not 30 s
async def test_r3_three_failed_ticks_do_not_exclude_channel():
    r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(ok=False), FakePubSub(), FakeStore(),
               user_id=42, clock=lambda: camp().starts_at + timedelta(days=1))
    await r.refresh()
    for _ in range(3):
        await r.tick()
    assert r.watching is not None and r.watching.login == "a"
    assert FAILS_BEFORE_SWITCH * PLAY_INTERVAL >= 90


# R4: the claim wait is time-based and is not re-armed after giving up
async def test_r4_claim_wait_expires_by_time_and_is_not_rearmed():
    base = camp().starts_at + timedelta(days=1)
    now = [base]
    fetches = []

    class C(FakeClient):
        async def campaigns(self):
            fetches.append(now[0])
            return [camp(cur=60)]   # never gets a claim id
    r = Runner(C([camp(cur=60)], [chan("a", 7)]), FakeWatcher(), FakePubSub(), FakeStore(),
               user_id=42, clock=lambda: now[0])
    await r.refresh()
    await r.handle(DropProgress("d1", 60, 60))
    for minutes in range(5, 120, 5):
        now[0] = base + timedelta(minutes=minutes)
        await r.refresh()
        if minutes == 65:
            await r.handle(DropProgress("d1", 60, 60))  # must not re-arm
    late = [t for t in fetches if t > base + timedelta(minutes=66)]
    assert len(late) <= 1  # only the regular hourly fetch after giving up


# R5: a resync that finds nothing waits another STALL_TICKS before retrying
async def test_r5_failed_resync_is_not_retried_every_tick():
    calls = []

    class C(FakeClient):
        async def current_drop(self, channel_id):
            calls.append(1)
            return None
    r = Runner(C([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), FakeStore(), user_id=42,
               clock=lambda: camp().starts_at + timedelta(days=1))
    await r.refresh()
    for _ in range(STALL_TICKS * 2):
        await r.tick()
    assert len(calls) <= 2


# R6: refreshes back off while Twitch is unreachable
async def test_r6_unreachable_refresh_backs_off():
    base = camp().starts_at + timedelta(days=1)
    now = [base]
    attempts = []

    class C(FakeClient):
        async def live_channels(self, campaigns, prefs, t):
            attempts.append(t)
            raise GqlError("service timeout")
    r = Runner(C([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), FakeStore(), user_id=42,
               clock=lambda: now[0])
    await r.refresh()
    assert r.state == State.TWITCH_UNREACHABLE
    for i in range(1, 6):          # 50 s of 10 s ticks
        now[0] = base + timedelta(seconds=10 * i)
        await r.tick()
    assert len(attempts) == 1


# R7: malformed playlists never raise out of the watcher
def test_r7_playlist_urls_swallows_invalid_urls():
    assert playlist_urls("#EXTM3U\n#EXTINF:2,\nhttp://[::1/seg.ts\n", "https://x/y.m3u8") == []


async def test_r7_non_dict_token_response_is_a_failed_send():
    class G:
        async def run(self, payload):
            return {"data": "unexpected"}
    assert await Watcher(Net([media("a.ts")]), lambda: S, G(), clock=lambda: 0.0).send(CH, NOW) is False


async def test_r7_undecodable_body_is_a_failed_send():
    class Bad(Net):
        async def request(self, method, url, *, headers, json=None, data=None):
            if "usher" in url:
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return await super().request(method, url, headers=headers, json=json, data=data)
    assert await Watcher(Bad([media("a.ts")]), lambda: S, FakeGql(), clock=lambda: 0.0).send(CH, NOW) is False


def _unused():  # keep HttpResponse import meaningful for readers of the fakes
    return HttpResponse(200, "")
