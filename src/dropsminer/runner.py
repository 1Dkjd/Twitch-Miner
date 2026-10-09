"""Mining loop. Owns state; never touches any UI (spec §5, §9)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .models import Campaign, LiveChannel, claimable, with_drop
from .planner import Plan, plan
from .twitch.constants import WATCH_INTERVAL
from .twitch.gql import AuthExpired, TwitchUnreachable
from .twitch.pubsub import DropClaimable, DropProgress, StreamChanged, StreamDown, topic

log = logging.getLogger("dropsminer.runner")
FAILS_BEFORE_SWITCH = 3
STALL_TICKS = 3
EXCLUDE_FOR = timedelta(minutes=10)
REFRESH_EVERY = timedelta(minutes=5)


class State(StrEnum):
    MINING = "mining"
    SWITCHED = "switched"
    PAUSED = "paused"
    IDLE = "idle"
    SIGNED_OUT = "signed_out"
    TWITCH_UNREACHABLE = "twitch_unreachable"


class Runner:
    def __init__(self, client, watcher, pubsub, store, *, user_id: int,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 emit: Callable[[str, dict], None] = lambda k, d: None):
        self._client, self._watcher, self._pubsub, self._store = client, watcher, pubsub, store
        self._user_id, self._clock, self._emit = user_id, clock, emit
        self.state: State = State.IDLE
        self.plan: Plan | None = None
        self.campaigns: list[Campaign] = []
        self.live: list[LiveChannel] = []
        self.watching: LiveChannel | None = None
        self.paused_until: datetime | None = None
        self._paused = False
        self._fails = 0
        self._ticks_since_progress = 0
        self._excluded: dict[str, datetime] = {}
        self._override_campaign: str | None = None
        self._override_channel: str | None = None
        self.last_refresh: datetime | None = None

    # --- commands
    def pause(self, until: datetime | None) -> None:
        self._paused, self.paused_until = True, until
        self._set_state(State.PAUSED, {"until": until.isoformat() if until else None})

    def resume(self) -> None:
        self._paused, self.paused_until = False, None
        self._set_state(State.MINING if self.watching else State.IDLE)

    def mine_now(self, campaign_id: str) -> None:
        self._override_campaign = campaign_id

    def use_channel(self, login: str) -> None:
        self._override_channel = login

    # --- core
    def _set_state(self, state: State, extra: dict | None = None) -> None:
        if state != self.state or extra:
            self.state = state
            data = {"state": str(state), **(extra or {})}
            self._emit("state", data)
            self._store.log_event("state", data)

    async def refresh(self) -> None:
        now = self._clock()
        prefs = self._store.get_prefs()
        try:
            self.campaigns = await self._client.campaigns()
            await self._catch_up_claims(now)
            self.live = await self._client.live_channels(self.campaigns, prefs, now)
        except AuthExpired:
            self.watching = None
            self._set_state(State.SIGNED_OUT)
            return
        except TwitchUnreachable as exc:
            self._set_state(State.TWITCH_UNREACHABLE, {"error": str(exc)})
            return
        self.last_refresh = now
        self._excluded = {k: v for k, v in self._excluded.items() if v > now}
        usable = [c for c in self.live if c.login not in self._excluded]
        previous = self.watching
        self.plan = plan(self.campaigns, usable, prefs, now,
                         watching=previous.login if previous else None,
                         override_campaign=self._override_campaign,
                         override_channel=self._override_channel)
        cur = self.plan.current
        self.watching = next((c for c in usable if cur and c.login == cur.channel_login), None)
        topics = {topic("user_drops", self._user_id), topic("user_notifications", self._user_id)}
        if self.watching:
            topics |= {topic("stream_state", self.watching.id), topic("stream_update", self.watching.id)}
        self._pubsub.set_topics(topics)
        if self._paused:
            return
        if self.watching is None:
            self._set_state(State.IDLE)
        elif previous and previous.login != self.watching.login:
            self._fails = 0
            info = {"from": previous.login, "to": self.watching.login}
            self._emit("switched", info)
            self._store.log_event("switched", info)
            self._set_state(State.SWITCHED, info)
        else:
            self._set_state(State.MINING)

    async def _catch_up_claims(self, now: datetime) -> None:
        for c in list(self.campaigns):
            for d in c.drops:
                if claimable(c, d, now) and d.current_minutes >= d.required_minutes:
                    await self._claim(c, d.id, d.claim_id)

    async def _claim(self, c: Campaign, drop_id: str, claim_id: str | None) -> None:
        if not claim_id:
            return
        d = c.drop(drop_id)
        if await self._client.claim(claim_id):
            info = {"campaign": c.name, "reward": ", ".join(r.name for r in d.rewards) if d else drop_id}
            self._emit("claimed", info)
            self._store.log_event("claimed", info)
            self.campaigns = await self._client.campaigns()
        else:
            self._store.log_event("claim_failed", {"campaign": c.name, "drop": drop_id})

    async def tick(self) -> None:
        now = self._clock()
        if self._paused:
            if self.paused_until is None or now < self.paused_until:
                self._set_state(State.PAUSED)
                return
            self.resume()
        if self.last_refresh is None or now - self.last_refresh >= REFRESH_EVERY:
            await self.refresh()
        if self.watching is None:
            return
        if await self._watcher.send(self.watching, now):
            self._fails = 0
        else:
            self._fails += 1
            if self._fails >= FAILS_BEFORE_SWITCH:
                bad = self.watching.login
                self._watcher.forget(bad)
                self._excluded[bad] = now + EXCLUDE_FOR
                self._store.log_event("channel_dropped", {"channel": bad})
                self._fails = 0
                await self.refresh()
                return
        self._ticks_since_progress += 1
        if self._ticks_since_progress >= STALL_TICKS and self.watching:
            cur = await self._client.current_drop(self.watching.id)
            if cur:
                await self.handle(DropProgress(cur[0], cur[1], -1))

    async def handle(self, event: object) -> None:
        if isinstance(event, DropProgress):
            self._ticks_since_progress = 0
            for i, c in enumerate(self.campaigns):
                d = c.drop(event.drop_id)
                if d is not None:
                    self.campaigns[i] = with_drop(c, replace(d, current_minutes=event.current))
            self._emit("progress", {"drop": event.drop_id, "minutes": event.current})
        elif isinstance(event, DropClaimable):
            for c in self.campaigns:
                if c.drop(event.drop_id) is not None:
                    await self._claim(c, event.drop_id, event.claim_id)
                    break
            await self.refresh()
        elif isinstance(event, (StreamDown, StreamChanged)):
            if self.watching and event.channel_id == self.watching.id:
                if isinstance(event, StreamDown):
                    self.live = [c for c in self.live if c.id != event.channel_id]
                await self.refresh()


async def run_cli(store) -> int:
    """`dropsminer run`: wire the real pieces and loop until Ctrl+C."""
    from .twitch.client import TwitchClient
    from .twitch.gql import Gql
    from .twitch.pubsub import PubSub
    from .twitch.transport import AiohttpTransport
    from .twitch.watch import Watcher

    session = store.get_session()
    if session is None:
        print("Not signed in. Run: dropsminer signin")
        return 1
    transport = AiohttpTransport()
    pubsub = PubSub(lambda: session.access_token)

    def emit(kind: str, data: dict) -> None:
        log.info("%s %s", kind, data)

    r = Runner(TwitchClient(Gql(transport, lambda: session), session.user_id),
               Watcher(transport, lambda: session), pubsub, store,
               user_id=session.user_id, emit=emit)

    async def events() -> None:
        async for ev in pubsub.events():
            await r.handle(ev)

    events_task = asyncio.create_task(events())
    try:
        await r.refresh()
        while r.state != State.SIGNED_OUT:
            await r.tick()
            await asyncio.sleep(WATCH_INTERVAL)
        print("Twitch session expired. Run: dropsminer signin")
        return 1
    finally:
        events_task.cancel()
        await pubsub.close()
        await transport.close()
