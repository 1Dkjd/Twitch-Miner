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


# --- review fixes (2026-10-12)
def test_offline_campaigns_outside_priority_are_not_first_in_line(now):
    palia, albion = mk(now, "palia", PALIA), mk(now, "albion", ALBION)
    p = plan([palia, albion], [], Prefs(priority=("Palia",), priority_only=True), now)
    assert p.waiting == ("palia",)


def test_a_mine_now_override_cannot_pick_a_game_outside_priority(now):
    palia, albion = mk(now, "palia", PALIA, end_h=300), mk(now, "albion", ALBION, end_h=3)
    prefs = Prefs(priority=("Palia",), priority_only=True)
    p = plan([palia, albion], [ch("a", PALIA), ch("c", ALBION)], prefs, now, override_campaign="albion")
    assert p.current.campaign_id == "palia"


def test_toggling_priority_only_does_not_re_alert_campaigns_already_announced(tmp_path, now):
    from dropwatch.alerts import Notifier
    st = Store(tmp_path / "d.db")
    st.put_settings({"notify_needs_you": True})
    n = Notifier(st, clock=lambda: now)
    both = [("a", "A", "Palia"), ("b", "B", "Albion Online")]
    assert len(n._needs_you(both, st.get_settings())) == 1  # one message for the two
    st.put_settings({"priority_only": True})
    assert n._needs_you(both[:1], st.get_settings()) == []  # b left Needs you only because of the switch
    st.put_settings({"priority_only": False})
    assert n._needs_you(both, st.get_settings()) == []  # so it isn't "new" when the switch goes off


def test_history_says_priority_only_kept_a_campaign_from_being_mined(tmp_path, now):
    from datetime import timedelta
    st = Store(tmp_path / "d.db")
    row = {"id": "c1", "name": "AOCP", "game": "Albion Online", "box_art_url": "", "link_url": "",
           "ends_at": now + timedelta(minutes=30), "linked": True, "badge": False,
           "rewards": [{"name": "R", "image_url": "", "claimed": False}], "impossible": False,
           "never": False, "priority": False, "pinned": False, "live": True, "watched": 0, "outside": True}
    st.log_campaigns(now, [row])
    missed = st.missed_between(now - timedelta(hours=1), now + timedelta(hours=1))
    assert [m["reason"] for m in missed] == ["priority_only"]
    st.log_campaigns(now, [{**row, "id": "c2", "outside": False}])
    missed = st.missed_between(now - timedelta(hours=1), now + timedelta(hours=1))
    assert {m["campaign_id"]: m["reason"] for m in missed}["c2"] == "outranked"


def test_an_existing_database_gets_the_new_column(tmp_path):
    import sqlite3
    path = tmp_path / "d.db"
    old = sqlite3.connect(path)  # campaign_log as it was before 2026-10-12, with one row in it
    old.execute("CREATE TABLE campaign_log (id TEXT PRIMARY KEY, name TEXT NOT NULL, game TEXT NOT NULL,"
                " box_art_url TEXT NOT NULL, link_url TEXT NOT NULL, ends_at TEXT NOT NULL,"
                " rewards TEXT NOT NULL,"
                " first_seen TEXT NOT NULL, impossible_at_first INTEGER NOT NULL, last_seen TEXT NOT NULL,"
                " linked INTEGER, badge INTEGER NOT NULL, never INTEGER NOT NULL, priority INTEGER NOT NULL,"
                " pinned INTEGER NOT NULL, live INTEGER NOT NULL, watched INTEGER NOT NULL)")
    old.execute("INSERT INTO campaign_log VALUES ('c0','n','g','','','2026-01-01T00:00:00+00:00','[]',"
                "'2026-01-01T00:00:00+00:00',0,'2026-01-01T00:00:00+00:00',1,0,0,0,0,1,0)")
    old.commit()
    old.close()
    st = Store(path)
    cols = {r[1] for r in st._db.execute("PRAGMA table_info(campaign_log)")}
    assert "outside" in cols
    assert st._db.execute("SELECT outside FROM campaign_log WHERE id = 'c0'").fetchone() == (0,)
