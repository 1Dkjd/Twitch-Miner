"""Favourite channels: remember every channel seen live, and say which are live now (2026-10-10)."""
from datetime import timedelta

from apihelpers import NOW, logged_in, make_app
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.models import LiveChannel
from dropwatch.runner import Runner
from dropwatch.store import Store


def test_seen_channels_upsert_newest_first_and_prune(tmp_path):
    st = Store(tmp_path / "d.db")
    st.record_seen([("old_one", "Palia")], NOW - timedelta(days=40))
    st.record_seen([("alpha", "Palia"), ("beta", "Phasmophobia")], NOW - timedelta(hours=2))
    st.record_seen([("alpha", "AION 2")], NOW)
    rows = st.seen_channels(NOW)
    assert [(r["login"], r["game"]) for r in rows] == [("alpha", "AION 2"), ("beta", "Phasmophobia")]
    assert rows[0]["last_seen"] == NOW


async def test_runner_records_what_it_sees(tmp_path):
    st = Store(tmp_path / "d.db")
    r = Runner(FakeClient([camp()], [chan("a", 7), chan("b", 8)]), FakeWatcher(), FakePubSub(), st,
               user_id=42, clock=lambda: NOW)
    await r.refresh()
    assert {x["login"] for x in st.seen_channels(NOW)} == {"a", "b"}


async def test_suggestions_report_live_game_and_last_seen(tmp_path):
    app, ctx = make_app(tmp_path)
    live = [LiveChannel(7, "a", 1, 100, True, "b7", "Palia")]
    r = Runner(FakeClient([camp()], live), FakeWatcher(), FakePubSub(), ctx.store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    ctx.store.record_seen([("gone", "Phasmophobia")], NOW - timedelta(days=2))
    ctx.store.set_lists([], set(), ["fav_never_seen"])
    c = await logged_in(app)
    s = (await c.get("/api/suggestions")).json()
    by = {x["login"]: x for x in s["channels"]}
    assert by["a"]["live"] is True and by["a"]["game"] == "Palia"
    assert by["gone"]["live"] is False and by["gone"]["game"] == "Phasmophobia" and by["gone"]["last_seen"]
    assert by["fav_never_seen"] == {"login": "fav_never_seen", "live": False, "game": None, "last_seen": None}
    assert [x["login"] for x in s["channels"]][0] == "a"  # live first
    await c.aclose()


async def test_offline_suggestions_are_capped_but_favourites_never_drop(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.store.record_seen([(f"ch{i:04d}", "Palia") for i in range(400)], NOW)
    ctx.store.set_lists([], set(), ["ch0399", "nobody"])
    c = await logged_in(app)
    chans = (await c.get("/api/suggestions")).json()["channels"]
    logins = [x["login"] for x in chans]
    # the newest 300 offline channels, plus the favourite ch0399 that falls outside them
    assert len([x for x in chans if not x["live"] and x["last_seen"]]) == 301
    assert "ch0399" in logins and "nobody" in logins  # favourites are always there
    await c.aclose()
