"""Up next: "Arrange myself" pins (approved in docs/design/next-features-mockup.html, 2026-10-10). Pinned
campaigns go first after Priority, in the pinned order; the rest stay in the automatic order. Nick chose
to leave the automatic order itself unchanged (2026-10-10)."""
from datetime import timedelta

from test_planner import PALIA, PHAS, ch, mk

from dropwatch.models import Game, Prefs
from dropwatch.planner import plan
from dropwatch.store import Store

ALBION = Game(3, "Albion Online", "albion")


def test_pins_go_first_after_priority_in_pinned_order(now):
    urgent = mk(now, "urgent", PHAS, need=100, end_h=3)
    a = mk(now, "a", ALBION, end_h=200)
    b = mk(now, "b", PALIA, end_h=300)
    live = [ch("x", PHAS), ch("y", ALBION), ch("z", PALIA)]
    assert plan([urgent, a, b], live, Prefs(), now).current.campaign_id == "urgent"  # automatic
    p = plan([urgent, a, b], live, Prefs(pins=("b", "a")), now)
    assert (p.current.campaign_id, p.queue) == ("b", ("a", "urgent"))
    assert p.current.reason == "you pinned it"
    p = plan([urgent, a, b], live, Prefs(priority=("Phasmophobia",), pins=("b", "a")), now)
    assert (p.current.campaign_id, p.queue) == ("urgent", ("b", "a"))  # Priority still wins


def test_a_pin_is_not_held_back_by_the_current_campaign(now):
    cur = mk(now, "cur", PHAS, need=100, end_h=3)  # very urgent and being mined
    pinned = mk(now, "pinned", PALIA, end_h=300)
    p = plan([cur, pinned], [ch("x", PHAS), ch("z", PALIA)], Prefs(pins=("pinned",)), now,
             current_campaign="cur", watching="x")
    assert p.current.campaign_id == "pinned"


def test_pins_only_count_while_arrange_myself_is_on(tmp_path):
    st = Store(tmp_path / "d.db")
    assert st.get_settings()["arrange_up_next"] is False
    st.set_pins(["c2", "c1", "c2"])
    assert st.get_pins() == ["c2", "c1"]  # no duplicates
    assert st.get_prefs().pins == ()  # switched off: automatic
    st.put_settings({"arrange_up_next": True})
    assert st.get_prefs().pins == ("c2", "c1")
    st.put_settings({"arrange_up_next": False})
    assert st.get_pins() == ["c2", "c1"]  # remembered for next time


async def test_runner_forgets_pins_of_campaigns_that_ended(tmp_path):
    from dataclasses import replace

    from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan

    from dropwatch.runner import Runner

    st = Store(tmp_path / "d.db")
    st.put_settings({"arrange_up_next": True})
    st.set_pins(["c1", "gone"])
    ended = replace(camp(), id="old", starts_at=NOW - timedelta(days=9), ends_at=NOW - timedelta(days=1))
    st.set_pins(["c1", "old", "gone"])
    r = Runner(FakeClient([camp(), ended], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    assert st.get_pins() == ["c1"]


async def test_api_pins_replan_and_state_marks_pinned_and_late(tmp_path):
    from apihelpers import NOW, logged_in, make_app
    from test_runner import FakeClient, FakePubSub, FakeWatcher, chan

    from dropwatch.runner import Runner

    G = Game(1, "Palia", "palia")
    soon = mk(NOW, "soon", G, need=120, end_h=3)  # 2 h of work, 3 h left
    later = mk(NOW, "later", G, need=120, end_h=200)
    other = mk(NOW, "other", G, need=120, end_h=300)
    app, ctx = make_app(tmp_path)
    r = Runner(FakeClient([soon, later, other], [chan("a", 7)]), FakeWatcher(), FakePubSub(), ctx.store,
               user_id=42, clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    c = await logged_in(app)
    assert (await c.put("/api/settings", json={"arrange_up_next": True})).status_code == 200
    got = (await c.put("/api/pins", json={"pins": ["other", "later"]})).json()
    assert got == {"pins": ["other", "later"]}
    s = (await c.get("/api/state")).json()
    assert s["current"]["campaign"]["id"] == "other" and s["current"]["campaign"]["pinned"] is True
    by = {x["id"]: x for x in s["up_next"]}
    assert [x["id"] for x in s["up_next"]] == ["later", "soon"]
    assert by["later"]["pinned"] is True and by["soon"]["pinned"] is False
    # "soon" needs 2 h and ends in 3 h, but 4 h of pinned work comes first: it ends before its turn
    assert by["soon"]["ends_before_turn"] is True and by["later"]["ends_before_turn"] is False
    assert (await c.put("/api/pins", json={"pins": ["x" * 200]})).status_code == 422
    await c.aclose()


async def test_switching_arrange_myself_takes_effect_at_once(tmp_path):
    from apihelpers import NOW, logged_in, make_app
    from test_runner import FakeClient, FakePubSub, FakeWatcher, chan

    from dropwatch.runner import Runner

    G = Game(1, "Palia", "palia")
    urgent, relaxed = mk(NOW, "urgent", G, need=120, end_h=3), mk(NOW, "relaxed", G, need=60, end_h=300)
    app, ctx = make_app(tmp_path)
    ctx.store.set_pins(["relaxed"])
    r = Runner(FakeClient([urgent, relaxed], [chan("a", 7)]), FakeWatcher(), FakePubSub(), ctx.store,
               user_id=42, clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    c = await logged_in(app)
    assert r.plan.current.campaign_id == "urgent"
    await c.put("/api/settings", json={"arrange_up_next": True})
    assert r.plan.current.campaign_id == "relaxed"  # no wait for the next 5-minute refresh
    await c.put("/api/settings", json={"arrange_up_next": False})
    assert r.plan.current.campaign_id == "urgent"
    await c.aclose()
