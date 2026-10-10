import asyncio
import json

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

from dropwatch.twitch.pubsub import (
    DropClaimable,
    DropProgress,
    PubSub,
    StreamDown,
    StreamUp,
    Viewers,
    parse_message,
    topic,
)


def test_topic_names():
    assert topic("user_drops", 42) == "user-drop-events.42"
    assert topic("stream_state", 7) == "video-playback-by-id.7"


def test_parse_drop_messages():
    t = "user-drop-events.42"
    assert parse_message(t, {"type": "drop-progress", "data": {
        "drop_id": "d", "current_progress_min": 3, "required_progress_min": 10}}) == DropProgress("d", 3, 10)
    assert parse_message(t, {"type": "drop-claim", "data": {
        "drop_id": "d", "drop_instance_id": "inst"}}) == DropClaimable("d", "inst")


def test_parse_stream_state_messages():
    t = "video-playback-by-id.7"
    assert parse_message(t, {"type": "stream-down"}) == StreamDown(7)
    assert parse_message(t, {"type": "stream-up"}) == StreamUp(7)
    assert parse_message(t, {"type": "viewcount", "viewers": 12}) == Viewers(7, 12)
    assert parse_message(t, {"type": "commercial"}) is None


async def test_listens_and_delivers_events():
    received = []

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            received.append(data)
            if data["type"] == "LISTEN":
                await ws.send_json({"type": "RESPONSE", "error": ""})
                await ws.send_json({"type": "MESSAGE", "data": {
                    "topic": "video-playback-by-id.7",
                    "message": json.dumps({"type": "stream-down"})}})
        return ws

    app = web.Application()
    app.router.add_get("/", handler)
    async with TestServer(app) as server:
        ps = PubSub(lambda: "tok", str(server.make_url("/")).replace("http", "ws"))
        ps.set_topics({"video-playback-by-id.7"})
        ev = await asyncio.wait_for(anext(ps.events()), 5)
        await ps.close()
    assert ev == StreamDown(7)
    listen = next(m for m in received if m["type"] == "LISTEN")
    assert listen["data"] == {"topics": ["video-playback-by-id.7"], "auth_token": "tok"}
