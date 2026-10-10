from datetime import UTC, datetime

import httpx
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.api.app import AppContext, create_app
from dropwatch.events import EventBus
from dropwatch.runner import Runner
from dropwatch.store import Store

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


class FakeService:
    def __init__(self, runner=None):
        self.runner, self.started, self.stopped = runner, 0, 0

    @property
    def running(self):
        return self.runner is not None

    async def start(self):
        self.started += 1
        return self.runner is not None

    async def stop(self):
        self.stopped += 1
        self.runner = None


class FakeSignIn:
    def __init__(self):
        self.started = self.cancelled = 0
        self.state = {"status": "idle", "message": ""}

    def status(self):
        return dict(self.state)

    async def start(self):
        if self.state["status"] == "waiting":
            return None
        self.started += 1
        self.state = {"status": "waiting", "message": "", "code": "BKDQMDGP",
                      "verification_uri": "https://www.twitch.tv/activate", "expires_at": None}
        return dict(self.state)

    def cancel(self):
        self.cancelled += 1


async def runner_with_plan(store):
    r = Runner(FakeClient([camp()], [chan("a", 7), chan("b", 8)]), FakeWatcher(), FakePubSub(), store,
               user_id=42, clock=lambda: NOW)
    await r.refresh()
    return r


def make_app(tmp_path, runner=None, password="correct horse"):
    store = Store(tmp_path / "d.db")
    if password:
        store.set_password(password)
    ctx = AppContext(store=store, bus=EventBus(), service=FakeService(runner), signin=FakeSignIn(),
                     clock=lambda: NOW)
    return create_app(ctx), ctx


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def logged_in(app, password="correct horse"):
    c = client(app)
    r = await c.post("/api/login", json={"password": password})
    assert r.status_code == 204, r.text
    return c
