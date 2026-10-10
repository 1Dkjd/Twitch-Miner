import asyncio

from dropwatch.events import EventBus


async def test_fan_out_to_every_subscriber():
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish("claimed", {"reward": "x"})
    assert await a.get() == ("claimed", {"reward": "x"})
    assert await b.get() == ("claimed", {"reward": "x"})


async def test_slow_subscriber_drops_oldest_not_blocks():
    bus = EventBus(maxsize=3)
    q = bus.subscribe()
    for i in range(10):
        bus.publish("progress", {"i": i})   # must return immediately
    got = [q.get_nowait()[1]["i"] for _ in range(q.qsize())]
    assert got == [7, 8, 9]


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.publish("state", {})
    assert q.empty() and bus.subscribers == 0


async def test_publish_without_subscribers_is_fine():
    EventBus().publish("state", {})
    await asyncio.sleep(0)
