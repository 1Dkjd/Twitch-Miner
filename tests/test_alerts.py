"""When Dropwatch notifies (feat/notifications, mockup docs/design/notifications-mockup.html approved
2026-10-10): each failure once when it starts and once when it clears; the waits come from settings."""
from datetime import timedelta

from test_runner import NOW

from dropwatch.alerts import Notifier, Snapshot
from dropwatch.store import Store


def make(tmp_path, **settings):
    st = Store(tmp_path / "d.db")
    st.put_settings(settings)
    clock = [NOW]
    return Notifier(st, clock=lambda: clock[0]), clock, st


def titles(alerts):
    return [a.title for a in alerts]


SNAP = Snapshot(campaign="EXFIL Brothers Day 2", channel="honeyxxo", needs_you=[])


def test_sign_in_alerts_once_then_says_when_it_works_again(tmp_path):
    n, _, _ = make(tmp_path)
    assert titles(n.handle("state", {"state": "signed_out"})) == ["Dropwatch: Twitch sign-in stopped working"]
    assert n.handle("signin", {"status": "expired"}) == []  # the same problem, already said
    assert titles(n.handle("state", {"state": "mining"})) == ["Dropwatch: Twitch sign-in is working again"]
    assert n.handle("state", {"state": "mining"}) == []


def test_unreachable_waits_for_the_configured_minutes(tmp_path):
    n, clock, _ = make(tmp_path, notify_unreachable_minutes=20)
    n.handle("state", {"state": "twitch_unreachable", "error": "ClientError: x"})
    clock[0] += timedelta(minutes=19)
    n.handle("state", {"state": "twitch_unreachable", "error": "ClientError: x"})  # each failed retry
    assert n.check(SNAP) == []
    clock[0] += timedelta(minutes=1)
    (a,) = n.check(SNAP)
    assert a.title == "Dropwatch: Can't reach Twitch" and "20 minutes" in a.body
    assert n.check(SNAP) == []
    assert titles(n.handle("state", {"state": "mining"})) == ["Dropwatch: Twitch is reachable again"]


def test_a_short_outage_says_nothing(tmp_path):
    n, clock, _ = make(tmp_path)
    n.handle("state", {"state": "twitch_unreachable"})
    clock[0] += timedelta(minutes=5)
    assert n.handle("state", {"state": "mining"}) == [] and n.check(SNAP) == []


def test_not_earning_counts_from_mining_start_or_the_last_progress(tmp_path):
    n, clock, _ = make(tmp_path)  # default 30 min
    n.handle("state", {"state": "mining"})
    clock[0] += timedelta(minutes=20)
    n.handle("progress", {"drop": "d1", "minutes": 5})
    clock[0] += timedelta(minutes=29)
    assert n.check(SNAP) == []
    clock[0] += timedelta(minutes=1)
    (a,) = n.check(SNAP)
    assert a.title == "Dropwatch: Mining isn't earning"
    assert a.body == ("Watched honeyxxo for 30 minutes with no new minutes on EXFIL Brothers Day 2. "
                      "Twitch may have changed something.")
    assert n.check(SNAP) == []
    again = n.handle("progress", {"drop": "d1", "minutes": 6})
    assert titles(again) == ["Dropwatch: Mining is earning again"]


def test_not_earning_stops_counting_while_paused_or_idle(tmp_path):
    n, clock, _ = make(tmp_path)
    n.handle("state", {"state": "mining"})
    clock[0] += timedelta(minutes=25)
    n.handle("state", {"state": "paused"})
    clock[0] += timedelta(hours=2)
    n.handle("state", {"state": "mining"})
    clock[0] += timedelta(minutes=10)
    assert n.check(SNAP) == []


def test_a_failed_claim_alerts_once_and_says_when_it_went_through(tmp_path):
    n, _, _ = make(tmp_path)
    info = {"campaign": "CFB Live", "reward": "CFB Twitch Pack"}
    (a,) = n.handle("claim_failed", info)
    assert a.title == "Dropwatch: A reward couldn't be claimed"
    assert a.body == "CFB Twitch Pack from CFB Live. Dropwatch will try again."
    assert n.handle("claim_failed", info) == []  # retried every refresh: no repeat
    assert titles(n.handle("claimed", info)) == ["Dropwatch: Claimed after all"]


