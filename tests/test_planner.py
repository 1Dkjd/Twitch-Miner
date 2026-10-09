from datetime import timedelta

from dropsminer.models import Campaign, Drop, Game, LiveChannel, Prefs, Reward
from dropsminer.planner import plan

PALIA = Game(1, "Palia", "palia")
PHAS = Game(2, "Phasmophobia", "phasmophobia")
SPECIAL = Game(509663, "Special Events", "special-events")
R = Reward("r", "Reward", "", "DIRECT_ENTITLEMENT")
BADGE = Reward("b", "Badge", "", "BADGE")


def mk(now, cid, game, *, need=60, cur=0, end_h=96, linked=True, allowed=(), rewards=(R,), claimed=False):
    d = Drop(f"{cid}-d", "d", rewards, now - timedelta(days=1), now + timedelta(hours=end_h),
             need, cur, claimed, None)
    return Campaign(cid, cid, game, now - timedelta(days=1), now + timedelta(hours=end_h),
                    linked, "https://link", tuple(allowed), (d,))


def ch(login, game, viewers=100, drops=True, cid=None):
    return LiveChannel(id=hash(login) % 10_000, login=login, game_id=game.id if game else None,
                       viewers=viewers, drops_enabled=drops, broadcast_id="b-" + login)


def test_priority_beats_urgency(now):
    urgent = mk(now, "phas", PHAS, end_h=2)
    relaxed = mk(now, "palia", PALIA, end_h=200)
    p = plan([urgent, relaxed], [ch("a", PALIA), ch("b", PHAS)], Prefs(priority=("Palia",)), now)
    assert p.current.campaign_id == "palia"
    assert p.current.reason == "priority 1"
    assert p.queue == ("phas",)


def test_unlisted_games_ordered_by_spare_time(now):
    tight = mk(now, "tight", PHAS, need=100, end_h=3)       # 180/100 = 1.8
    loose = mk(now, "loose", PALIA, need=30, end_h=3)       # 180/30 = 6
    p = plan([loose, tight], [ch("a", PALIA), ch("b", PHAS)], Prefs(), now)
    assert p.current.campaign_id == "tight"
    assert p.current.reason == "most urgent"


def test_never_beats_priority(now):
    c = mk(now, "palia", PALIA)
    p = plan([c], [ch("a", PALIA)], Prefs(priority=("Palia",), never=frozenset({"Palia"})), now)
    assert p.current is None
    assert "palia" not in p.needs_you and "palia" not in p.done


def test_unlinked_goes_to_needs_you(now):
    c = mk(now, "bond", PALIA, linked=False)
    p = plan([c], [ch("a", PALIA)], Prefs(), now)
    assert p.current is None
    assert p.needs_you == ("bond",)


def test_badge_campaign_not_in_needs_you_and_skipped_by_default(now):
    c = mk(now, "badge", PALIA, linked=False, rewards=(BADGE,))
    p = plan([c], [ch("a", PALIA)], Prefs(), now)
    assert p.current is None
    assert p.needs_you == ()


def test_badge_campaign_mined_when_enabled(now):
    c = mk(now, "badge", PALIA, linked=False, rewards=(BADGE,))
    p = plan([c], [ch("a", PALIA)], Prefs(mine_badges=True), now)
    assert p.current.campaign_id == "badge"


def test_allowed_channels_only(now):
    c = mk(now, "dnd", PALIA, allowed=("dnd",))
    p = plan([c], [ch("random", PALIA, viewers=9999)], Prefs(), now)
    assert p.current is None
    p2 = plan([c], [ch("random", PALIA, viewers=9999), ch("dnd", PALIA, viewers=1)], Prefs(), now)
    assert p2.current.channel_login == "dnd"
    assert p2.current.channel_reason == "allowed channel"


def test_allowed_channel_must_stream_the_game(now):
    c = mk(now, "dnd", PALIA, allowed=("dnd",))
    p = plan([c], [ch("dnd", PHAS)], Prefs(), now)
    assert p.current is None


def test_special_game_any_channel(now):
    c = mk(now, "sp", SPECIAL)
    p = plan([c], [ch("x", PHAS)], Prefs(), now)
    assert p.current.campaign_id == "sp"


def test_drops_disabled_channel_does_not_qualify(now):
    c = mk(now, "palia", PALIA)
    p = plan([c], [ch("a", PALIA, drops=False)], Prefs(), now)
    assert p.current is None


def test_channel_tiers_favourite_then_allowed_then_viewers(now):
    c = mk(now, "palia", PALIA, allowed=("allowed1", "fav2"))
    live = [ch("big", PALIA, 5000), ch("allowed1", PALIA, 10), ch("fav2", PALIA, 1)]
    # with an allowed list, only allowed channels qualify; favourite wins among them
    p = plan([c], live, Prefs(favourites=("fav1", "fav2")), now)
    assert (p.current.channel_login, p.current.channel_reason) == ("fav2", "favourite")
    open_c = mk(now, "open", PALIA)
    p2 = plan([open_c], live, Prefs(), now)
    assert (p2.current.channel_login, p2.current.channel_reason) == ("big", "any channel")


