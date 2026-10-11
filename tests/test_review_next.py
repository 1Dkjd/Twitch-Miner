"""Fixes from the fresh review of feat/next-features (2026-10-10). Each test failed before its fix."""
from dataclasses import replace
from datetime import timedelta

from test_missed import c, seen
from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.runner import Runner
from dropwatch.store import Store
from dropwatch.twitch.pubsub import PointsClaimable


# 2: a History log or pin write that fails must not stop planning
async def test_a_failing_log_write_never_stops_the_refresh(tmp_path):
    st = Store(tmp_path / "d.db")

    def broken(*a, **k):
        raise RuntimeError("database is locked")

    st.log_campaigns = broken
    st.set_pins = broken
    st.put_settings({"arrange_up_next": True})
    st._db.execute("INSERT INTO settings VALUES ('up_next_pins', '[\"gone\"]')")
    r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    assert r.plan.current is not None and r.last_refresh == NOW


# 3: only pins of campaigns known to have ended are dropped, never because a list came back short
async def test_a_short_campaign_list_keeps_pins(tmp_path):
    st = Store(tmp_path / "d.db")
    st.put_settings({"arrange_up_next": True})
    st.set_pins(["c1", "missing-now", "ended"])
    ended = c("ended", "Ended", end_h=1)
    await seen(st, [ended], NOW)  # logged once, while running
    r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW + timedelta(hours=2))
    await r.refresh()  # "ended" has ended and left the list; "missing-now" just isn't listed this time
    assert st.get_pins() == ["c1", "missing-now"]


# 4b: a reward claimed in the 24 h after the end is not missed; 4a: nor one in History's claims
async def test_claimed_after_the_end_or_recorded_in_claims_is_not_missed(tmp_path):
    st = Store(tmp_path / "d.db")
    late = c("late", "Claimed late", cur=60, need=60, end_h=1)
    await seen(st, [late], NOW + timedelta(minutes=55))
    claimed = replace(late, drops=(replace(late.drops[0], claimed=True),))
    await seen(st, [claimed], NOW + timedelta(hours=2))  # Twitch now lists it claimed, after the end
    assert st.missed_between(NOW - timedelta(days=1), NOW + timedelta(hours=3)) == []
    other = c("other", "Claimed by Dropwatch", cur=60, need=60, end_h=1)
    st2 = Store(tmp_path / "e.db")
    await seen(st2, [other], NOW + timedelta(minutes=55))
    st2.add_claim(NOW + timedelta(minutes=58), "other", "Claimed by Dropwatch", "Palia",
                  [("Claimed by Dropwatch reward", "img/other")])
    assert st2.missed_between(NOW - timedelta(days=1), NOW + timedelta(hours=3)) == []


# 9: a campaign earned on the same stream as the current one takes no extra queue time
async def test_also_credited_campaigns_do_not_push_others_past_their_end(tmp_path):
    from apihelpers import logged_in, make_app

    from dropwatch.models import Game, LiveChannel

    palia, other = Game(1, "Palia", "palia"), Game(2, "Other", "other")
    cur = c("cur", "Current", palia, need=120, end_h=10)  # Palia is in Priority: mined first
    twin = c("twin", "Twin", palia, need=120, end_h=10)  # same game, same stream: earned alongside
    tight = c("tight", "Tight", other, need=60, end_h=3.5)  # 120 + 60 = 180 min of work, 210 min left
    live = [chan("a", 7), LiveChannel(8, "b", 2, 100, True, "b8", "Other")]
    app, ctx = make_app(tmp_path)
    ctx.store.set_lists(["Palia"], set(), [])
    r = Runner(FakeClient([cur, twin, tight], live), FakeWatcher(), FakePubSub(), ctx.store,
               user_id=42, clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    assert r.plan.current.campaign_id == "cur" and "twin" in r.plan.also_credited
    cl = await logged_in(app)
    by = {x["id"]: x for x in (await cl.get("/api/state")).json()["up_next"]}
    assert by["tight"]["ends_before_turn"] is False
    await cl.aclose()


# 11: a malformed chest message is ignored, and switching points on subscribes at once
async def test_points_ignore_malformed_chests(tmp_path):
    from test_points import make

    r, client, _ = make(tmp_path)
    await r.refresh()
    await r.handle(PointsClaimable(0, ""))
    await r.handle(PointsClaimable(7, ""))
    assert client.points_claims == []


async def test_a_failing_points_claim_never_breaks_the_refresh(tmp_path):
    from test_points import make

    r, client, _ = make(tmp_path, waiting=(7, "claim-0"))

    async def boom(*a):
        raise RuntimeError("not a Twitch error")

    client.claim_points = boom
    await r.refresh()
    assert r.plan.current is not None and r.last_refresh == NOW


async def test_switching_points_on_subscribes_at_once(tmp_path):
    from apihelpers import logged_in, make_app
    from test_points import PointsClient

    from dropwatch.twitch.pubsub import topic

    app, ctx = make_app(tmp_path)
    ctx.store.put_settings({"claim_points": False})
    pubsub = FakePubSub()
    r = Runner(PointsClient([camp()], [chan("a", 7)]), FakeWatcher(), pubsub, ctx.store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    ctx.service.runner = r
    cl = await logged_in(app)
    assert topic("user_points", 42) not in pubsub.topics
    await cl.put("/api/settings", json={"claim_points": True})
    assert topic("user_points", 42) in pubsub.topics
    await cl.aclose()


# 6: the notifier survives an error, and a summary that couldn't be delivered isn't marked sent
async def test_the_notifier_survives_an_error_and_resends_an_undelivered_summary(tmp_path):
    import asyncio
    from datetime import UTC, datetime

    from dropwatch.alerts import Notifier, Snapshot
    from dropwatch.events import EventBus

    st = Store(tmp_path / "d.db")
    st.put_settings({"notify_weekly": True})
    at = [datetime(2026, 10, 11, 18, 1, tzinfo=UTC)]
    n = Notifier(st, clock=lambda: at[0], tz=UTC)
    calls, results = [], [[{"name": "ntfy", "message": "ntfy: HTTP 500", "ok": False}]]  # first send fails

    async def send(title, body):
        calls.append(title)
        return results.pop(0) if results else [{"name": "ntfy", "message": "sent", "ok": True}]

    real = st.claims_since
    st.claims_since = lambda since: (_ for _ in ()).throw(RuntimeError("database is locked"))
    bus = EventBus()
    task = asyncio.create_task(n.run(bus, lambda: Snapshot(None, None, []), send))
    await asyncio.sleep(0)
    bus.publish("state", {"state": "mining"})  # check() raises inside the loop
    await asyncio.sleep(0.05)
    assert not task.done()  # still running
    st.claims_since = real
    bus.publish("state", {"state": "mining"})
    await asyncio.sleep(0.05)  # sent, but no channel delivered it
    bus.publish("state", {"state": "mining"})
    await asyncio.sleep(0.05)
    assert calls == ["Dropwatch: Your week"]  # not retried at once
    at[0] += timedelta(minutes=11)
    bus.publish("state", {"state": "mining"})
    await asyncio.sleep(0.05)
    task.cancel()
    assert calls == ["Dropwatch: Your week", "Dropwatch: Your week"]  # undelivered once, so sent again
    assert st.get_setting("notify_weekly_sent") == "2026-10-11"
