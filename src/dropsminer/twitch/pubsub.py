"""Twitch PubSub over one websocket (reference websocket.py, MIT)."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import aiohttp

from .constants import PING_INTERVAL, PONG_TIMEOUT, PUBSUB_URL, TOPICS

log = logging.getLogger("dropsminer.pubsub")


@dataclass(frozen=True)
class DropProgress:
    drop_id: str
    current: int
    required: int


@dataclass(frozen=True)
class DropClaimable:
    drop_id: str
    claim_id: str


@dataclass(frozen=True)
class StreamUp:
    channel_id: int


@dataclass(frozen=True)
class StreamDown:
    channel_id: int


@dataclass(frozen=True)
class Viewers:
    channel_id: int
    viewers: int


@dataclass(frozen=True)
class StreamChanged:
    channel_id: int


@dataclass(frozen=True)
class PointsClaimable:
    channel_id: int
    claim_id: str


def topic(key: str, target_id: int) -> str:
    return f"{TOPICS[key]}.{target_id}"


def parse_message(topic_name: str, message: dict) -> object | None:
    prefix, _, target = topic_name.rpartition(".")
    kind = message.get("type")
    data = message.get("data") or {}
    if prefix == TOPICS["user_drops"]:
        if kind == "drop-progress":
            return DropProgress(data["drop_id"], data["current_progress_min"], data["required_progress_min"])
        if kind == "drop-claim":
            return DropClaimable(data["drop_id"], data["drop_instance_id"])
    elif prefix == TOPICS["stream_state"]:
        cid = int(target)
        if kind == "stream-up":
            return StreamUp(cid)
        if kind == "stream-down":
            return StreamDown(cid)
        if kind == "viewcount":
            return Viewers(cid, message.get("viewers", 0))
    elif prefix == TOPICS["stream_update"]:
        return StreamChanged(int(target))
    elif prefix == TOPICS["user_points"] and kind == "claim-available":
        claim = data.get("claim") or {}
        return PointsClaimable(int(claim.get("channel_id", 0)), claim.get("id", ""))
    return None


class PubSub:
    def __init__(
        self,
        token: Callable[[], str],
        url: str = PUBSUB_URL,
        *,
        ping_interval: float = PING_INTERVAL,
        pong_timeout: float = PONG_TIMEOUT,
        session_factory: Callable[[], aiohttp.ClientSession] = aiohttp.ClientSession,
    ):
        self._token, self._url = token, url
        self._ping_interval, self._pong_timeout = ping_interval, pong_timeout
        self._factory = session_factory
        self._wanted: set[str] = set()
        self._changed = asyncio.Event()
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._closing = False
        self.connected = False

    def set_topics(self, topics: set[str]) -> None:
        if topics != self._wanted:
            self._wanted = set(topics)
            self._changed.set()
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def events(self) -> AsyncIterator[object]:
        while True:
            yield await self._queue.get()

    async def close(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _send_topics(self, ws, kind: str, topics: list[str]) -> None:
        for i in range(0, len(topics), 20):
            await ws.send_json({"type": kind, "data": {"topics": topics[i:i + 20],
                                                       "auth_token": self._token()}})

    async def _run(self) -> None:
        delay = 1.0
        async with self._factory() as session:
            while not self._closing:
                try:
                    async with session.ws_connect(self._url, heartbeat=None) as ws:
                        self.connected, delay = True, 1.0
                        await self._session(ws)
                except (TimeoutError, aiohttp.ClientError, OSError) as exc:
                    log.warning("PubSub connection problem: %s", type(exc).__name__)
                finally:
                    self.connected = False
                if self._closing:
                    return
                await asyncio.sleep(delay)
                delay = min(delay * 2, 180)

    async def _session(self, ws) -> None:
        submitted: set[str] = set()
        next_ping = time.monotonic()
        pong_deadline: float | None = None
        self._changed.set()
        while True:
            now = time.monotonic()
            if now >= next_ping:
                await ws.send_json({"type": "PING"})
                next_ping, pong_deadline = now + self._ping_interval, now + self._pong_timeout
            elif pong_deadline is not None and now >= pong_deadline:
                log.warning("No PONG from PubSub; reconnecting")
                return
            if self._changed.is_set():
                self._changed.clear()
                removed, added = sorted(submitted - self._wanted), sorted(self._wanted - submitted)
                if removed:
                    await self._send_topics(ws, "UNLISTEN", removed)
                if added:
                    await self._send_topics(ws, "LISTEN", added)
                submitted = set(self._wanted)
            try:
                msg = await ws.receive(timeout=0.5)
            except TimeoutError:
                continue
            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                return
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            kind = data.get("type")
            if kind == "PONG":
                pong_deadline = None
            elif kind == "RECONNECT":
                return
            elif kind == "MESSAGE":
                t = data["data"]["topic"]
                try:
                    ev = parse_message(t, json.loads(data["data"]["message"]))
                except (KeyError, ValueError, TypeError) as exc:
                    log.warning("Unparseable PubSub message on %s: %s", t, exc)
                    continue
                if ev is not None:
                    await self._queue.put(ev)
            elif kind == "RESPONSE" and data.get("error"):
                log.warning("PubSub LISTEN error: %s", data["error"])
