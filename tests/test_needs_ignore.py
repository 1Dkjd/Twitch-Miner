"""Needs you > Ignore (approved 2026-10-11, docs/design/ignore-mockup.html): hides one campaign from
Needs you until it ends, and with it its alert and its mention in the weekly summary. Undo or Unignore
brings it back."""
from dataclasses import replace
from datetime import timedelta

from test_planner import PALIA, PHAS, ch, mk

from dropwatch.alerts import Notifier, Snapshot
from dropwatch.models import Prefs
from dropwatch.planner import plan
from dropwatch.store import Store


def test_an_ignored_campaign_leaves_needs_you_but_is_still_known(now):
    a, b = mk(now, "a", PALIA, linked=False), mk(now, "b", PHAS, linked=False, end_h=200)
    p = plan([a, b], [ch("x", PALIA)], Prefs(ignored=frozenset({"a"})), now)
    assert p.needs_you == ("b",)
    assert p.needs_ignored == ("a",)


def test_ignoring_is_per_campaign_not_per_game(now):
    a, a2 = mk(now, "a", PALIA, linked=False), mk(now, "a2", PALIA, linked=False, end_h=200)
    p = plan([a, a2], [], Prefs(ignored=frozenset({"a"})), now)
    assert p.needs_you == ("a2",)  # the game's next campaign still asks


def test_an_ignored_campaign_is_mined_once_linked(now):
    a = mk(now, "a", PALIA, linked=True)
    p = plan([a], [ch("x", PALIA)], Prefs(ignored=frozenset({"a"})), now)
    assert p.current.campaign_id == "a" and p.needs_ignored == ()


def test_store_keeps_ignored_ids_once_each(tmp_path):
    st = Store(tmp_path / "d.db")
    assert st.get_ignored() == [] and st.get_prefs().ignored == frozenset()
    st.set_ignored(["c2", "c1", "c2"])
    assert st.get_ignored() == ["c2", "c1"]
    assert st.get_prefs().ignored == frozenset({"c1", "c2"})


def test_no_alert_for_an_ignored_campaign(tmp_path, now):
    st = Store(tmp_path / "d.db")
    st.put_settings({"notify_needs_you": True})
    n = Notifier(st, clock=lambda: now)
    a, b = mk(now, "a", PALIA, linked=False), mk(now, "b", PHAS, linked=False)
    p = plan([a, b], [], Prefs(ignored=frozenset({"a"})), now)
    by = {c.id: c for c in (a, b)}
    snap = Snapshot(None, None, [(c.id, c.name, c.game.name) for cid in p.needs_you if (c := by[cid])])
    # the alert and the weekly summary both read Snapshot.needs_you, built from plan.needs_you (snapshot_of)
    alerts = n._needs_you(snap.needs_you, st.get_settings())
    assert [x.title for x in alerts] == ["Dropwatch: b needs your account linked"]


async def test_runner_forgets_ignored_campaigns_that_ended(tmp_path):
    from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan

    from dropwatch.runner import Runner

    st = Store(tmp_path / "d.db")
    ended = replace(camp(), id="old", starts_at=NOW - timedelta(days=9), ends_at=NOW - timedelta(days=1))
    st.set_ignored(["c1", "old", "gone"])
    r = Runner(FakeClient([camp(), ended], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    assert st.get_ignored() == ["c1", "gone"]  # as pins: only what is known to have ended goes


async def test_api_ignore_and_unignore_replan_and_show_in_state(tmp_path):
    from apihelpers import NOW, logged_in, make_app
    from test_runner import FakeClient, FakePubSub, FakeWatcher

    from dropwatch.runner import Runner

    a, b = mk(NOW, "a", PALIA, linked=False), mk(NOW, "b", PHAS, linked=False, end_h=200)
    app, ctx = make_app(tmp_path)
    r = Runner(FakeClient([a, b], []), FakeWatcher(), FakePubSub(), ctx.store, user_id=42, clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    c = await logged_in(app)
    assert (await c.post("/api/needs/ignored/a")).json() == {"ids": ["a"]}
    s = (await c.get("/api/state")).json()
    assert [x["id"] for x in s["needs_you"]] == ["b"]
    assert [x["id"] for x in s["needs_ignored"]] == ["a"]
    assert (await c.post("/api/needs/ignored/a")).json() == {"ids": ["a"]}  # twice is once
    assert (await c.delete("/api/needs/ignored/a")).json() == {"ids": []}
    s = (await c.get("/api/state")).json()
    assert [x["id"] for x in s["needs_you"]] == ["a", "b"] and s["needs_ignored"] == []
    assert (await c.post("/api/needs/ignored/" + "x" * 200)).status_code == 422
    await c.aclose()
