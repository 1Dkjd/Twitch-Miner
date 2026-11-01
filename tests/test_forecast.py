from datetime import timedelta

from test_planner import PALIA, PHAS, R, mk
from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan
from test_views import ViewStore

from dropwatch.api.views import state_view
from dropwatch.forecast import forecast
from dropwatch.models import Campaign, Drop, Game
from dropwatch.runner import Runner

ALBION = Game(3, "Albion", "albion")


def run(*cs, alongside=(), start=NOW, skip=False):
    ids = [c.id for c in cs]
    return forecast(ids[0], ids[1:], alongside, {c.id: c for c in cs}, start, NOW, skip_too_late=skip)


def two_rewards(cid, game, end_h):
    """A short reward after 1 h and a long one after 10 h, in one campaign ending in end_h hours."""
    start, end = NOW - timedelta(days=1), NOW + timedelta(hours=end_h)
    ds = tuple(Drop(f"{cid}-{m}", "d", (R,), start, end, m, 0, False, None) for m in (60, 600))
    return Campaign(cid, cid, game, start, end, True, "https://link", (), ds)


def test_the_queue_runs_back_to_back_in_order():
    a, b = mk(NOW, "a", PALIA, need=120, end_h=100), mk(NOW, "b", PHAS, need=60, end_h=100)
    first, second = run(a, b)
    assert (first.starts_at, first.finishes_at) == (NOW, NOW + timedelta(hours=2))
    assert (second.starts_at, second.finishes_at) == (NOW + timedelta(hours=2), NOW + timedelta(hours=3))
    assert first.status == second.status == "ok" and first.earned == 1 and second.missed == ()


def test_time_already_watched_counts():
    a, b = mk(NOW, "a", PALIA, need=120, cur=90, end_h=100), mk(NOW, "b", PHAS, need=60, end_h=100)
    assert run(a, b)[1].starts_at == NOW + timedelta(minutes=30)


def test_a_campaign_that_ends_before_its_turn_is_missed_and_takes_no_time():
    a = mk(NOW, "a", PALIA, need=240, end_h=100)
    late = mk(NOW, "late", PHAS, need=60, end_h=2)
    after = mk(NOW, "after", ALBION, need=60, end_h=100)
    _, b, c = run(a, late, after)
    assert b.status == "miss" and b.missed == ("Reward",) and b.earned == 0
    assert c.starts_at == NOW + timedelta(hours=4)  # the missed one did not delay it


def test_only_the_rewards_out_of_reach_are_missed():
    s = run(two_rewards("a", PALIA, 5))[0]
    assert s.status == "partial" and s.earned == 1 and s.missed == ("Reward",)


def test_skip_too_late_moves_on_after_the_last_reward_in_reach():
    assert run(two_rewards("a", PALIA, 5), skip=True)[0].finishes_at == NOW + timedelta(hours=1)
    # otherwise it stays until the campaign ends
    assert run(two_rewards("a", PALIA, 5), skip=False)[0].finishes_at == NOW + timedelta(hours=5)


def test_a_drop_window_closing_before_the_campaign_counts():
    d = Drop("d", "d", (R,), NOW - timedelta(days=1), NOW + timedelta(hours=1), 120, 0, False, None)
    c = Campaign("c", "c", PALIA, d.starts_at, NOW + timedelta(hours=50), True, "https://link", (), (d,))
    assert run(c)[0].status == "miss"


def test_earned_alongside_runs_at_once_and_what_follows_waits_for_the_longest():
    a = mk(NOW, "a", PALIA, need=60, end_h=100)
    b = mk(NOW, "b", PALIA, need=180, end_h=100)
    c = mk(NOW, "c", PHAS, need=60, end_h=100)
    _, along, after = run(a, b, c, alongside=("b",))
    assert along.alongside and along.starts_at == NOW and along.finishes_at == NOW + timedelta(hours=3)
    assert after.starts_at == NOW + timedelta(hours=3)


def test_a_later_start_can_cost_rewards():
    a = mk(NOW, "a", PALIA, need=60, end_h=2)
    assert run(a)[0].status == "ok"
    assert run(a, start=NOW + timedelta(hours=2))[0].status == "miss"


def test_unknown_ids_and_no_current_are_fine():
    a = mk(NOW, "a", PALIA, need=60, end_h=100)
    assert [s.campaign.id for s in forecast(None, ["gone", "a"], (), {"a": a}, NOW, NOW)] == ["a"]
    assert forecast(None, [], (), {}, NOW, NOW) == []


async def test_state_carries_the_forecast():
    st = ViewStore()
    r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    f = state_view(r, st, NOW).forecast
    assert [s.campaign_id for s in f.steps] == [camp().id]
    assert f.missed == 0 and f.finishes_at == f.steps[0].finishes_at and f.waiting == []


async def test_nobody_live_means_waiting_not_scheduled():
    st = ViewStore()
    r = Runner(FakeClient([camp()], []), FakeWatcher(), FakePubSub(), st, user_id=42, clock=lambda: NOW)
    await r.refresh()
    f = state_view(r, st, NOW).forecast
    assert f.steps == [] and f.finishes_at is None and f.waiting == [camp().name]


async def test_no_forecast_before_a_plan_or_while_paused_for_good():
    st = ViewStore()
    r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW)
    assert state_view(r, st, NOW).forecast is None
    await r.refresh()
    assert state_view(r, st, NOW).forecast is not None
    r.state, r.paused_until = "paused", None
    assert state_view(r, st, NOW).forecast is None
    r.paused_until = NOW + timedelta(hours=1)
    assert state_view(r, st, NOW).forecast.steps[0].starts_at == NOW + timedelta(hours=1)
