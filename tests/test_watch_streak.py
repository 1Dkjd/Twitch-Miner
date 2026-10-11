"""Watch streaks (asked for 2026-10-11): Twitch pays bonus points for watching consecutive streams of a
channel. When a favourite starts a new stream, watch it for a few minutes first, then go back to drops."""
from datetime import timedelta

from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.models import LiveChannel
from dropwatch.runner import STREAK_VISIT, Runner
from dropwatch.store import Store
from dropwatch.twitch.pubsub import PointsEarned, parse_message


def fav(broadcast="bfav1"):
    return LiveChannel(9, "favchan", 999, 50, True, broadcast, "Just Chatting")


def make(tmp_path, live, streak=True, points=True):
    st = Store(tmp_path / "d.db")
    st.put_settings({"points_watch_streak": streak, "claim_points": points})
    st.set_lists([], set(), ["favchan"])
    t = [NOW]
    c = FakeClient([camp()], live)
    return Runner(c, FakeWatcher(), FakePubSub(), st, user_id=42, clock=lambda: t[0]), c, st, t


async def test_a_new_stream_of_a_favourite_gets_a_short_visit_then_drops_resume(tmp_path):
    r, c, st, t = make(tmp_path, [chan("a", 7), fav()])
    await r.refresh()
    assert r.watching.login == "favchan"  # its streak first
    t[0] += STREAK_VISIT + timedelta(minutes=1)
    await r.refresh()
    assert r.watching.login == "a"  # back to the drop channel
    t[0] += timedelta(minutes=30)
    await r.refresh()
    assert r.watching.login == "a"  # same stream: not visited again
    c.live = [chan("a", 7), fav("bfav2")]  # its next stream
    t[0] += timedelta(minutes=5)
    await r.refresh()
    assert r.watching.login == "favchan"
    switches = [d for k, _, d in st.recent_events(50) if k == "switched"]
    assert switches[0]["reason"] == "watch streak"


async def test_no_visits_when_switched_off_or_points_off(tmp_path):
    for i, kw in enumerate(({"streak": False}, {"points": False})):
        r, *_ = make(tmp_path / f"case{i}", [chan("a", 7), fav()], **kw)
        await r.refresh()
        assert r.watching.login == "a", kw


async def test_the_streak_bonus_arriving_ends_the_visit_early(tmp_path):
    r, c, st, t = make(tmp_path, [chan("a", 7), fav()])
    await r.refresh()
    assert r.watching.login == "favchan"
    await r.handle(PointsEarned(9, "WATCH_STREAK", 350))
    assert r.watching.login == "a"
    earned = [d for k, _, d in st.recent_events(50) if k == "points_earned"]
    assert earned == [{"channel": "favchan", "reason": "WATCH_STREAK", "points": 350}]


async def test_a_visit_does_not_count_against_the_drop_campaign(tmp_path):
    # no drop minutes during a visit must not look like "this campaign isn't earning" (link test)
    r, c, st, t = make(tmp_path, [chan("a", 7), fav()])
    await r.refresh()
    for _ in range(10):
        t[0] += timedelta(seconds=60)
        await r.tick()
    assert not r.maybe_unlinked


def test_points_earned_is_read_from_pubsub():
    msg = {"type": "points-earned", "data": {"channel_id": "9", "point_gain": {
        "channel_id": "9", "total_points": 350, "reason_code": "WATCH_STREAK"}}}
    assert parse_message("community-points-user-v1.42", msg) == PointsEarned(9, "WATCH_STREAK", 350)
