import math
from datetime import timedelta

from dropwatch.models import (
    Campaign,
    Drop,
    Game,
    Reward,
    campaign_active,
    campaign_minutes_needed,
    campaign_ratio,
    claimable,
    deadline_verdict,
    drop_earnable_now,
    drop_open,
    preconditions_met,
    total_remaining,
    with_drop,
)

G = Game(id=1, name="Palia", slug="palia")
R = Reward(id="r1", name="10x Ectoplasm", image_url="", kind="DIRECT_ENTITLEMENT")


def drop(id, now, *, req=60, cur=0, claimed=False, pre=(), start=-1, end=96, rewards=(R,), claim_id=None):
    return Drop(id=id, name=id, rewards=rewards, starts_at=now + timedelta(hours=start),
                ends_at=now + timedelta(hours=end), required_minutes=req, current_minutes=cur,
                claimed=claimed, claim_id=claim_id, preconditions=pre)


def camp(now, *drops, start=-24, end=96, linked=True):
    return Campaign(id="c1", name="Frights", game=G, starts_at=now + timedelta(hours=start),
                    ends_at=now + timedelta(hours=end), linked=linked, link_url="",
                    allowed_logins=(), drops=tuple(drops))


def test_simple_remaining_and_ratio(now):
    c = camp(now, drop("a", now, req=60, cur=22, end=4))
    assert campaign_minutes_needed(c, now) == 38
    assert campaign_ratio(c, now) == (4 * 60) / 38


def test_precondition_chain_blocks_until_claimed(now):
    a = drop("a", now, req=60, cur=10)
    b = drop("b", now, req=120, pre=("a",))
    c = camp(now, a, b)
    assert not preconditions_met(c, b)
    assert not drop_earnable_now(c, b, now)
    assert drop_earnable_now(c, a, now)


def test_precondition_chain_adds_remaining_minutes(now):
    a = drop("a", now, req=60, cur=10)
    b = drop("b", now, req=120, pre=("a",))
    c = camp(now, a, b)
    assert total_remaining(c, b) == 120 + 50
    assert campaign_minutes_needed(c, now) == 170


def test_drop_window_not_started_is_open_but_not_earnable_now(now):
    later = drop("a", now, start=2, end=50)
    c = camp(now, later)
    assert drop_open(c, later, now)
    assert not drop_earnable_now(c, later, now)


def test_drop_window_ended_is_closed(now):
    gone = drop("a", now, start=-48, end=-1)
    c = camp(now, gone)
    assert not drop_open(c, gone, now)
    assert campaign_minutes_needed(c, now) == 0
    assert math.isinf(campaign_ratio(c, now))


def test_zero_required_minutes(now):
    z = drop("a", now, req=0)
    c = camp(now, z)
    assert not drop_open(c, z, now)
    assert campaign_minutes_needed(c, now) == 0
    assert math.isinf(campaign_ratio(c, now))


def test_overshoot_clamped(now):
    o = drop("a", now, req=60, cur=75)
    c = camp(now, o)
    assert total_remaining(c, o) == 0


def test_claimed_drop_is_not_open(now):
    d = drop("a", now, claimed=True)
    assert not drop_open(camp(now, d), d, now)


def test_drop_without_rewards_only_counts_inside_a_chain(now):
    bare = drop("a", now, rewards=())
    assert not drop_open(camp(now, bare), bare, now)
    child = drop("b", now, pre=("a",))
    assert drop_open(camp(now, bare, child), bare, now)


def test_campaign_active(now):
    assert campaign_active(camp(now, drop("a", now)), now)
    assert not campaign_active(camp(now, drop("a", now), start=1), now)
    assert not campaign_active(camp(now, drop("a", now), end=-1), now)


def test_claimable_within_grace(now):
    d = drop("a", now, cur=60, claim_id="inst-1")
    ended = camp(now, d, end=-23)
    assert claimable(ended, d, now)
    expired = camp(now, d, end=-25)
    assert not claimable(expired, d, now)
    assert not claimable(ended, drop("b", now, claim_id=None), now)


def test_deadline_verdict_thresholds():
    assert deadline_verdict(0.9) == "wont_finish"
    assert deadline_verdict(1.0) == "tight"
    assert deadline_verdict(1.99) == "tight"
    assert deadline_verdict(2.0) == "plenty"
    assert deadline_verdict(math.inf) == "plenty"


def test_with_drop_replaces_by_id(now):
    c = camp(now, drop("a", now, cur=1), drop("b", now))
    c2 = with_drop(c, drop("a", now, cur=5))
    assert c2.drop("a").current_minutes == 5
    assert c2.drop("b") == c.drop("b")


def test_game_slug_matches_reference_rule():
    from dropwatch.models import game_slug
    assert game_slug("Marvel Rivals") == "marvel-rivals"
    assert game_slug("Tom Clancy's Rainbow Six Siege") == "tom-clancys-rainbow-six-siege"
    assert game_slug("Out of the Park Baseball 27") == "out-of-the-park-baseball-27"
    assert game_slug("  Dead by Daylight  ") == "dead-by-daylight"
    assert game_slug("Pokémon UNITE") == "pokémon-unite"  # reference keeps unicode word chars
