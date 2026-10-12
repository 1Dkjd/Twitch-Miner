"""Priority-only mining (approved 2026-10-12, docs/design/priority-only-mockup.html): with the switch on, only
games in Priority are mined (not pins, not badge campaigns); everything else is "outside", folded away on the
page; Needs you only lists Priority games; with nothing to mine Dropwatch waits."""
from test_planner import BADGE, PALIA, PHAS, ch, mk

from dropwatch.models import Game, Prefs
from dropwatch.planner import plan
from dropwatch.store import Store

ALBION = Game(3, "Albion Online", "albion")


def test_only_priority_games_are_mined_and_the_rest_are_outside(now):
    palia, phas, albion = mk(now, "palia", PALIA), mk(now, "phas", PHAS, end_h=3), mk(now, "albion", ALBION)
    live = [ch("a", PALIA), ch("b", PHAS), ch("c", ALBION)]
    p = plan([palia, phas, albion], live, Prefs(priority=("Palia",), priority_only=True), now)
    assert p.current.campaign_id == "palia" and p.queue == ()
    assert set(p.outside) == {"phas", "albion"}
    off = plan([palia, phas, albion], live, Prefs(priority=("Palia",)), now)
    assert off.outside == () and set(off.queue) == {"phas", "albion"}  # switch off: as before


def test_pins_and_badge_campaigns_outside_priority_wait_too(now):
    pinned, badge = mk(now, "pinned", PHAS), mk(now, "badge", ALBION, rewards=(BADGE,))
    live = [ch("b", PHAS), ch("c", ALBION)]
    p = plan([pinned, badge], live, Prefs(priority=("Palia",), pins=("pinned",), mine_badges=True,
                                          priority_only=True), now)
    assert p.current is None and set(p.outside) == {"pinned", "badge"}


def test_with_no_priority_game_live_it_waits_and_says_who_is_first(now):
    palia, albion = mk(now, "palia", PALIA), mk(now, "albion", ALBION)
    p = plan([palia, albion], [ch("c", ALBION)], Prefs(priority=("Palia",), priority_only=True), now)
    assert p.current is None
    assert p.waiting == ("palia",)  # first in line: a Priority campaign with nobody live
    assert p.outside == ("albion",)


def test_needs_you_only_lists_priority_games(now):
    palia, albion = mk(now, "palia", PALIA, linked=False), mk(now, "albion", ALBION, linked=False)
    p = plan([palia, albion], [], Prefs(priority=("Palia",), priority_only=True), now)
    assert p.needs_you == ("palia",)


def test_the_setting_is_off_by_default_and_reaches_prefs(tmp_path):
    st = Store(tmp_path / "d.db")
    assert st.get_settings()["priority_only"] is False and st.get_prefs().priority_only is False
    st.put_settings({"priority_only": True})
    assert st.get_prefs().priority_only is True


async def test_api_switch_state_and_mine_now(tmp_path):
    from apihelpers import NOW, logged_in, make_app
    from test_runner import FakeClient, FakePubSub, FakeWatcher

    from dropwatch.models import LiveChannel
    from dropwatch.runner import Runner

    palia, albion = mk(NOW, "palia", Game(1, "Palia", "palia")), mk(NOW, "albion", ALBION)
    live = [LiveChannel(1, "ch1", 1, 100, True, "b1"), LiveChannel(3, "ch3", 3, 100, True, "b3")]
    app, ctx = make_app(tmp_path)
    ctx.store.set_lists(["Palia"], set(), [])
    r = Runner(FakeClient([palia, albion], live), FakeWatcher(), FakePubSub(), ctx.store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    c = await logged_in(app)
    s = (await c.get("/api/state")).json()
    assert s["priority_only"] is False and s["outside"] == []
    assert (await c.put("/api/settings", json={"priority_only": True})).json()["priority_only"] is True
    s = (await c.get("/api/state")).json()
    assert s["priority_only"] is True
    assert s["current"]["campaign"]["id"] == "palia" and s["up_next"] == []
    assert [x["id"] for x in s["outside"]] == ["albion"]
    r2 = await c.post("/api/mine-now", json={"campaign_id": "albion"})
    assert r2.status_code == 409 and "Priority only" in r2.json()["detail"]
    await c.aclose()
