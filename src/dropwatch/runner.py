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

from .models import (
    CLAIM_GRACE,
    Campaign,
    LiveChannel,
    campaign_active,
    campaign_minutes_needed,
    claimable,
    with_drop,
)
from .planner import Plan, plan, qualifies
from .twitch.constants import PLAY_INTERVAL
from .twitch.gql import AuthExpired, GqlError
from .twitch.pubsub import (
    DropClaimable,
    DropProgress,
    PointsClaimable,
    StreamChanged,
    StreamDown,
    StreamUp,
    topic,
)

log = logging.getLogger("dropwatch.runner")
FAILS_BEFORE_SWITCH = 9  # ticks are 10 s apart: ~90 s of failed playback before excluding
STALL_TICKS = 18  # ticks are PLAY_INTERVAL (10 s) apart: resync after ~3 min of silence
EXCLUDE_FOR = timedelta(minutes=10)
REFRESH_EVERY = timedelta(minutes=5)
CAMPAIGNS_EVERY = timedelta(hours=1)  # default; Settings' campaigns_every_minutes overrides it
CLAIM_WAIT = timedelta(hours=1)  # force campaign re-fetches this long; the hourly fetch covers the rest
BACKOFF_START, BACKOFF_MAX = 60.0, 600.0
# spec §4 (2026-10-10): an unknown account link that earns nothing for 10 minutes of good playback
LINK_PROBE_TICKS = 60  # ticks are PLAY_INTERVAL (10 s) apart
MAYBE_UNLINKED_FOR = timedelta(hours=6)
# earning doesn't prove the link: Twitch's inventory does, once it lists the campaign (ER ESPORTS DROPS,
# 2026-10-10: an hour of counted minutes, then isAccountConnected false and no reward)
LINK_RECHECK = timedelta(minutes=10)
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
        self._awaiting_claim: dict[str, datetime] = {}  # drop id -> stop forcing re-fetches at
        self._gave_up_claim: set[str] = set()
        self._refresh_backoff = 0.0
        self._retry_refresh_at: datetime | None = None
        self.last_switch: dict | None = None  # {"from", "to", "at"}
        self._link_probe: dict[str, tuple[int, int]] = {}  # campaign -> (good ticks, minutes at start)
        self._link_recheck: dict[str, datetime] = {}  # unknown-link campaign -> campaigns last re-read for it
        self.maybe_unlinked: dict[str, datetime] = {}  # campaign -> marked at
        self._mined_on: dict[str, str] = {}  # campaign -> channel last watched for it (History details)

    @property
    def next_check_at(self) -> datetime | None:
        if self.state == State.TWITCH_UNREACHABLE and self._retry_refresh_at is not None:
            return self._retry_refresh_at
        return self.last_refresh + REFRESH_EVERY if self.last_refresh else None

    @property
    def campaigns_at(self) -> datetime | None:
        return self._campaigns_at

    @property
    def catalog_status(self):
        """(ok|stale|unreachable, since) when campaigns come from the catalogue, else None."""
        catalog = getattr(self._client, "catalog", None)
        if catalog is None or not getattr(catalog, "used", True):
            return None
        return catalog.status

    # --- commands
    def pause(self, until: datetime | None) -> None:
        self._paused, self.paused_until = True, until
        self._set_state(State.PAUSED, {"until": until.isoformat() if until else None})

    def resume(self) -> None:
        self._paused, self.paused_until = False, None
        self._set_state(State.MINING if self.watching else State.IDLE)

    def mine_now(self, campaign_id: str) -> None:
        self._override_campaign = campaign_id
        # "Mine now" on a may-need-linking campaign means "I linked it, try again"
        self.maybe_unlinked.pop(campaign_id, None)
        self._link_probe.pop(campaign_id, None)

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
            due = (self._campaigns_at is None or now - self._campaigns_at >= self._campaigns_every()
                   or bool(self._awaiting_claim))
            if force_campaigns or due:
                self.campaigns = await self._client.campaigns()
                self._campaigns_at = now
                if await self._catch_up_claims(now):
                    self.campaigns = await self._client.campaigns()
                self._settle_awaiting(now)
            self.live = await self._client.live_channels(self.campaigns, prefs, now)
            if (record := getattr(self._store, "record_seen", None)) is not None:
                record([(c.login, c.game_name) for c in self.live], now)
        except AuthExpired:
            self.watching = None
            self._set_state(State.SIGNED_OUT)
            return
        except TWITCH_ERRORS as exc:
            log.warning("Refresh failed: %s: %s", type(exc).__name__, exc)
            self._refresh_backoff = (min(self._refresh_backoff * 2, BACKOFF_MAX)
                                     if self._refresh_backoff else BACKOFF_START)
            self._retry_refresh_at = now + timedelta(seconds=self._refresh_backoff)
            self._set_state(State.TWITCH_UNREACHABLE, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self.last_refresh = now
        self._refresh_backoff, self._retry_refresh_at = 0.0, None
        self._bookkeeping(now, prefs)
        self._plan(now, prefs)
        await self._claim_waiting_points()

    def _bookkeeping(self, now: datetime, prefs) -> None:
        """History's campaign log and pin pruning: a failure is logged, never a reason to stop planning."""
        for step in (self._forget_ended_pins, lambda n: self._log_campaigns(n, prefs)):
            try:
                step(now)
            except Exception as exc:  # noqa: BLE001 - bookkeeping must never stop mining
                log.warning("History bookkeeping failed: %s: %s", type(exc).__name__, exc)

    def _log_campaigns(self, now: datetime, prefs) -> None:
        """Keep History's "Missed" able to say why: the latest view of every active campaign."""
        log = getattr(self._store, "log_campaigns", None)
        if log is None:
            return
        rows = []
        for c in self.campaigns:
            if not campaign_active(c, now):
                if c.ends_at <= now < c.ends_at + CLAIM_GRACE and hasattr(self._store, "update_log_rewards"):
                    self._store.update_log_rewards(c.id, [{"name": r.name, "image_url": r.image_url,
                                                           "claimed": d.claimed}
                                                          for d in c.drops for r in d.rewards])
                continue
            left = (c.ends_at - now).total_seconds() / 60
            rows.append({
                "id": c.id, "name": c.name, "game": c.game.name, "box_art_url": c.game.box_art_url,
                "link_url": c.link_url, "ends_at": c.ends_at, "linked": c.linked,
                "badge": c.has_badge_or_emote,
                "rewards": [{"name": r.name, "image_url": r.image_url, "claimed": d.claimed}
                            for d in c.drops for r in d.rewards],
                "impossible": campaign_minutes_needed(c, now) > left,
                "never": c.game.name in prefs.never, "priority": c.game.name in prefs.priority,
                "pinned": c.id in prefs.pins, "live": any(qualifies(c, ch) for ch in self.live),
                "watched": max((d.current_minutes for d in c.drops), default=0),
            })
        log(now, rows)

    def _forget_ended_pins(self, now: datetime) -> None:
        """A pin lasts as long as its campaign: drop it once the campaign is known to have ended (listed and
        past its end, or logged as ended). A pin whose campaign is just missing from a short list stays."""
        get = getattr(self._store, "get_pins", None)
        if get is None:
            return
        pins = get()
        listed = {c.id: c for c in self.campaigns}
        ended_in_log = getattr(self._store, "ended_campaign_ids", lambda ids, at: set())(pins, now)

        def ended(cid: str) -> bool:
            c = listed.get(cid)
            return c.ends_at <= now if c is not None else cid in ended_in_log

        if (kept := [p for p in pins if not ended(p)]) != pins:
            self._store.set_pins(kept)

    async def replan(self) -> None:
        """Re-decide from what is already known (lists or an override changed): no Twitch calls."""
        async with self._lock:
            self._plan(self._clock(), self._store.get_prefs())

    def _plan(self, now: datetime, prefs) -> None:
        """Lock held. Plan from the cached campaigns and live channels, then act on the result."""
        self._excluded = {k: v for k, v in self._excluded.items() if v > now}
        usable = [c for c in self.live if c.login not in self._excluded]
        previous = self.watching
        self._settle_link_marks(now)
        planned = [replace(c, linked=False) if c.id in self.maybe_unlinked else c for c in self.campaigns]
        self.plan = plan(planned, usable, prefs, now,
                         watching=previous.login if previous else None,
                         override_campaign=self._override_campaign,
                         override_channel=self._override_channel,
                         current_campaign=self.plan.current.campaign_id
                         if self.plan and self.plan.current else None)
        cur = self.plan.current
        # a link test only counts consecutive time on one campaign: restart it after a break
        self._link_probe = {k: v for k, v in self._link_probe.items() if cur and k == cur.campaign_id}
        # spec §6: overrides last only while the plan still honours them
        if self._override_campaign and (cur is None or cur.campaign_id != self._override_campaign):
            self._override_campaign = None
        if self._override_channel and (cur is None or cur.channel_login != self._override_channel):
            self._override_channel = None
        self.watching = next((c for c in usable if cur and c.login == cur.channel_login), None)
        if self.watching and cur:
            for cid in (cur.campaign_id, *self.plan.also_credited):
                self._mined_on[cid] = self.watching.login
        topics = {topic("user_drops", self._user_id), topic("user_notifications", self._user_id)}
        if self._points_on():
            topics.add(topic("user_points", self._user_id))
        if self.watching:
            topics |= {topic("stream_state", self.watching.id), topic("stream_update", self.watching.id)}
        self._pubsub.set_topics(topics)
        if not self._paused:
            if self.watching is None:
                self._set_state(State.IDLE)
            elif previous and previous.login != self.watching.login:
                self._fails = 0
                info = {"from": previous.login, "to": self.watching.login}
                self.last_switch = {**info, "at": now}
                self._emit("switched", info)
                self._store.log_event("switched", {**info, **self._switch_why(previous.login)})
                self._set_state(State.SWITCHED, info)
            else:
                self._set_state(State.MINING)
        self._emit("refreshed", {"at": now.isoformat()})

    def _settle_link_marks(self, now: datetime) -> None:
        """A "may need linking" mark ends once Twitch reports the link either way, or after 6 h."""
        by_id = {c.id: c for c in self.campaigns}
        for cid, at in list(self.maybe_unlinked.items()):
            c = by_id.get(cid)
            if c is None or c.linked is not None or now - at >= MAYBE_UNLINKED_FOR:
                del self.maybe_unlinked[cid]

    async def _probe_link(self, now: datetime) -> None:
        """Called after each good playback tick. Unknown link + no new minutes for 10 min -> Needs you."""
        cur = self.plan.current if self.plan else None
        c = next((x for x in self.campaigns if cur and x.id == cur.campaign_id), None)
        if c is None or c.linked is not None or c.has_badge_or_emote:
            return
        total = sum(d.current_minutes for d in c.drops)
        ticks, start = self._link_probe.get(c.id, (0, total))
        if total > start:
            # it earns, but that doesn't prove the link: re-read Twitch's campaigns now, then every
            # LINK_RECHECK while the link is still unknown, rather than waiting for the hourly fetch
            self._link_probe.pop(c.id, None)
            last = self._link_recheck.get(c.id)
            if last is None or now - last >= LINK_RECHECK:
                self._link_recheck[c.id] = now
                await self.refresh(force_campaigns=True)
            return
        ticks += 1
        if ticks < LINK_PROBE_TICKS:
            self._link_probe[c.id] = (ticks, start)
            return
        self._link_probe.pop(c.id, None)
        self.maybe_unlinked[c.id] = now
        info = {"campaign": c.name, "reason": "may need linking"}
        self._emit("needs_you", info)
        self._store.log_event("needs_you", info)
        await self.refresh()

    def _settle_awaiting(self, now: datetime) -> None:
        """Stop forcing campaign fetches for drops that are claimed, gone, or waited on for 1 h."""
        for drop_id, deadline in list(self._awaiting_claim.items()):
            d = next((d for c in self.campaigns if (d := c.drop(drop_id))), None)
            if d is None or d.claimed:
                del self._awaiting_claim[drop_id]
            elif now >= deadline:
                del self._awaiting_claim[drop_id]
                self._gave_up_claim.add(drop_id)  # never re-armed this run

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
        if c.linked is False and not c.has_badge_or_emote:
            # Twitch answers ELIGIBLE_FOR_ALL here but awards nothing (ER ESPORTS DROPS, 2026-10-10);
            # the campaign stays in Needs you, and the claim goes through once Twitch says it's linked
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
            # game, watch time and channel only for the "a reward is claimed" push
            self._emit("claimed", {**info, "game": c.game.name, "minutes": d.required_minutes if d else None,
                                   "channel": self._mined_on.get(c.id)})
            self._store.log_event("claimed", {**info, "game": c.game.name})
            if hasattr(self._store, "add_claim"):
                self._store.add_claim(self._clock(), c.id, c.name, c.game.name,
                                      [(r.name, r.image_url) for r in (d.rewards if d else ())],
                                      minutes=d.required_minutes if d else None,
                                      channel=self._mined_on.get(c.id),
                                      campaign_rewards=sum(len(x.rewards) for x in c.drops),
                                      campaign_ends=c.ends_at, box_art_url=c.game.box_art_url)
            return True
        self._store.log_event("claim_failed", {"campaign": c.name, "drop": drop_id})
        # for the "a reward couldn't be claimed" notification; same shape as "claimed", so a later
        # success matches it
        self._emit("claim_failed", {"campaign": c.name,
                                    "reward": ", ".join(r.name for r in d.rewards) if d else drop_id})
        return False

    async def tick(self) -> None:
        now = self._clock()
        if self._paused:
            if self.paused_until is None or now < self.paused_until:
                self._set_state(State.PAUSED)
                return
            self.resume()
        if self.state == State.TWITCH_UNREACHABLE and self._retry_refresh_at is not None:
            due = now >= self._retry_refresh_at  # back off while Twitch is failing
        else:
            due = self.last_refresh is None or now - self.last_refresh >= REFRESH_EVERY
        if due:
            await self.refresh()
        if self.watching is None:
            return
        if await self._watcher.send(self.watching, now):
            self._fails = 0
            await self._probe_link(now)
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
            self._ticks_since_progress = 0  # whatever the outcome, wait STALL_TICKS again
            if cur:
                await self.handle(DropProgress(cur[0], cur[1], -1))

    async def safe_tick(self) -> float:
        """One tick that never raises. Returns how long to sleep before the next one."""
        started = self._clock()
        try:
            await self.tick()
        except Exception as exc:  # noqa: BLE001  the loop must survive anything
            log.exception("Tick failed")
            self._set_state(State.TWITCH_UNREACHABLE, {"error": type(exc).__name__})
            self._backoff = min(self._backoff * 2, BACKOFF_MAX) if self._backoff else BACKOFF_START
            return self._backoff
        self._backoff = 0.0
        elapsed = (self._clock() - started).total_seconds()
        return max(0.0, PLAY_INTERVAL - elapsed)  # keep a steady 10 s period like the reference

    def _switch_why(self, previous: str) -> dict:
        """For Activity: what is mined now and why the channel changed."""
        choice = self.plan.current if self.plan else None
        c = next((x for x in self.campaigns if choice and x.id == choice.campaign_id), None)
        return {"campaign": c.name if c else None, "game": c.game.name if c else None,
                "reason": choice.reason if choice else None,
                "channel_reason": choice.channel_reason if choice else None,
                # the directory lists a stream for minutes after it ends: an excluded channel is gone
                "from_live": previous not in self._excluded and any(ch.login == previous for ch in self.live)}

    def _campaigns_every(self) -> timedelta:
        """Settings' "Check Twitch for campaign changes every" (campaigns_every_minutes; 1 h by default)."""
        get = getattr(self._store, "get_settings", None)
        minutes = get().get("campaigns_every_minutes") if get else None
        return timedelta(minutes=minutes) if minutes else CAMPAIGNS_EVERY

    def _points_on(self) -> bool:
        """Settings' "Also claim channel points" (claim_points; on by default)."""
        get = getattr(self._store, "get_settings", None)
        return bool(get and get().get("claim_points"))

    async def _claim_points(self, channel_id: int, claim_id: str) -> None:
        try:
            ok = await self._client.claim_points(channel_id, claim_id)
        except Exception as exc:  # noqa: BLE001 - points are a bonus: never let them break mining
            log.info("Points claim raised %s", type(exc).__name__)
            ok = False
        login = next((ch.login for ch in self.live if ch.id == channel_id), None)
        self._store.log_event("points_claimed" if ok else "points_claim_failed",
                              {"channel_id": channel_id, "channel": login})

    async def _claim_waiting_points(self) -> None:
        """A chest that was already waiting when we started watching never arrives over PubSub: look once
        per refresh on the channel being watched."""
        if not self.watching or not self._points_on():
            return
        try:
            waiting = await self._client.waiting_points_claim(self.watching.login)
        except Exception as exc:  # noqa: BLE001 - points are a bonus: never let them break a refresh
            log.info("Points check raised %s", type(exc).__name__)
            return
        if waiting:
            await self._claim_points(*waiting)

    async def handle(self, event: object) -> None:
        if isinstance(event, PointsClaimable):
            if self._points_on() and event.channel_id and event.claim_id:
                await self._claim_points(event.channel_id, event.claim_id)
            return
        if isinstance(event, DropProgress):
            self._ticks_since_progress = 0
            for i, c in enumerate(self.campaigns):
                d = c.drop(event.drop_id)
                if d is not None:
                    self.campaigns[i] = with_drop(c, replace(d, current_minutes=event.current))
                    if event.current >= d.required_minutes > 0 and not d.claimed:
                        # Twitch may never send drop-claim; fetch the claim id at the next refresh
                        if d.id not in self._gave_up_claim:
                            self._awaiting_claim.setdefault(d.id, self._clock() + CLAIM_WAIT)
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
    """`dropwatch run`: headless mining until Ctrl+C or the Twitch session expires."""
    from .events import EventBus
    from .service import MinerService

    svc = MinerService(store, EventBus())
    if not await svc.start():
        print("Not signed in. Run: dropwatch signin")
        return 1
    try:
        await svc.wait_stopped()
    finally:
        await svc.stop()
    print("Twitch session expired. Run: dropwatch signin")
    return 1
