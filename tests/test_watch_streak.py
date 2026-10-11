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
    # review fix: no drop minutes during a visit must not look like "this campaign isn't earning" (link test).
    # An unknown-link campaign and more than LINK_PROBE_TICKS ticks, so the test fails without the guard.
    from dataclasses import replace

    from dropwatch.runner import LINK_PROBE_TICKS
    r, c, st, t = make(tmp_path, [chan("a", 7), fav()])
    c.camps = [replace(camp(), linked=None)]

    async def no_drop_here(channel_id):  # the favourite has no drops: nothing progresses
        return None
    c.current_drop = no_drop_here
    await r.refresh()
    assert r.watching.login == "favchan"
    for _ in range(LINK_PROBE_TICKS + 1):  # 1 s apart: all inside the visit, no refresh (which adds minutes)
        t[0] += timedelta(seconds=1)
        await r.tick()
    assert r.watching.login == "favchan"
    assert not r.maybe_unlinked


async def test_the_visit_ends_on_time_between_refreshes(tmp_path):
    # review fix: it ended only at a refresh (so ~10 min, or never while Twitch was unreachable)
    r, c, st, t = make(tmp_path, [chan("a", 7), fav()])
    await r.refresh()
    t[0] += timedelta(minutes=5)
    await r.tick()  # refresh due: still visiting
    assert r.watching.login == "favchan"
    t[0] += STREAK_VISIT - timedelta(minutes=5) + timedelta(seconds=10)
    await r.tick()  # no refresh due, but the visit is over
    assert r.watching.login == "a"


async def test_picking_a_channel_or_mine_now_ends_the_visit(tmp_path):
    r, c, st, t = make(tmp_path, [chan("a", 7), fav()])
    await r.refresh()
    assert r.watching.login == "favchan"
    r.use_channel("a")
    await r.replan()
    assert r.watching.login == "a"
    t[0] += timedelta(minutes=5)
    await r.refresh()
    assert r.watching.login == "a"  # and not visited again


async def test_visited_streams_are_remembered_across_restarts(tmp_path):
    r, c, st, t = make(tmp_path, [chan("a", 7), fav()])
    await r.refresh()
    t[0] += STREAK_VISIT + timedelta(minutes=1)
    await r.refresh()
    again = Runner(FakeClient([camp()], [chan("a", 7), fav()]), FakeWatcher(), FakePubSub(), st, user_id=42,
                   clock=lambda: t[0])
    await again.refresh()
    assert again.watching.login == "a"


async def test_the_page_is_told_about_the_visit(tmp_path):
    from dropwatch.api.views import state_view
    r, c, st, t = make(tmp_path, [chan("a", 7), fav()])
    await r.refresh()
    v = state_view(r, st, t[0]).streak_visit
    assert v.channel == "favchan" and v.until == t[0] + STREAK_VISIT
    t[0] += STREAK_VISIT + timedelta(minutes=1)
    await r.refresh()
    assert state_view(r, st, t[0]).streak_visit is None


def test_points_earned_is_read_from_pubsub():
    msg = {"type": "points-earned", "data": {"channel_id": "9", "point_gain": {
        "channel_id": "9", "total_points": 350, "reason_code": "WATCH_STREAK"}}}
    assert parse_message("community-points-user-v1.42", msg) == PointsEarned(9, "WATCH_STREAK", 350)


async def test_back_to_drops_now_from_the_page(tmp_path):
    from apihelpers import logged_in, make_app
    r, c, st, t = make(tmp_path / "r", [chan("a", 7), fav()])
    await r.refresh()
    app, ctx = make_app(tmp_path / "app", runner=r)
    client = await logged_in(app)
    assert (await client.post("/api/streak/end")).status_code == 204
    assert r.watching.login == "a" and r.streak_visit is None
    await client.aclose()
