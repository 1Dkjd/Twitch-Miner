"""Settings › About (version, commit, uptime) and the weekly summary's chosen time zone."""
from datetime import UTC, datetime, timedelta

from apihelpers import NOW, client, make_app
from test_summaries import NONE, make

from dropwatch import version
from dropwatch.store import Store

# 18:01 in New York (EDT, UTC-4) on Sunday 11 Oct 2026 is 22:01 UTC
NY_SUN_1801 = datetime(2026, 10, 11, 22, 1, tzinfo=UTC)


def test_time_zone_defaults_to_the_servers(tmp_path):
    assert Store(tmp_path / "d.db").get_settings()["notify_weekly_tz"] == ""


def test_weekly_summary_follows_the_chosen_zone(tmp_path):
    n, clock, _ = make(tmp_path, NY_SUN_1801 - timedelta(hours=4), notify_weekly=True,
                       notify_weekly_tz="America/New_York")
    assert n.check(NONE) == []  # 18:01 UTC is only 14:01 in New York
    clock[0] = NY_SUN_1801
    (a,) = n.check(NONE)
    assert a.title == "Dropwatch: Your week"


def test_an_unknown_stored_zone_falls_back_to_the_servers(tmp_path):
    # a zone that later vanished from the tz database must not stop the summary (server zone = UTC here)
    n, clock, st = make(tmp_path, datetime(2026, 10, 11, 18, 1, tzinfo=UTC), notify_weekly=True)
    st.set_setting("notify_weekly_tz", "Mars/Olympus_Mons")
    (a,) = n.check(NONE)
    assert a.title == "Dropwatch: Your week"


async def test_api_accepts_real_zones_and_refuses_others(tmp_path):
    app, ctx = make_app(tmp_path)
    async with client(app) as c:
        await c.post("/api/login", json={"password": "correct horse"})
        r = await c.put("/api/settings", json={"notify_weekly_tz": "Europe/London"})
        assert r.status_code == 200 and r.json()["notify_weekly_tz"] == "Europe/London"
        assert (await c.put("/api/settings", json={"notify_weekly_tz": ""})).json()["notify_weekly_tz"] == ""
        for bad in ("Mars/Olympus_Mons", "../../etc/passwd", "x" * 80, "Europe", "America"):
            assert (await c.put("/api/settings", json={"notify_weekly_tz": bad})).status_code == 422, bad
    assert ctx.store.get_settings()["notify_weekly_tz"] == ""


async def test_about(tmp_path, monkeypatch):
    monkeypatch.setenv("DROPWATCH_COMMIT", "main@abc1234")
    monkeypatch.setenv("TZ", "America/New_York")
    version.build_info.cache_clear()
    app, ctx = make_app(tmp_path)
    async with client(app) as c:
        await c.post("/api/login", json={"password": "correct horse"})
        a = (await c.get("/api/about")).json()
    assert a["version"] == version.VERSION and a["version"].count(".") == 2
    assert a["commit"] == "main@abc1234"
    assert a["started_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert a["server_tz"] == "America/New_York"
    assert a["campaigns_at"] is None  # no miner running
    async with client(app) as anon:
        assert (await anon.get("/api/about")).status_code == 401


def test_commit_falls_back_to_git(monkeypatch):
    monkeypatch.delenv("DROPWATCH_COMMIT", raising=False)
    version.build_info.cache_clear()
    commit = version.build_info()
    assert commit is None or "@" in commit  # branch@sha from this checkout, None without git
    version.build_info.cache_clear()
