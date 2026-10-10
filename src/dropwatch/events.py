"""In-process event fan-out for the live page (SSE). Never blocks the publisher."""
from __future__ import annotations

import asyncio


class EventBus:
    def __init__(self, maxsize: int = 100):
        self._maxsize = maxsize
        self._subs: set[asyncio.Queue[tuple[str, dict]]] = set()

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def subscribe(self) -> asyncio.Queue[tuple[str, dict]]:
        q: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=self._maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[tuple[str, dict]]) -> None:
        self._subs.discard(q)

    def publish(self, kind: str, data: dict) -> None:
        for q in list(self._subs):
            if q.full():
                q.get_nowait()  # a slow client loses its oldest event, never the runner's time
            q.put_nowait((kind, data))
