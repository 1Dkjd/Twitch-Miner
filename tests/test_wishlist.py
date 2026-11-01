"""Inventory stars: mining order, the alert, the API and the backup."""
from datetime import timedelta

from apihelpers import NOW, logged_in, make_app
from test_planner import PALIA, PHAS, ch, mk
from test_runner import FakeClient, FakePubSub, FakeWatcher

from dropwatch.alerts import Notifier, Snapshot
from dropwatch.models import Game, Prefs
from dropwatch.planner import plan
from dropwatch.runner import Runner

ALBION = Game(3, "Albion", "albion")
LIVE = [ch("a", PALIA), ch("b", PHAS), ch("c", ALBION)]


def order(*cs, **prefs):
    p = plan(cs, LIVE, Prefs(**prefs), NOW)
    return [p.current.campaign_id, *p.queue], p


def test_a_star_goes_before_the_automatic_order():
    urgent, starred = mk(NOW, "urgent", PALIA, end_h=2), mk(NOW, "starred", PHAS, end_h=200)
    ids, p = order(urgent, starred, wanted=frozenset({"starred-d"}))
    assert ids == ["starred", "urgent"]
    assert p.current.reason == "you starred a reward"


def test_priority_and_pins_still_come_first():
    a, b, c = mk(NOW, "a", PALIA), mk(NOW, "b", PHAS), mk(NOW, "c", ALBION)
    wanted = frozenset({"c-d"})
    assert order(a, b, c, wanted=wanted, priority=("Palia",))[0][:2] == ["a", "c"]
    assert order(a, b, c, wanted=wanted, pins=("b",))[0][:2] == ["b", "c"]


def test_a_claimed_star_no_longer_counts():
    done = mk(NOW, "done", PALIA, end_h=200, claimed=True)
    other = mk(NOW, "other", PHAS, end_h=2)
    assert order(done, other, wanted=frozenset({"done-d"}))[0][0] == "other"


def test_stars_are_not_held_back_by_hysteresis():
    cur, starred = mk(NOW, "cur", PALIA, end_h=2), mk(NOW, "starred", PHAS, end_h=200)
    p = plan([cur, starred], LIVE, Prefs(wanted=frozenset({"starred-d"})), NOW, current_campaign="cur")
    assert p.current.campaign_id == "starred"


def test_priority_only_still_rules_a_star_out():
    a, starred = mk(NOW, "a", PALIA), mk(NOW, "starred", PHAS)
    ids, p = order(a, starred, wanted=frozenset({"starred-d"}), priority=("Palia",), priority_only=True)
    assert ids == ["a"] and p.outside == ("starred",)


async def test_api_saves_replans_and_backs_up(tmp_path):
    a, b = mk(NOW, "a", PALIA, end_h=2), mk(NOW, "b", PHAS, end_h=200)
    app, ctx = make_app(tmp_path)
    r = Runner(FakeClient([a, b], LIVE), FakeWatcher(), FakePubSub(), ctx.store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    c = await logged_in(app)
    assert (await c.get("/api/state")).json()["current"]["campaign"]["id"] == "a"
    assert (await c.put("/api/wishlist", json={"drops": ["b-d", "b-d"]})).json() == {"drops": ["b-d"]}
    assert (await c.get("/api/wishlist")).json() == {"drops": ["b-d"]}
    s = (await c.get("/api/state")).json()
    assert s["current"]["campaign"]["id"] == "b" and s["current"]["reason"] == "you starred a reward"
    assert (await c.get("/api/backup")).json()["wishlist"] == ["b-d"]
    assert (await c.put("/api/wishlist", json={"drops": ["x" * 200]})).status_code == 422
    await c.aclose()


async def test_stars_of_ended_campaigns_are_forgotten(tmp_path):
    over = mk(NOW, "over", PALIA, end_h=-1)
    app, ctx = make_app(tmp_path)
    ctx.store.set_wishlist(["over-d", "gone-d"])
    r = Runner(FakeClient([over], LIVE), FakeWatcher(), FakePubSub(), ctx.store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    assert ctx.store.get_wishlist() == ["gone-d"]  # a short list forgets nothing


def _notifier(tmp_path, **settings):
    _, ctx = make_app(tmp_path)
    if settings:
        ctx.store.put_settings(settings)
    return Notifier(ctx.store, clock=lambda: NOW)


SKIN = "https://static-cdn.jtvnw.net/skin.png"
RISK = ("d1", "Skin", "Rust", NOW + timedelta(hours=1), SKIN)


def test_alert_fires_once_per_reward(tmp_path):
    n = _notifier(tmp_path)
    got = n.check(Snapshot(None, None, at_risk=[RISK]))
    mine = [a for a in got if a.key == "notify_wishlist"]
    assert len(mine) == 1 and "Skin" in mine[0].title and "Rust" in mine[0].body
    assert mine[0].image == SKIN
    assert not [a for a in n.check(Snapshot(None, None, at_risk=[RISK])) if a.key == "notify_wishlist"]


def test_alert_can_be_switched_off(tmp_path):
    n = _notifier(tmp_path, notify_wishlist=False)
    assert not [a for a in n.check(Snapshot(None, None, at_risk=[RISK])) if a.key == "notify_wishlist"]


async def test_state_counts_live_channels_and_reports_progress(tmp_path):
    a = mk(NOW, "a", PALIA)
    app, ctx = make_app(tmp_path)
    live = [ch("a", PALIA), ch("a2", PALIA), ch("b", PHAS)]
    r = Runner(FakeClient([a], live), FakeWatcher(), FakePubSub(), ctx.store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    c = await logged_in(app)
    s = (await c.get("/api/state")).json()
    assert s["current"]["campaign"]["live_channels"] == 2 and s["last_progress_at"] is None
    await c.aclose()


async def test_history_since_replaces_days(tmp_path):
    app, ctx = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.get("/api/history", params={"since": (NOW - timedelta(hours=3)).isoformat()})
    assert r.status_code == 200 and r.json()["total_rewards"] == 0
    no_zone = await c.get("/api/history", params={"since": "2026-01-01T00:00:00"})
    assert no_zone.status_code == 422
    await c.aclose()
