import asyncio
import json

from dropsminer.api.sse import sse_stream
from dropsminer.events import EventBus


async def test_stream_formats_events_and_pings():
    bus = EventBus()
    gone = asyncio.Event()

    async def disconnected():
        return gone.is_set()

    gen = sse_stream(bus, disconnected, ping=0.05)
    assert await anext(gen) == ": connected\n\n"
    bus.publish("claimed", {"reward": "Glasses"})
    chunk = await anext(gen)
    head, data = chunk.strip().split("\n")
    assert head == "event: claimed" and json.loads(data[len("data: "):]) == {"reward": "Glasses"}
    assert await asyncio.wait_for(anext(gen), 1) == ": ping\n\n"
    gone.set()
    await gen.aclose()
    assert bus.subscribers == 0


async def test_stream_ends_when_client_disconnects():
    bus = EventBus()

    async def disconnected():
        return True

    chunks = [c async for c in sse_stream(bus, disconnected, ping=0.01)]
    assert chunks == [": connected\n\n"] and bus.subscribers == 0