def test_stickiness_keeps_current_channel(now):
    c = mk(now, "palia", PALIA)
    live = [ch("bigger", PALIA, 900), ch("current", PALIA, 100)]
    p = plan([c], live, Prefs(), now, watching="current")
    assert (p.current.channel_login, p.current.channel_reason) == ("current", "already watching")


def test_favourite_coming_online_breaks_stickiness(now):
    c = mk(now, "palia", PALIA)
    live = [ch("current", PALIA, 900), ch("fav", PALIA, 5)]
    p = plan([c], live, Prefs(favourites=("fav",)), now, watching="current")
    assert p.current.channel_login == "fav"


def test_overrides(now):
    a = mk(now, "a", PALIA)
    b = mk(now, "b", PHAS)
    live = [ch("pa", PALIA), ch("ph1", PHAS, 50), ch("ph2", PHAS, 10)]
    p = plan([a, b], live, Prefs(priority=("Palia",)), now, override_campaign="b",
             override_channel="ph2")
    assert (p.current.campaign_id, p.current.channel_login) == ("b", "ph2")
    assert p.current.reason == "you picked it"
    # an override that is no longer eligible is ignored
    p2 = plan([a, b], live, Prefs(priority=("Palia",)), now, override_campaign="gone")
    assert p2.current.campaign_id == "a"


def test_done_and_verdicts(now):
    finished = mk(now, "fin", PALIA, claimed=True)
    tight = mk(now, "tight", PHAS, need=100, end_h=3)
    p = plan([finished, tight], [ch("b", PHAS)], Prefs(), now)
    assert p.done == ("fin",)
    assert p.verdicts["tight"] == "tight"
    assert "fin" not in p.verdicts


def test_also_credited_same_game_same_channel(now):
    a = mk(now, "a", PALIA, end_h=5)
    b = mk(now, "b", PALIA, end_h=50)
    p = plan([a, b], [ch("x", PALIA)], Prefs(), now)
    assert p.current.campaign_id == "a"
    assert p.also_credited == ("b",)


def test_ties_are_deterministic(now):
    a = mk(now, "a", PALIA)
    b = mk(now, "b", PHAS)
    live = [ch("x", PALIA), ch("y", PHAS)]
    assert plan([b, a], live, Prefs(), now).current.campaign_id == "a"
    assert plan([a, b], live, Prefs(), now).current.campaign_id == "a"


def test_unlinked_campaign_with_nothing_left_is_not_needs_you(now):
    c = mk(now, "old", PALIA, linked=False, claimed=True)
    assert plan([c], [ch("a", PALIA)], Prefs(), now).needs_you == ()


def test_partly_claimed_campaign_is_not_done(now):
    d1 = Drop("p-1", "d", (R,), now - timedelta(days=1), now + timedelta(days=4), 60, 60, True, None)
    d2 = Drop("p-2", "d", (R,), now - timedelta(days=1), now + timedelta(days=4), 120, 60, False, None)
    c = Campaign("p", "p", PALIA, now - timedelta(days=1), now + timedelta(days=4), True, "", (), (d1, d2))
    p = plan([c], [ch("a", PALIA)], Prefs(), now)
    assert p.done == ()
    assert p.current.campaign_id == "p"


def test_drop_not_started_is_not_mined_yet(now):
    later = Drop("l-1", "d", (R,), now + timedelta(hours=2), now + timedelta(days=4), 60, 0, False, None)
    c = Campaign("l", "l", PALIA, now - timedelta(days=1), now + timedelta(days=4), True, "", (), (later,))
    assert plan([c], [ch("a", PALIA)], Prefs(), now).current is None


def test_favourite_list_order_decides_between_live_favourites(now):
    c = mk(now, "palia", PALIA)
    live = [ch("second", PALIA, 900), ch("first", PALIA, 5)]
    p = plan([c], live, Prefs(favourites=("first", "second")), now)
    assert p.current.channel_login == "first"


def test_inactive_campaigns_are_ignored(now):
    past, gone = now - timedelta(days=9), now - timedelta(hours=1)
    soon, later = now + timedelta(days=1), now + timedelta(days=9)
    ended = Campaign("e", "e", PALIA, past, gone, True, "", (),
                     (Drop("e-1", "d", (R,), past, gone, 60, 60, True, None),))
    upcoming = Campaign("u", "u", PHAS, soon, later, False, "", (),
                        (Drop("u-1", "d", (R,), soon, later, 60, 0, False, None),))
    p = plan([ended, upcoming], [ch("a", PALIA)], Prefs(), now)
    assert p.done == ()
    assert p.needs_you == ()
