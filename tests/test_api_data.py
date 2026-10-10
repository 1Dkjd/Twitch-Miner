from datetime import timedelta

from apihelpers import NOW, logged_in, make_app, runner_with_plan


async def test_state_signed_out(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    s = (await c.get("/api/state")).json()
    assert s["state"] == "signed_out" and s["current"] is None
    await c.aclose()


async def test_state_mining(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    c = await logged_in(app)
    s = (await c.get("/api/state")).json()
    assert s["state"] == "mining" and s["current"]["channel"]["login"] in ("a", "b")
    await c.aclose()


async def test_lists_round_trip_and_normalisation(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.put("/api/lists", json={"priority": ["Palia", "Palia"], "never": ["AION 2"],
                                        "favourites": ["KernelPanic"]})
    assert r.status_code == 200
    assert r.json() == {"priority": ["Palia"], "never": ["AION 2"], "favourites": ["kernelpanic"]}
    assert (await c.get("/api/lists")).json() == r.json()
    await c.aclose()


async def test_lists_reject_game_in_priority_and_never(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.put("/api/lists", json={"priority": ["Palia"], "never": ["Palia"], "favourites": []})
    assert r.status_code == 422
    await c.aclose()


async def test_suggestions(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    ctx.store.set_lists([], set(), ["fav_x"])
    c = await logged_in(app)
    s = (await c.get("/api/suggestions")).json()
    assert s["games"] == ["Palia"]
    assert [(c["login"], c["live"]) for c in s["channels"]] == [("a", True), ("b", True), ("fav_x", False)]
    await c.aclose()


async def test_settings_partial_update_and_validation(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.put("/api/settings", json={"mine_badges": True})
    assert r.status_code == 200 and r.json()["mine_badges"] is True and r.json()["claim_points"] is True
    assert (await c.put("/api/settings", json={"mine_badges": "yes"})).status_code == 422
    await c.aclose()


async def test_history(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.store.add_claim(NOW, "c1", "Frights", "Palia", [("Glasses", "g")])
    ctx.store.add_claim(NOW - timedelta(days=40), "c0", "Old", "X", [("R", "")])
    c = await logged_in(app)
    h = (await c.get("/api/history")).json()
    assert h["total_rewards"] == 1 and h["claims"][0]["campaign"] == "Frights"
    assert (await c.get("/api/history?days=0")).status_code == 422
    assert (await c.get("/api/history?days=60")).json()["total_rewards"] == 2
    await c.aclose()
