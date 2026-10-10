"""Phase 3 Task 1: what the web UI needs from the API (alternatives, switch notice, next check,
Check now, and serving the built page)."""
from datetime import timedelta

import httpx
from apihelpers import NOW, FakeService, FakeSignIn, logged_in, make_app, runner_with_plan
from test_runner import FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

from dropwatch.api.app import AppContext, create_app
from dropwatch.api.views import state_view
from dropwatch.events import EventBus
from dropwatch.runner import REFRESH_EVERY, Runner
from dropwatch.store import Store
from dropwatch.twitch.pubsub import StreamDown


class ViewStore(FakeStore):
    def get_session(self):
        return None


def runner(live, clock=None):
    clock = clock or [NOW]
    return Runner(FakeClient([camp()], live), FakeWatcher(), FakePubSub(), ViewStore(), user_id=42,
                  clock=lambda: clock[0]), clock


async def test_current_lists_alternative_channels():
    r, _ = runner([chan("a", 7), chan("b", 8)])
    await r.refresh()
    cur = state_view(r, ViewStore(), NOW).current
    assert {c.login for c in cur.channels} == {"a", "b"} - {cur.channel.login}


async def test_last_switch_reported_then_expires():
    r, clock = runner([chan("a", 7), chan("b", 8)])
    await r.refresh()
    first = r.watching
    r._client.live = [ch for ch in r._client.live if ch.login != first.login]
    await r.handle(StreamDown(first.id))
    s = state_view(r, ViewStore(), clock[0])
    assert s.last_switch.from_ == first.login and s.last_switch.to == r.watching.login
    assert '"from"' in s.model_dump_json(by_alias=True)
    clock[0] += timedelta(minutes=11)
    assert state_view(r, ViewStore(), clock[0]).last_switch is None


async def test_next_check_at():
    r, _ = runner([chan("a", 7)])
    await r.refresh()
    assert state_view(r, ViewStore(), NOW).next_check_at == NOW + REFRESH_EVERY


async def test_check_now_refreshes_campaigns(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    calls = []
    real = ctx.service.runner.refresh

    async def spy(**kw):
        calls.append(kw)
        await real(**kw)
    ctx.service.runner.refresh = spy
    c = await logged_in(app)
    assert (await c.post("/api/refresh")).status_code == 204
    assert calls == [{"force_campaigns": True}]
    await c.aclose()


async def test_check_now_signed_out_conflict(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    assert (await c.post("/api/refresh")).status_code == 409
    await c.aclose()


def web_app(tmp_path):
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_bytes(b"<!doctype html><title>Dropwatch</title>")
    (web / "assets" / "app.js").write_bytes(b"console.log(1)")
    store = Store(tmp_path / "d.db")
    ctx = AppContext(store=store, bus=EventBus(), service=FakeService(), signin=FakeSignIn(),
                     clock=lambda: NOW)
    return create_app(ctx, web_dir=web)


async def test_serves_index_and_assets(tmp_path):
    app = web_app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/")
        assert r.status_code == 200 and "<title>Dropwatch</title>" in r.text
        assert (await c.get("/assets/app.js")).text == "console.log(1)"
        assert "<title>Dropwatch</title>" in (await c.get("/priorities")).text  # SPA fallback


async def test_spa_fallback_not_for_api(tmp_path):
    app = web_app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/nope")).status_code == 404
        assert (await c.get("/api/state")).status_code == 401


def test_no_web_dir_means_api_only(tmp_path):
    ctx = AppContext(store=None, bus=None, service=None, signin=None)
    app = create_app(ctx, web_dir=tmp_path / "missing")
    assert not any(getattr(r, "path", "") == "/{path:path}" for r in app.router.routes)


async def test_page_server_never_escapes_web_dir(tmp_path):
    app = web_app(tmp_path)  # d.db sits next to dist/
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for path in ("/%2e%2e/d.db", "/..%2fd.db", "/assets/..%2f..%2fd.db"):
            r = await c.get(path)
            assert b"SQLite" not in r.content, path
