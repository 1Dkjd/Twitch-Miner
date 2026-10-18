"""Homepage widget (key-protected summary) and "I've linked it" (2026-10-18)."""
from dataclasses import replace

from apihelpers import NOW, client, logged_in, make_app, runner_with_plan
from test_runner import FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

from dropwatch.runner import Runner


async def test_widget_needs_its_key_and_reports_the_mining(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    async with client(app) as anon:
        assert (await anon.get("/api/widget")).status_code == 401  # no key made yet
    c = await logged_in(app)
    assert (await c.get("/api/widget/key")).json() == {"exists": False, "key": None}
    key = (await c.post("/api/widget/key")).json()["key"]
    assert key and (await c.get("/api/widget/key")).json() == {"exists": True, "key": None}
    async with client(app) as anon:
        assert (await anon.get("/api/widget?key=wrong")).status_code == 401
        r = await anon.get(f"/api/widget?key={key}")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        w = r.json()
        assert (w["status"], w["game"], w["campaign"], w["channel"]) == ("mining", "Palia", "Frights", "a")
        assert w["next_reward"] == "Palcat Glasses" and w["next_in_minutes"] == 60 and w["progress"] == 0
    assert (await c.delete("/api/widget/key")).status_code == 204
    async with client(app) as anon:
        assert (await anon.get(f"/api/widget?key={key}")).status_code == 401  # revoked


async def test_ive_linked_it_rereads_and_reports():
    fc = FakeClient([replace(camp(), linked=None)], [chan("a", 7)])
    r = Runner(fc, FakeWatcher(), FakePubSub(), FakeStore(), user_id=42, clock=lambda: NOW)
    await r.refresh()
    r.maybe_unlinked["c1"] = NOW
    fc.camps = [replace(camp(), linked=True)]  # Twitch now says linked
    assert await r.linked_check("palia") == "linked"
    assert "c1" not in r.maybe_unlinked
    fc.camps = [replace(camp(), linked=False)]
    assert await r.linked_check("Palia") == "not_linked"
