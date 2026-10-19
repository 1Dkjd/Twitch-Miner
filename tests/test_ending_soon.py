"""Ending soon (2026-10-18): a started reward whose window closes within N hours, while it can finish."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from test_runner import NOW, FakeClient, FakePubSub, FakeStore, FakeWatcher, camp

from dropwatch.alerts import Notifier, Snapshot, _started
from dropwatch.runner import Runner
from dropwatch.store import Store

T = datetime(2026, 10, 18, 12, tzinfo=UTC)
IMG = "https://static-cdn.jtvnw.net/x.png"


def notifier(tmp_path, **settings):
    st = Store(tmp_path / "d.db")
    st.put_settings(settings)
    clock = [T]
    return Notifier(st, clock=lambda: clock[0], tz=UTC), clock


def snap(*started):
    return Snapshot(None, None, [], started=list(started))


def test_said_once_per_reward_inside_the_window(tmp_path):
    n, clock = notifier(tmp_path, notify_ending_hours=6)
    far = ("d1", "Cyclops Costume", "Marvel Rivals", 20, T + timedelta(hours=9), IMG)
    assert n.check(snap(far)) == []  # 9 h away: outside the 6 h window
    clock[0] += timedelta(hours=4)  # now 5 h away
    (a,) = n.check(snap(far))
    assert a.title == "Dropwatch: Ending soon: Cyclops Costume"
    assert a.body == "Cyclops Costume (Marvel Rivals): 20 min to go, ends in 5 h."
    assert a.image == IMG
    assert n.check(snap(far)) == []  # once
    again = Notifier(n._store, clock=lambda: clock[0], tz=UTC)
    assert again.check(snap(far)) == []  # not again after a restart


def test_several_at_once_arrive_as_one_message(tmp_path):
    n, _ = notifier(tmp_path)
    a = ("d1", "Hat", "Palia", 30, T + timedelta(hours=2), "")
    b = ("d2", "Mug", "Rust", 90, T + timedelta(minutes=50), "")
    (msg,) = n.check(snap(a, b))
    assert msg.title == "Dropwatch: Ending soon: 2 rewards"
    assert msg.body.startswith("Mug (Rust): 1 h 30 min to go, ends in 50 min. Hat (Palia)")


def test_off_means_silent(tmp_path):
    n, _ = notifier(tmp_path, notify_ending_soon=False)
    assert n.check(snap(("d1", "Hat", "Palia", 30, T + timedelta(hours=1), ""))) == []


def test_only_started_rewards_that_can_still_finish_are_candidates():
    started = replace(camp(cur=20), id="s")                    # 40 of 60 to go, days left: candidate
    untouched = replace(camp(cur=0), id="u")                   # nothing watched yet
    c = camp(cur=10)
    hopeless = replace(c, id="h", ends_at=NOW + timedelta(minutes=30),
                       drops=(replace(c.drops[0], ends_at=NOW + timedelta(minutes=30)),))  # 50 to go, 30 left
    r = Runner(FakeClient([started, untouched, hopeless], []), FakeWatcher(), FakePubSub(), FakeStore(),
               user_id=42, clock=lambda: NOW)
    r.campaigns = [started, untouched, hopeless]
    got = _started(r, NOW)
    assert [(x[0], x[3]) for x in got] == [("d1", 40)]
    assert got[0][1] == "Palcat Glasses" and got[0][2] == "Palia"
