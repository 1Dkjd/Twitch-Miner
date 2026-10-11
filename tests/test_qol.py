"""Pre-Docker QoL (asked for 2026-10-11): the page learns when Dropwatch was updated, History counts channel
points, and Settings lists the browsers signed in to the page."""
from datetime import timedelta

from apihelpers import NOW, client, make_app, runner_with_plan
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan
from test_summaries import NONE
from test_summaries import make as notifier

from dropwatch import version
from dropwatch.runner import Runner
from dropwatch.store import Store
from dropwatch.twitch.pubsub import PointsEarned


# --- 1. "Dropwatch was updated"
async def test_state_carries_the_running_build(tmp_path, monkeypatch):
    monkeypatch.setenv("DROPWATCH_COMMIT", "main@abc1234")
    version.build_info.cache_clear()
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    async with client(app) as c:
        await c.post("/api/login", json={"password": "correct horse"})
        assert (await c.get("/api/state")).json()["build"] == f"{version.VERSION}+main@abc1234"
    version.build_info.cache_clear()


# --- 3. points
async def test_every_points_gain_is_kept_for_history(tmp_path):
    st = Store(tmp_path / "d.db")
    r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    for reason, pts in (("WATCH", 10), ("WATCH", 10), ("CLAIM", 50), ("WATCH_STREAK", 350)):
        await r.handle(PointsEarned(7, reason, pts))
    assert st.points_since(NOW - timedelta(days=1)) == {"points": 420, "chests": 1}
    assert st.points_since(NOW + timedelta(minutes=1)) == {"points": 0, "chests": 0}


async def test_history_reports_points_for_the_period(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.store.add_points(NOW - timedelta(days=2), "a", "WATCH", 10)
    ctx.store.add_points(NOW - timedelta(days=2), "a", "CLAIM", 50)
    ctx.store.add_points(NOW - timedelta(days=40), "a", "CLAIM", 50)  # outside 30 days
    async with client(app) as c:
        await c.post("/api/login", json={"password": "correct horse"})
        h = (await c.get("/api/history?days=30")).json()
    assert h["points"] == {"points": 60, "chests": 1}


def test_the_weekly_summary_mentions_points(tmp_path):
    from datetime import UTC, datetime
    sun = datetime(2026, 10, 11, 18, 1, tzinfo=UTC)
    n, clock, st = notifier(tmp_path, sun, notify_weekly=True)
    st.add_points(sun - timedelta(days=1), "a", "WATCH", 1180)
    st.add_points(sun - timedelta(days=1), "a", "CLAIM", 50)
    (a,) = n.check(NONE)
    assert "1,230 channel points (1 chest)" in a.body


# --- 5. signed-in browsers
async def test_sessions_list_marks_this_browser_and_can_sign_out_the_others(tmp_path):
    app, ctx = make_app(tmp_path)
    phone = client(app)
    await phone.post("/api/login", json={"password": "correct horse"},
                     headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"})
    async with client(app) as pc:
        await pc.post("/api/login", json={"password": "correct horse"},
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0"})
        rows = (await pc.get("/api/sessions")).json()["sessions"]
        assert len(rows) == 2
        mine = [r for r in rows if r["current"]]
        assert len(mine) == 1 and "Windows" in mine[0]["device"]
        other = next(r for r in rows if not r["current"])
        assert "iPhone" in other["device"] and other["id"] and "token" not in str(rows).lower()
        assert (await pc.post("/api/sessions/sign-out-others")).status_code == 204
        assert (await phone.get("/api/state")).status_code == 401  # the phone is signed out
        assert (await pc.get("/api/sessions")).json()["sessions"][0]["current"] is True
        assert len((await pc.get("/api/sessions")).json()["sessions"]) == 1
    await phone.aclose()


async def test_one_browser_can_be_signed_out(tmp_path):
    app, ctx = make_app(tmp_path)
    phone = client(app)
    await phone.post("/api/login", json={"password": "correct horse"})
    async with client(app) as pc:
        await pc.post("/api/login", json={"password": "correct horse"})
        other = next(r for r in (await pc.get("/api/sessions")).json()["sessions"] if not r["current"])
        assert (await pc.delete(f"/api/sessions/{other['id']}")).status_code == 204
        assert (await pc.delete("/api/sessions/nope")).status_code == 404
    assert (await phone.get("/api/state")).status_code == 401
    await phone.aclose()


def test_sign_ins_from_before_the_list_say_so():
    from dropwatch.api.app import _device
    assert _device("") == "Older sign-in (no details kept)"
    assert _device("Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0") == "Firefox on Linux"



def test_a_week_with_points_but_no_claims_is_not_called_quiet(tmp_path):
    from datetime import UTC, datetime
    sun = datetime(2026, 10, 11, 18, 1, tzinfo=UTC)
    n, clock, st = notifier(tmp_path, sun, notify_weekly=True)
    st.add_points(sun - timedelta(days=1), "a", "WATCH", 300)
    (a,) = n.check(NONE)
    assert "quiet" not in a.body and "300 channel points" in a.body
