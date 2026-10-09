from datetime import timedelta

from apihelpers import NOW, logged_in, make_app, runner_with_plan


async def test_commands_while_signed_out_conflict(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    for path, body in [("/api/pause", {"minutes": 30}), ("/api/resume", {}),
                       ("/api/mine-now", {"campaign_id": "c1"}), ("/api/channel", {"login": "a"})]:
        assert (await c.post(path, json=body)).status_code == 409, path
    await c.aclose()


async def test_pause_validation_and_effect(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    c = await logged_in(app)
    for bad in (0, -5, 1441):
        assert (await c.post("/api/pause", json={"minutes": bad})).status_code == 422
    assert (await c.post("/api/pause", json={"minutes": 30})).status_code == 204
    assert ctx.service.runner.paused_until == NOW + timedelta(minutes=30)
    assert (await c.post("/api/resume")).status_code == 204
    assert ctx.service.runner.paused_until is None
    assert (await c.post("/api/pause", json={"minutes": None})).status_code == 204
    assert ctx.service.runner.state == "paused" and ctx.service.runner.paused_until is None
    await c.aclose()


async def test_mine_now_unknown_and_known(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    c = await logged_in(app)
    assert (await c.post("/api/mine-now", json={"campaign_id": "nope"})).status_code == 404
    assert (await c.post("/api/mine-now", json={"campaign_id": "c1"})).status_code == 204
    assert ctx.service.runner.plan.current.campaign_id == "c1"
    await c.aclose()


async def test_channel_override(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    other = "b" if ctx.service.runner.watching.login == "a" else "a"
    c = await logged_in(app)
    assert (await c.post("/api/channel", json={"login": "not live"})).status_code == 422
    assert (await c.post("/api/channel", json={"login": "nobody"})).status_code == 404
    assert (await c.post("/api/channel", json={"login": other.upper()})).status_code == 204
    assert ctx.service.runner.watching.login == other
    await c.aclose()
