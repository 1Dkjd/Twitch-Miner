import asyncio

from test_runner import NOW, FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

from dropsminer.events import EventBus
from dropsminer.runner import Runner, State
from dropsminer.service import MinerService, Parts
from dropsminer.twitch.session import TwitchSession

S = TwitchSession("tok", 42, "me", "dev", "cid", "sess")


class SessionStore(FakeStore):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def get_session(self):
        return self.session


def builder(closed):
    def build(store, session, emit):
        r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), store,
                   user_id=session.user_id, clock=lambda: NOW, emit=emit)

        async def close():
            closed.append(True)
        return Parts(r, FakePubSub(), close)
    return build


async def test_start_without_session_returns_false():
    svc = MinerService(SessionStore(None), EventBus(), build=builder([]))
    assert await svc.start() is False and svc.runner is None


async def test_start_runs_and_publishes_then_stop_closes():
    closed = []
    bus = EventBus()
    q = bus.subscribe()
    svc = MinerService(SessionStore(S), bus, build=builder(closed))
    assert await svc.start() is True
    kind, data = await asyncio.wait_for(q.get(), 2)
    assert kind == "state" and data["state"] == "mining"
    assert svc.running and svc.runner.state == State.MINING
    await svc.stop()
    assert closed == [True] and not svc.running and svc.runner is None


async def test_start_twice_is_noop():
    svc = MinerService(SessionStore(S), EventBus(), build=builder([]))
    assert await svc.start()
    first = svc.runner
    assert await svc.start()
    assert svc.runner is first
    await svc.stop()
