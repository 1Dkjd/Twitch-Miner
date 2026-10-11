"""Pre-Docker LAN hardening: login limiter, Host check, private schema, idle "first in line"."""
from datetime import timedelta

import httpx
from apihelpers import NOW, client, make_app
from test_planner import PALIA, PHAS, ch, mk

from dropwatch.api.app import create_app
from dropwatch.models import Prefs
from dropwatch.planner import plan


def at(ctx, minutes):
    ctx.clock = lambda: NOW + timedelta(minutes=minutes)


async def test_login_locks_after_five_wrong_passwords_then_reopens(tmp_path):
    app, ctx = make_app(tmp_path)
    async with client(app) as c:
        for _ in range(5):
            assert (await c.post("/api/login", json={"password": "nope nope"})).status_code == 401
        r = await c.post("/api/login", json={"password": "correct horse"})  # even the right one waits
        assert r.status_code == 429 and "dm_session" not in r.cookies
        assert int(r.headers["retry-after"]) > 0
        at(ctx, 16)  # the window has passed
        assert (await c.post("/api/login", json={"password": "correct horse"})).status_code == 204


async def test_right_password_clears_the_count(tmp_path):
    app, _ = make_app(tmp_path)
    async with client(app) as c:
        for _ in range(4):
            await c.post("/api/login", json={"password": "nope nope"})
        assert (await c.post("/api/login", json={"password": "correct horse"})).status_code == 204
        for _ in range(4):
            assert (await c.post("/api/login", json={"password": "nope nope"})).status_code == 401


async def test_limit_is_per_address(tmp_path):
    app, _ = make_app(tmp_path)
    other = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("10.0.0.9", 1)),
                              base_url="http://127.0.0.1")
    async with client(app) as c, other:
        for _ in range(5):
            await c.post("/api/login", json={"password": "nope nope"})
        assert (await c.post("/api/login", json={"password": "nope nope"})).status_code == 429
        assert (await other.post("/api/login", json={"password": "correct horse"})).status_code == 204


def hosted(app, host):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{host}")


async def test_host_check_allows_addresses_and_localhost(tmp_path):
    app, _ = make_app(tmp_path)
    for host in ("127.0.0.1:5810", "192.168.1.10:5810", "[::1]:5810", "localhost:5810", "dw.localhost"):
        async with hosted(app, host) as c:
            assert (await c.get("/api/health")).status_code == 200, host


async def test_host_check_refuses_other_names(tmp_path):
    # a page on evil.example whose DNS later points at the LAN box (DNS rebinding) arrives with
    # Host: evil.example; refusing it keeps first-run setup and login out of its reach
    app, ctx = make_app(tmp_path, password=None)
    async with hosted(app, "evil.example:5810") as c:
        r = await c.post("/api/setup", json={"password": "attacker pw"})
        assert r.status_code == 400 and "DROPWATCH_HOSTS" in r.text
    assert not ctx.store.has_password()


async def test_named_hosts_are_allowed(tmp_path):
    _, ctx = make_app(tmp_path)
    app = create_app(ctx, hosts=["Tower", "dropwatch.home.lan"])
    for host in ("tower:5810", "dropwatch.home.lan"):
        async with hosted(app, host) as c:
            assert (await c.get("/api/health")).status_code == 200, host
    async with hosted(app, "other.lan") as c:
        assert (await c.get("/api/health")).status_code == 400


async def test_star_turns_the_host_check_off(tmp_path):
    _, ctx = make_app(tmp_path)
    app = create_app(ctx, hosts=["*"])
    async with hosted(app, "anything.example") as c:
        assert (await c.get("/api/health")).status_code == 200


async def test_schema_is_not_served(tmp_path):
    app, _ = make_app(tmp_path)
    async with client(app) as c:
        r = await c.get("/openapi.json")
        assert r.status_code == 404 or "paths" not in r.text
    assert "/api/state" in app.openapi()["paths"]  # still built for `dropwatch openapi`


def test_idle_plan_names_what_is_first_in_line(now):
    soon = mk(now, "soon", PHAS, end_h=5)
    later = mk(now, "later", PALIA, end_h=200)
    p = plan([later, soon], [], Prefs(), now)  # nobody live
    assert p.current is None
    assert p.waiting == ("soon", "later")


def test_waiting_follows_priority_and_skips_never_and_unlinked(now):
    soon = mk(now, "soon", PHAS, end_h=5)
    later = mk(now, "later", PALIA, end_h=200)
    unlinked = mk(now, "unl", PHAS, linked=False)
    p = plan([later, soon, unlinked], [], Prefs(priority=("Palia",)), now)
    assert p.waiting == ("later", "soon")
    p = plan([later, soon], [], Prefs(never=("Palia",)), now)
    assert p.waiting == ("soon",)


def test_waiting_excludes_what_can_be_mined(now):
    a = mk(now, "a", PHAS)
    b = mk(now, "b", PALIA)
    p = plan([a, b], [ch("x", PHAS)], Prefs(), now)
    assert p.current.campaign_id == "a" and p.waiting == ("b",)
