"""2026-10-18: sign-in alerts that say how to sign in again, the lost-campaign-list alert, and the week ahead
in the weekly summary."""
from datetime import UTC, datetime, timedelta

from dropwatch.alerts import Notifier, Snapshot
from dropwatch.store import Store
from dropwatch.twitch.constants import ANDROID_APP, SMARTBOX
from dropwatch.twitch.session import TwitchSession

SUN_1801 = datetime(2026, 10, 11, 18, 1, tzinfo=UTC)


def make(tmp_path, client_id=None, **settings):
    st = Store(tmp_path / "d.db")
    st.put_settings(settings)
    if client_id:
        st.set_session(TwitchSession("t", 1, "dk", "d", client_id, "s"))
    clock = [SUN_1801]
    return Notifier(st, clock=lambda: clock[0], tz=UTC), clock, st


def test_sign_out_advice_matches_the_kind_of_sign_in(tmp_path):
    n, _, _ = make(tmp_path / "a", ANDROID_APP.client_id)
    (a,) = n.handle("state", {"state": "signed_out"})
    assert "sign in again on Twitch's page" in a.body
    n, _, _ = make(tmp_path / "b", SMARTBOX.client_id)
    (b,) = n.handle("state", {"state": "signed_out"})
    assert "new sign-in code" in b.body and "Twitch's page" not in b.body


def test_losing_the_full_list_is_said_once_and_cleared(tmp_path):
    n, _, _ = make(tmp_path, ANDROID_APP.client_id)
    lost = Snapshot(None, None, [], list_lost=True)
    (a,) = n.check(lost)
    assert a.title == "Dropwatch: Twitch stopped sending the full campaign list"
    assert "Twitch's page" in a.body
    assert n.check(lost) == []
    (back,) = n.check(Snapshot(None, None, []))
    assert back.title == "Dropwatch: Twitch is sending the full campaign list again"
    assert n.check(Snapshot(None, None, [])) == []


def test_the_week_ahead_lists_priority_first_and_what_to_link(tmp_path):
    n, _, st = make(tmp_path, notify_weekly=True)
    st.set_lists(["WARDOGS"], {"Rust"}, [])
    up = [("Apex Legends", "Split 2", SUN_1801 + timedelta(days=2), True),
          ("WARDOGS", "Season 02", SUN_1801 + timedelta(days=5), False),
          ("WARDOGS", "Season 02 week 2", SUN_1801 + timedelta(days=6), False),
          ("Rust", "Rust S9", SUN_1801 + timedelta(days=1), False),        # Never: left out
          ("Later game", "Far off", SUN_1801 + timedelta(days=20), None)]  # beyond the week
    (a,) = n.check(Snapshot(None, None, [], upcoming=up))
    assert "Starting this week: WARDOGS (Priority) on Fri 16 Oct, Apex Legends on Tue 13 Oct." in a.body
    assert "Link before they start: WARDOGS." in a.body
    assert "Rust" not in a.body and "Later game" not in a.body
