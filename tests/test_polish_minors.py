"""Old deferred minors, fixed in the 2026-10-12 polish pass: request bodies reject unknown fields, list
entries can't be blank or huge, the password check runs off the event loop, and the live-event stream ends
when the browser's page session does."""
import asyncio
import time

from apihelpers import logged_in, make_app

from dropwatch.api.sse import sse_stream
from dropwatch.backup import restore_backup
from dropwatch.events import EventBus
from dropwatch.store import Store


async def test_request_bodies_reject_unknown_fields(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    for method, path, body in [
        ("POST", "/api/pause", {"minutes": 5, "typo": 1}),
        ("POST", "/api/mine-now", {"campaign_id": "c1", "typo": 1}),
        ("POST", "/api/channel", {"login": "someone", "typo": 1}),
        ("PUT", "/api/lists", {"priority": [], "never": [], "favourites": [], "typo": []}),
        ("PUT", "/api/notify/channels/ntfy", {"values": {}, "typo": 1}),
        ("POST", "/api/login", {"password": "correct horse", "typo": 1}),
    ]:
        r = await c.request(method, path, json=body)
        assert r.status_code == 422, (path, r.status_code, r.text)
    await c.aclose()


async def test_lists_drop_blank_entries_cap_length_and_keep_real_names_exact(tmp_path):
    app, ctx = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.put("/api/lists", json={"priority": ["Palia", "", "   "], "never": ["Dead by Daylight "],
                                        "favourites": []})
    assert r.status_code == 200, r.text
    assert r.json()["priority"] == ["Palia"]
    assert r.json()["never"] == ["Dead by Daylight "]  # Twitch's own spelling: lists match on it exactly
    r = await c.put("/api/lists", json={"priority": ["x" * 201], "never": [], "favourites": []})
    assert r.status_code == 422
    await c.aclose()


def test_restore_ignores_list_fields_a_newer_version_added(tmp_path):
    st = Store(tmp_path / "d.db")
    data = {"dropwatch_backup": 1, "lists": {"priority": ["Palia"], "never": [], "favourites": [],
                                             "something_new": ["x"]}}
    restore_backup(st, data)
    assert st.get_prefs().priority == ("Palia",)


async def test_password_check_does_not_hold_up_other_requests(tmp_path, monkeypatch):
    app, ctx = make_app(tmp_path)
    slow = 0.6

    def slow_verify(*_a, **_k):
        time.sleep(slow)  # argon2 on a slow box
        return True

    monkeypatch.setattr(Store, "verify_password", staticmethod(slow_verify))
    c = await logged_in_client(app)
    t0 = time.perf_counter()

    async def health():
        await asyncio.sleep(0.05)  # let the login start first
        await c.get("/api/health")
        return time.perf_counter() - t0

    login = asyncio.create_task(c.post("/api/login", json={"password": "correct horse"}))
    health_done = await health()
    assert (await login).status_code == 204
    assert health_done < slow - 0.2, f"health waited {health_done:.2f}s behind the password check"
    await c.aclose()


async def logged_in_client(app):
    from apihelpers import client
    return client(app)


async def test_live_events_end_when_the_page_session_does():
    bus = EventBus()
    allowed = [True]

    async def disconnected():
        return False

    gen = sse_stream(bus, disconnected, ping=0.02, allowed=lambda: allowed[0])
    assert await anext(gen) == ": connected\n\n"
    assert await asyncio.wait_for(anext(gen), 1) == ": ping\n\n"
    allowed[0] = False  # signed out (here, or "sign out everywhere else" from another browser)

    async def rest():
        return [x async for x in gen]

    # without the check the stream pings forever: fail in 1 s rather than hang
    assert await asyncio.wait_for(rest(), 1) == [] and bus.subscribers == 0