def test_a_crash_alerts_and_mining_again_clears_it(tmp_path):
    n, _, _ = make(tmp_path)
    (a,) = n.handle("state", {"state": "idle", "error": "KeyError"})
    assert a.title == "Dropwatch: Mining stopped on an error"
    assert a.body == "KeyError. Restart Dropwatch to start mining again."
    assert titles(n.handle("state", {"state": "mining"})) == ["Dropwatch: Mining is running again"]


def test_switched_off_alerts_stay_silent_and_never_send_a_recovery(tmp_path):
    n, _, _ = make(tmp_path, notify_signin=False, notify_stopped=False)
    assert n.handle("state", {"state": "signed_out"}) == []
    assert n.handle("state", {"state": "idle", "error": "KeyError"}) == []
    assert n.handle("state", {"state": "mining"}) == []


def test_needs_you_is_off_by_default_then_batches_and_remembers(tmp_path):
    n, _, st = make(tmp_path)
    many = Snapshot(None, None, [("c1", "ER ESPORTS DROPS", "Eternal Return"),
                                 ("c2", "Mobile Drop 183", "Pokemon")])
    assert n.check(many) == []  # off by default
    st.put_settings({"notify_needs_you": True})
    (a,) = n.check(many)
    assert a.title == "Dropwatch: 2 campaigns need your account linked"
    assert a.body == "ER ESPORTS DROPS (Eternal Return), Mobile Drop 183 (Pokemon)"
    assert n.check(many) == []
    n2 = Notifier(st, clock=lambda: NOW)  # a restart doesn't repeat them
    assert n2.check(many) == []
    (one,) = n2.check(Snapshot(None, None, [*many.needs_you, ("c3", "Oct Wk 1", "MapleStory")]))
    assert one.title == "Dropwatch: Oct Wk 1 needs your account linked"
    assert one.body == "MapleStory: link your account to mine it."


async def test_the_runner_announces_a_failed_claim_with_its_reward(tmp_path):
    from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

    from dropwatch.runner import Runner

    class Refuses(FakeClient):
        async def claim(self, claim_id):
            return None

    emitted = []
    r = Runner(Refuses([camp(cur=60, claim_id="inst")], [chan("a", 7)]), FakeWatcher(), FakePubSub(),
               Store(tmp_path / "d.db"), user_id=42, clock=lambda: NOW,
               emit=lambda k, d: emitted.append((k, d)))
    await r.refresh()
    assert ("claim_failed", {"campaign": "Frights", "reward": "Palcat Glasses"}) in emitted


async def test_snapshot_reads_the_campaign_channel_and_needs_you(tmp_path):
    from dataclasses import replace

    from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

    from dropwatch.alerts import snapshot_of
    from dropwatch.runner import Runner

    unlinked = replace(camp(), id="c2", name="Mobile Drop", linked=False)
    r = Runner(FakeClient([camp(), unlinked], [chan("a", 7)]), FakeWatcher(), FakePubSub(),
               Store(tmp_path / "d.db"), user_id=42, clock=lambda: NOW)
    assert snapshot_of(None) == Snapshot(None, None, [])
    await r.refresh()
    assert snapshot_of(r) == Snapshot("Frights", "a", [("c2", "Mobile Drop", "Palia")])


async def test_run_sends_from_bus_events_and_survives_a_send_that_raises(tmp_path):
    import asyncio

    from dropwatch.events import EventBus

    n, _, _ = make(tmp_path)
    bus, sent = EventBus(), []

    async def send(title, body):
        sent.append(title)
        if len(sent) == 1:
            raise RuntimeError("boom")  # must not end the notifier
        return [{"name": "ntfy", "message": "sent"}]

    task = asyncio.create_task(n.run(bus, lambda: Snapshot(None, None, []), send))
    await asyncio.sleep(0)
    bus.publish("state", {"state": "signed_out"})
    await asyncio.sleep(0.05)
    bus.publish("state", {"state": "mining"})
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    assert sent == ["Dropwatch: Twitch sign-in stopped working", "Dropwatch: Twitch sign-in is working again"]
