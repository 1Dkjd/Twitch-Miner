"""Phase 2b Task 5: a campaign whose link is unknown and that earns nothing for 10 minutes moves to
Needs you as "may need linking" (spec §4, 2026-10-10)."""
from dataclasses import replace
from datetime import timedelta

from test_runner import NOW, FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

from dropwatch.api.views import state_view
from dropwatch.runner import LINK_PROBE_TICKS, Runner
from dropwatch.twitch.pubsub import DropProgress


def unknown():
    return replace(camp(), linked=None)


class NoProgressClient(FakeClient):
    async def current_drop(self, channel_id):
        return None  # an unlinked campaign earns nothing, so Twitch reports no drop session


def make(campaign):
    clock = [NOW]
    emitted = []
    r = Runner(NoProgressClient([campaign], [chan("a", 7)]), FakeWatcher(), FakePubSub(), FakeStore(),
               user_id=42, clock=lambda: clock[0], emit=lambda k, d: emitted.append((k, d)))
    return r, clock, emitted


async def ticks(r, clock, n):
    for _ in range(n):
        clock[0] += timedelta(seconds=10)
        await r.tick()


async def test_unknown_link_marked_after_10_min_flat():
    r, clock, emitted = make(unknown())
    await r.refresh()
    assert r.plan.current.campaign_id == "c1"
    await ticks(r, clock, LINK_PROBE_TICKS)
    assert "c1" in r.maybe_unlinked
    assert r.plan.current is None and "c1" in r.plan.needs_you
    assert ("needs_you", {"campaign": "Frights", "reason": "may need linking"}) in emitted
    assert LINK_PROBE_TICKS * 10 == 600


async def test_progress_clears_probe():
    r, clock, _ = make(unknown())
    await r.refresh()
    await ticks(r, clock, LINK_PROBE_TICKS - 10)
    await r.handle(DropProgress("d1", 5, 60))
    await ticks(r, clock, LINK_PROBE_TICKS - 10)
    assert "c1" not in r.maybe_unlinked and r.plan.current.campaign_id == "c1"


async def test_mark_expires_after_6h():
    r, clock, _ = make(unknown())
    await r.refresh()
    await ticks(r, clock, LINK_PROBE_TICKS)
    assert "c1" in r.maybe_unlinked
    clock[0] += timedelta(hours=6, minutes=1)
    await r.refresh()
    assert "c1" not in r.maybe_unlinked and r.plan.current.campaign_id == "c1"


async def test_known_link_never_probed():
    r, clock, emitted = make(camp())
    await r.refresh()
    await ticks(r, clock, LINK_PROBE_TICKS + 5)
    assert r.maybe_unlinked == {} and r.plan.current.campaign_id == "c1"
    assert r._link_probe == {} and not any(k == "needs_you" for k, _ in emitted)


async def test_mark_clears_once_link_is_known():
    r, clock, _ = make(unknown())
    await r.refresh()
    await ticks(r, clock, LINK_PROBE_TICKS)
    r._client.camps = [camp()]           # Inventory now reports the campaign as linked
    await r.refresh(force_campaigns=True)
    assert r.maybe_unlinked == {} and r.plan.current.campaign_id == "c1"


async def test_failed_watch_ticks_do_not_count():
    r, clock, _ = make(unknown())
    r._watcher.ok = False
    await r.refresh()
    await ticks(r, clock, 8)              # below FAILS_BEFORE_SWITCH, all failed sends
    assert r._link_probe.get("c1", (0, 0))[0] == 0


async def test_state_marks_maybe_unlinked():
    class S(FakeStore):
        def get_session(self):
            return None
    r, clock, _ = make(unknown())
    await r.refresh()
    await ticks(r, clock, LINK_PROBE_TICKS)
    s = state_view(r, S(), clock[0])
    item = next(c for c in s.needs_you if c.id == "c1")
    assert item.maybe_unlinked is True and item.linked is None
