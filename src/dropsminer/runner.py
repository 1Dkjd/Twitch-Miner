"""Mining loop. Owns state; never touches any UI (spec §5, §9).

Robustness rules (phase-1 final review):
- No exception escapes the loop: safe_tick() and safe_handle() catch, report
  TWITCH_UNREACHABLE and back off.
- refresh() and claims run under one lock, and each claim id is claimed at most once per run.
- Campaigns are re-fetched hourly (and after a claim), live channels every 5 minutes
  (the reference fetches inventory hourly).
- A channel that sends stream-down is excluded until stream-up or 10 minutes pass, even if
  the game directory still lists it.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .models import Campaign, LiveChannel, claimable, with_drop
from .planner import Plan, plan
from .twitch.constants import PLAY_INTERVAL
from .twitch.gql import AuthExpired, GqlError
from .twitch.pubsub import DropClaimable, DropProgress, StreamChanged, StreamDown, StreamUp, topic

log = logging.getLogger("dropsminer.runner")
FAILS_BEFORE_SWITCH = 3
STALL_TICKS = 18  # ticks are PLAY_INTERVAL (10 s) apart: resync after ~3 min of silence
EXCLUDE_FOR = timedelta(minutes=10)
REFRESH_EVERY = timedelta(minutes=5)
CAMPAIGNS_EVERY = timedelta(hours=1)
BACKOFF_START, BACKOFF_MAX = 60.0, 600.0
# GqlError covers TwitchUnreachable; the rest are unexpected response shapes from parsing.
TWITCH_ERRORS = (GqlError, KeyError, TypeError, ValueError)


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
        self._down_ids: dict[int, str] = {}
        self._override_campaign: str | None = None
        self._override_channel: str | None = None
        self.last_refresh: datetime | None = None
        self._campaigns_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._claimed: set[str] = set()
        self._backoff = 0.0

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

    async def refresh(self, *, force_campaigns: bool = False) -> None:
        async with self._lock:
            await self._refresh(force_campaigns)

    async def _refresh(self, force_campaigns: bool) -> None:
        now = self._clock()
        prefs = self._store.get_prefs()
        try:
            due = self._campaigns_at is None or now - self._campaigns_at >= CAMPAIGNS_EVERY
            if force_campaigns or due:
                self.campaigns = await self._client.campaigns()
                self._campaigns_at = now
                if await self._catch_up_claims(now):
                    self.campaigns = await self._client.campaigns()
            self.live = await self._client.live_channels(self.campaigns, prefs, now)
        except AuthExpired:
            self.watching = None
            self._set_state(State.SIGNED_OUT)
            return
        except TWITCH_ERRORS as exc:
            log.warning("Refresh failed: %s: %s", type(exc).__name__, exc)
            self._set_state(State.TWITCH_UNREACHABLE, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self.last_refresh = now
        self._excluded = {k: v for k, v in self._excluded.items() if v > now}
        usable = [c for c in self.live if c.login not in self._excluded]
        previous = self.watching
        self.plan = plan(self.campaigns, usable, prefs, now,
                         watching=previous.login if previous else None,
                         override_campaign=self._override_campaign,
                         override_channel=self._override_channel,
                         current_campaign=self.plan.current.campaign_id
                         if self.plan and self.plan.current else None)
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

    async def _catch_up_claims(self, now: datetime) -> bool:
        """Claim anything Twitch has issued a claim id for (reference can_claim). Lock held."""
        claimed = False
        for c in list(self.campaigns):
            for d in c.drops:
                if claimable(c, d, now):
                    claimed |= await self._claim(c, d.id, d.claim_id)
        return claimed

    async def _claim(self, c: Campaign, drop_id: str, claim_id: str | None) -> bool:
        """Lock held by caller. Each claim id is claimed at most once per run."""
        if not claim_id or claim_id in self._claimed:
            return False
        d = c.drop(drop_id)
        try:
            ok = await self._client.claim(claim_id)
        except TWITCH_ERRORS as exc:
            log.warning("Claim raised %s", type(exc).__name__)
            ok = False
        if ok:
            self._claimed.add(claim_id)
            info = {"campaign": c.name, "reward": ", ".join(r.name for r in d.rewards) if d else drop_id}
            self._emit("claimed", info)
            self._store.log_event("claimed", info)
            return True
        self._store.log_event("claim_failed", {"campaign": c.name, "drop": drop_id})
        return False

    async def tick(self) -> None:
        now = self._clock()
        if self._paused:
            if self.paused_until is None or now < self.paused_until:
                self._set_state(State.PAUSED)
                return
            self.resume()
        if (self.last_refresh is None or now - self.last_refresh >= REFRESH_EVERY
                or self.state == State.TWITCH_UNREACHABLE):
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
            try:
                cur = await self._client.current_drop(self.watching.id)
            except TWITCH_ERRORS as exc:
                log.info("Progress resync failed: %s", type(exc).__name__)
                cur = None
            if cur:
                await self.handle(DropProgress(cur[0], cur[1], -1))

    async def safe_tick(self) -> float:
        """One tick that never raises. Returns how long to sleep before the next one."""
        try:
            await self.tick()
        except Exception as exc:  # noqa: BLE001  the loop must survive anything
            log.exception("Tick failed")
            self._set_state(State.TWITCH_UNREACHABLE, {"error": type(exc).__name__})
            self._backoff = min(self._backoff * 2, BACKOFF_MAX) if self._backoff else BACKOFF_START
            return self._backoff
        self._backoff = 0.0
        return float(PLAY_INTERVAL)

    async def handle(self, event: object) -> None:
        if isinstance(event, DropProgress):
            self._ticks_since_progress = 0
            for i, c in enumerate(self.campaigns):
                d = c.drop(event.drop_id)
                if d is not None:
                    self.campaigns[i] = with_drop(c, replace(d, current_minutes=event.current))
            self._emit("progress", {"drop": event.drop_id, "minutes": event.current})
        elif isinstance(event, DropClaimable):
            async with self._lock:
                for c in self.campaigns:
                    if c.drop(event.drop_id) is not None:
                        await self._claim(c, event.drop_id, event.claim_id)
                        break
            await self.refresh(force_campaigns=True)
        elif isinstance(event, StreamUp):
            login = self._down_ids.pop(event.channel_id, None)
            if login:
                self._excluded.pop(login, None)
        elif isinstance(event, (StreamDown, StreamChanged)):
            if self.watching and event.channel_id == self.watching.id:
                if isinstance(event, StreamDown):
                    # the directory can list a stream for minutes after it ends: exclude it
                    self._excluded[self.watching.login] = self._clock() + EXCLUDE_FOR
                    self._down_ids[self.watching.id] = self.watching.login
                await self.refresh()

    async def safe_handle(self, event: object) -> None:
        try:
            await self.handle(event)
        except Exception as exc:  # noqa: BLE001  one bad event must not stop the rest
            log.exception("Handling %s failed", type(event).__name__)
            self._set_state(State.TWITCH_UNREACHABLE, {"error": type(exc).__name__})


async def run_cli(store) -> int:
    """`dropsminer run`: wire the real pieces and loop until Ctrl+C or the session expires."""
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

    gql = Gql(transport, lambda: session)
    r = Runner(TwitchClient(gql, session.user_id),
               Watcher(transport, lambda: session, gql), pubsub, store,
               user_id=session.user_id, emit=emit)

    async def events() -> None:
        async for ev in pubsub.events():
            await r.safe_handle(ev)

    events_task = asyncio.create_task(events())
    try:
        await r.refresh()
        while True:
            if r.state == State.SIGNED_OUT:
                break
            delay = await r.safe_tick()
            await asyncio.sleep(delay)
        print("Twitch session expired. Run: dropsminer signin")
        return 1
    finally:
        events_task.cancel()
        await pubsub.close()
        await transport.close()
