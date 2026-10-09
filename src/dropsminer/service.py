"""Run the mining loop as a startable/stoppable service (API sign-in starts it, sign-out stops it)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .events import EventBus
from .runner import Runner, State

log = logging.getLogger("dropsminer.service")


@dataclass
class Parts:
    runner: Runner
    pubsub: object
    close: Callable[[], Awaitable[None]]


def build_parts(store, session, emit) -> Parts:
    from .twitch.client import TwitchClient
    from .twitch.gql import Gql
    from .twitch.pubsub import PubSub
    from .twitch.transport import AiohttpTransport
    from .twitch.watch import Watcher

    transport = AiohttpTransport()
    pubsub = PubSub(lambda: session.access_token)
    gql = Gql(transport, lambda: session)
    runner = Runner(TwitchClient(gql, session.user_id), Watcher(transport, lambda: session, gql),
                    pubsub, store, user_id=session.user_id, emit=emit)

    async def close() -> None:
        await pubsub.close()
        await transport.close()
    return Parts(runner, pubsub, close)


class MinerService:
    def __init__(self, store, bus: EventBus, build=build_parts):
        self._store, self._bus, self._build = store, bus, build
        self._parts: Parts | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopped = asyncio.Event()
        self._stopped.set()

    @property
    def runner(self) -> Runner | None:
        return self._parts.runner if self._parts else None

    @property
    def running(self) -> bool:
        return self._parts is not None

    def _emit(self, kind: str, data: dict) -> None:
        log.info("%s %s", kind, data)
        self._bus.publish(kind, data)

    async def start(self) -> bool:
        if self._parts is not None:
            return True
        session = self._store.get_session()
        if session is None:
            return False
        self._parts = self._build(self._store, session, self._emit)
        self._stopped.clear()
        self._tasks = [asyncio.create_task(self._loop()), asyncio.create_task(self._events())]
        return True

    async def _loop(self) -> None:
        r = self._parts.runner
        await r.refresh()
        while r.state != State.SIGNED_OUT:
            delay = await r.safe_tick()
            await asyncio.sleep(delay)
        self._bus.publish("signin", {"status": "expired"})

    async def _events(self) -> None:
        pubsub = self._parts.pubsub
        if not hasattr(pubsub, "events"):
            return
        async for ev in pubsub.events():
            await self._parts.runner.safe_handle(ev)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        if self._parts is not None:
            await self._parts.close()
            self._parts = None
        self._stopped.set()

    async def wait_stopped(self) -> None:
        loop = self._tasks[0] if self._tasks else None
        if loop is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await loop
        await self.stop()
