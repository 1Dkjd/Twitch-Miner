"""Docker (2026-10-11): a health check that fails when mining is stuck or crashed, not just when the web
page is down (Unraid's autoheal restarts an unhealthy container), and a database copy before an upgrade."""
import sqlite3
from datetime import timedelta

from apihelpers import NOW, client, make_app, runner_with_plan

from dropwatch.maintenance import BACKUP_KEEP, backup_on_upgrade
from dropwatch.runner import HEALTH_STALL
from dropwatch.store import Store


async def health(app):
    async with client(app) as c:  # no page sign-in: Docker's health check has none
        r = await c.get("/api/health/miner")
    return r.status_code, r.json()


async def test_healthy_while_ticking(tmp_path):
    app, ctx = make_app(tmp_path)
    r = await runner_with_plan(ctx.store)
    await r.safe_tick()
    ctx.service.runner = r
    assert await health(app) == (200, {"ok": True, "reason": "mining"})


async def test_unhealthy_when_ticks_stop(tmp_path):
    app, ctx = make_app(tmp_path)
    r = await runner_with_plan(ctx.store)
    await r.safe_tick()
    ctx.service.runner = r
    ctx.clock = lambda: NOW + HEALTH_STALL + timedelta(seconds=1)
    status, body = await health(app)
    assert status == 503 and body["ok"] is False and "no tick" in body["reason"]


async def test_signed_out_is_healthy_and_a_crash_is_not(tmp_path):
    app, ctx = make_app(tmp_path)  # no runner: nothing to mine is not a fault
    assert (await health(app))[0] == 200
    ctx.service.crashed = "RuntimeError"
    status, body = await health(app)
    assert status == 503 and "crashed" in body["reason"]


def test_a_new_build_backs_up_the_database_and_keeps_the_last_few(tmp_path):
    db = tmp_path / "drops.db"
    st = Store(db)
    st.set_setting("marker", "before")
    assert backup_on_upgrade(st, "0.1.0+main@aaa") is None  # first run: nothing to protect from
    st.set_setting("marker", "aaa")
    made = backup_on_upgrade(st, "0.1.0+main@bbb")
    assert made is not None and made.exists()
    copy = sqlite3.connect(made)
    assert copy.execute("SELECT value FROM settings WHERE key = 'marker'").fetchone() == ("aaa",)
    copy.close()
    assert backup_on_upgrade(st, "0.1.0+main@bbb") is None  # same build: no copy
    for b in ("ccc", "ddd", "eee"):
        backup_on_upgrade(st, f"0.1.0+main@{b}")
    assert len(list(tmp_path.glob("drops.db.before-*"))) == BACKUP_KEEP
