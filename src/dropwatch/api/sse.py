"""Server-sent events from the EventBus. One bounded queue per client (EventBus drops oldest)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable


async def sse_stream(bus, is_disconnected: Callable[[], Awaitable[bool]],
                     ping: float = 15.0, allowed: Callable[[], bool] = lambda: True) -> AsyncIterator[str]:
    """allowed() is checked before every event and ping: once the page session is gone (signed out here or
    from another browser, or expired) the stream ends, and the page's reconnect meets the sign-in."""
    q = bus.subscribe()
    try:
        yield ": connected\n\n"
        while not await is_disconnected() and allowed():
            try:
                kind, data = await asyncio.wait_for(q.get(), ping)
            except TimeoutError:
                if allowed():
                    yield ": ping\n\n"
                continue
            if not allowed():
                break
            yield f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
    finally:
        bus.unsubscribe(q)
