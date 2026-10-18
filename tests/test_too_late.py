"""Skip campaigns that can't finish in time (2026-10-18): no reward left fits its window, watched non-stop."""
from dataclasses import replace
from datetime import timedelta

from test_runner import NOW, camp, chan

from dropwatch.models import Drop, Prefs, campaign_finishable, drop_finishable
from dropwatch.planner import plan


def ending_in(minutes, need=60, done=0, cid="c1"):
    c = camp(cur=done)
    d = replace(c.drops[0], required_minutes=need, ends_at=NOW + timedelta(minutes=minutes))
    return replace(c, id=cid, drops=(d,), ends_at=NOW + timedelta(minutes=minutes))


def test_a_drop_needing_more_than_the_time_left_is_not_finishable():
    assert drop_finishable(ending_in(90, need=60), ending_in(90, need=60).drops[0], NOW)
    c = ending_in(30, need=60, done=10)  # 50 min to go, 30 left
    assert not drop_finishable(c, c.drops[0], NOW) and not campaign_finishable(c, NOW)
    c = ending_in(30, need=60, done=40)  # 20 to go, 30 left
    assert campaign_finishable(c, NOW)


def test_prerequisites_count_toward_the_time_needed():
    c = ending_in(120, need=60)
    first = c.drops[0]
    second = Drop("d2", "Second", first.rewards, first.starts_at, first.ends_at, 90, 0, False, None, ("d1",))
    c = replace(c, drops=(first, second))
    assert drop_finishable(c, first, NOW)            # 60 of 120
    assert not drop_finishable(c, second, NOW)       # 60 + 90 > 120
    assert campaign_finishable(c, NOW)               # the first still fits: keep mining for it


def test_the_planner_skips_hopeless_campaigns_only_with_the_setting_on():
    hopeless, fine = ending_in(30, need=300, cid="late"), ending_in(600, need=60, cid="ok")
    live = [chan("a", 7)]
    p = plan([hopeless, fine], live, Prefs(skip_too_late=True), NOW)
    assert p.current.campaign_id == "ok" and p.too_late == ("late",) and "late" not in p.queue
    p = plan([hopeless], live, Prefs(skip_too_late=False), NOW)
    assert p.current.campaign_id == "late" and p.too_late == ()


def test_mine_now_overrides_the_skip():
    hopeless, fine = ending_in(30, need=300, cid="late"), ending_in(600, need=60, cid="ok")
    p = plan([hopeless, fine], [chan("a", 7)], Prefs(skip_too_late=True), NOW, override_campaign="late")
    assert p.current.campaign_id == "late" and p.too_late == ()
