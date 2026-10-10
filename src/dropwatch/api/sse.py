"""Server-sent events from the EventBus. One bounded queue per client (EventBus drops oldest)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable


async def sse_stream(bus, is_disconnected: Callable[[], Awaitable[bool]],
                     ping: float = 15.0) -> AsyncIterator[str]:
    q = bus.subscribe()
    try:
        yield ": connected\n\n"
        while not await is_disconnected():
            try:
                kind, data = await asyncio.wait_for(q.get(), ping)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
    finally:
        bus.unsubscribe(q)
