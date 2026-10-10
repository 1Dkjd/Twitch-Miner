"""Notifications: the weekly summary and "a reward is claimed", both off by default (approved in
docs/design/next-features-mockup.html, 2026-10-10)."""
from datetime import UTC, datetime, timedelta

from dropwatch.alerts import Notifier, Snapshot
from dropwatch.store import Store

SUN_1801 = datetime(2026, 10, 11, 18, 1, tzinfo=UTC)  # a Sunday
NONE = Snapshot(None, None, [])


def make(tmp_path, at, **settings):
    st = Store(tmp_path / "d.db")
    st.put_settings(settings)
    clock = [at]
    return Notifier(st, clock=lambda: clock[0], tz=UTC), clock, st


def test_defaults_are_off(tmp_path):
    s = Store(tmp_path / "d.db").get_settings()
    assert (s["notify_claimed"], s["notify_weekly"]) == (False, False)
    assert (s["notify_weekly_day"], s["notify_weekly_hour"]) == (6, 18)  # Sunday 18:00


def test_claims_within_a_minute_arrive_as_one_message(tmp_path):
    n, clock, _ = make(tmp_path, SUN_1801, notify_claimed=True)
    info = {"campaign": "EXFIL Brothers Day 2", "game": "Escape from Tarkov", "minutes": 240,
            "channel": "honeyxxo"}
    assert n.handle("claimed", {**info, "reward": "Rare 2"}) == []  # held for a minute
    clock[0] += timedelta(seconds=20)
    assert n.handle("claimed", {**info, "reward": "Common 3"}) == [] and n.check(NONE) == []
    clock[0] += timedelta(seconds=45)
    (a,) = n.check(NONE)
    assert a.title == "Dropwatch: Claimed 2 rewards"
    assert a.body == "Rare 2 and Common 3 from EXFIL Brothers Day 2 (Escape from Tarkov)."
    assert n.check(NONE) == []
    n.handle("claimed", {**info, "reward": "Legendary 1"})
    clock[0] += timedelta(minutes=1)
    (one,) = n.check(NONE)
    assert one.title == "Dropwatch: Claimed Legendary 1"
    assert one.body == "EXFIL Brothers Day 2 (Escape from Tarkov), after 4 h watched on honeyxxo."


def test_claimed_is_silent_when_off(tmp_path):
    n, clock, _ = make(tmp_path, SUN_1801)
    n.handle("claimed", {"campaign": "X", "game": "Y", "reward": "Z"})
    clock[0] += timedelta(minutes=2)
    assert n.check(NONE) == []


def test_weekly_summary_once_at_the_chosen_time(tmp_path):
    n, clock, st = make(tmp_path, SUN_1801 - timedelta(minutes=2), notify_weekly=True)
    st.add_claim(SUN_1801 - timedelta(days=2), "c1", "EXFIL", "Escape from Tarkov",
                 [("Rare 1", ""), ("Rare 2", "")])
    st.add_claim(SUN_1801 - timedelta(days=9), "c0", "Old", "Old game", [("Old", "")])  # before the week
    needs = Snapshot(None, None, [("d", "DbD: October of Horror", "Dead by Daylight"),
                                  ("e", "Extended Operations", "007 First Light")])
    assert n.check(needs) == []  # 17:59
    clock[0] = SUN_1801
    (a,) = n.check(needs)
    assert a.title == "Dropwatch: Your week"
    assert a.body == ("2 rewards claimed from 1 campaign. "
                      "2 need your account linked: Dead by Daylight, 007 First Light.")
    clock[0] += timedelta(hours=3)
    assert n.check(needs) == []  # once a week
    assert Notifier(st, clock=lambda: clock[0], tz=UTC).check(needs) == []  # a restart doesn't repeat it
    clock[0] += timedelta(days=7)
    assert n.check(NONE)[0].body == "A quiet week: nothing claimed."


def test_weekly_summary_counts_missed_campaigns_that_mattered(tmp_path):
    n, clock, st = make(tmp_path, SUN_1801, notify_weekly=True)
    st.log_campaigns(SUN_1801 - timedelta(days=3), [{
        "id": "er", "name": "ER ESPORTS DROPS", "game": "Eternal Return", "box_art_url": "", "link_url": "",
        "ends_at": SUN_1801 - timedelta(days=3) + timedelta(minutes=5), "linked": False, "badge": False,
        "rewards": [{"name": "Token", "image_url": "", "claimed": False}], "impossible": False,
        "never": False, "priority": False, "pinned": False, "live": True, "watched": 60}])
    (a,) = n.check(NONE)
    assert a.body == "Nothing claimed. 1 campaign missed (History says why)."
