"""Docker (2026-10-11): a health check that fails when mining is stuck or crashed, not just when the web
page is down (the watchdog exits so the restart policy brings it back), and a database copy before an
upgrade."""
import os
import sqlite3
import stat
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
    assert await health(app) == (200, {"ok": True})  # review fix: nothing else, it needs no sign-in


async def test_unhealthy_when_ticks_stop(tmp_path):
    app, ctx = make_app(tmp_path)
    r = await runner_with_plan(ctx.store)
    await r.safe_tick()
    ctx.service.runner = r
    ctx.clock = lambda: NOW + HEALTH_STALL + timedelta(seconds=1)
    assert await health(app) == (503, {"ok": False})


async def test_signed_out_is_healthy_and_a_crash_is_not(tmp_path):
    app, ctx = make_app(tmp_path)  # no runner: nothing to mine is not a fault
    assert (await health(app))[0] == 200
    ctx.service.crashed = "RuntimeError"
    assert await health(app) == (503, {"ok": False})


def old_db(path, last_build=None):
    """A database as main left it: web_sessions with two columns, a page password, maybe a last_build."""
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("CREATE TABLE web_sessions (token_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL)")
    db.execute("INSERT INTO settings VALUES ('page_password_hash', 'x')")
    if last_build:
        db.execute("INSERT INTO settings VALUES ('last_build', ?)", (last_build,))
    db.commit()
    db.close()


def test_the_copy_is_taken_before_the_store_changes_the_database(tmp_path):
    # review fix: the copy used to be taken after Store() had already added columns, so it couldn't roll back
    path = tmp_path / "drops.db"
    old_db(path, "0.1.0+main@aaa")
    made = backup_on_upgrade(path, "0.1.0+main@bbb")
    Store(path)  # migrates the live file afterwards
    cols = [r[1] for r in sqlite3.connect(made).execute("PRAGMA table_info(web_sessions)")]
    assert cols == ["token_hash", "expires_at"]
    if os.name == "posix":
        assert stat.S_IMODE(made.stat().st_mode) == 0o600  # holds the Twitch token, like drops.db


def test_a_database_that_never_recorded_a_build_is_copied_too(tmp_path):
    # review fix: the first start of a build that records last_build is the riskiest upgrade
    path = tmp_path / "drops.db"
    old_db(path)
    assert backup_on_upgrade(path, "0.1.0+main@bbb") is not None


def test_no_copy_for_a_new_install_or_the_same_build(tmp_path):
    path = tmp_path / "drops.db"
    assert backup_on_upgrade(path, "0.1.0+main@aaa") is None  # nothing there yet
    old_db(path, "0.1.0+main@aaa")
    assert backup_on_upgrade(path, "0.1.0+main@aaa") is None


def test_only_the_newest_copies_are_kept(tmp_path):
    path = tmp_path / "drops.db"
    old_db(path, "0.1.0+main@aaa")
    for b in ("bbb", "ccc", "ddd", "eee"):
        backup_on_upgrade(path, f"0.1.0+main@{b}")
    assert len(list(tmp_path.glob("drops.db.before-*"))) == BACKUP_KEEP


def test_a_failed_copy_never_stops_the_miner(tmp_path, monkeypatch):
    from dropwatch import maintenance
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(maintenance.sqlite3, "connect", boom)
    assert maintenance.safe_backup_on_upgrade(tmp_path / "drops.db", "x") is None


async def test_the_watchdog_exits_only_after_two_bad_checks_in_a_row(tmp_path):
    from dropwatch.maintenance import Watchdog
    exits = []
    state = {"ok": True}
    dog = Watchdog(lambda: (state["ok"], "x"), exit=lambda code: exits.append(code))
    dog.check()
    state["ok"] = False
    dog.check()
    assert exits == []  # one bad check could be a moment's hiccup
    state["ok"] = True
    dog.check()
    state["ok"] = False
    dog.check()
    assert exits == []  # not consecutive
    dog.check()
    assert exits == [3]


def test_health_logic_is_shared(tmp_path):
    from types import SimpleNamespace

    from dropwatch.maintenance import miner_health
    ok, _ = miner_health(SimpleNamespace(crashed=None, runner=None), NOW)
    assert ok
    bad, why = miner_health(SimpleNamespace(crashed="KeyError", runner=None), NOW)
    assert not bad and "crashed" in why
    late = NOW - HEALTH_STALL - timedelta(seconds=1)
    stuck = SimpleNamespace(crashed=None, runner=SimpleNamespace(last_tick=late))
    assert miner_health(stuck, NOW)[0] is False
