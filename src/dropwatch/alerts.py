"""When to notify (approved mockup docs/design/notifications-mockup.html, 2026-10-10).

Failures, each said once when it starts and once when it clears (a recovery only follows an alert that was
actually sent, so a switched-off alert stays silent both ways):
- Twitch sign-in stopped working (state signed_out, or the service's "signin expired")
- Can't reach Twitch: twitch_unreachable for notify_unreachable_minutes (default 15)
- Mining isn't earning: mining for notify_not_earning_minutes (default 30) since mining began or the last
  progress event, not counting paused or idle time
- A reward couldn't be claimed (runner's claim_failed), once per reward until it is claimed
- Mining stopped on an error (the service's {"state": "idle", "error": ...} after a crash)
Plus "a campaign needs you" (account link), off by default: one batched message for campaigns not yet
reported, remembered across restarts.

`handle` takes the miner's own events; `check` runs on a timer for the time-based ones. `run` wires both
to the event bus and sends through `dispatch`.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

log = logging.getLogger("dropwatch.alerts")
PREFIX = "Dropwatch: "
CHECK_EVERY_S = 30
MINING = {"mining", "switched"}


@dataclass(frozen=True)
class Alert:
    key: str  # the setting that switches it on
    title: str
    body: str


@dataclass(frozen=True)
class Snapshot:
    campaign: str | None  # what is being mined, for the "isn't earning" message
    channel: str | None
    needs_you: list[tuple[str, str, str]] = field(default_factory=list)  # (campaign id, name, game)


class Notifier:
    def __init__(self, store, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._store, self._clock = store, clock
        self._sent: set[str] = set()  # alerts said and not yet cleared
        self._unreachable_since: datetime | None = None
        self._earning_since: datetime | None = None
        self._failed_claims: set[tuple[str, str]] = set()

    def _on(self, key: str) -> bool:
        return bool(self._store.get_settings().get(key))

    def _alert(self, key: str, title: str, body: str, *, track: str | None = None) -> list[Alert]:
        if not self._on(key):
            return []
        if track:
            self._sent.add(track)
        return [Alert(key, PREFIX + title, body)]

    def _clear(self, track: str, key: str, title: str, body: str) -> list[Alert]:
        if track not in self._sent:
            return []
        self._sent.discard(track)
        return [Alert(key, PREFIX + title, body)]

    def handle(self, kind: str, data: dict) -> list[Alert]:
        now = self._clock()
        out: list[Alert] = []
        expired = kind == "signin" and data.get("status") == "expired"
        if expired or kind == "state" and data.get("state") == "signed_out":
            if "signin" not in self._sent:
                out += self._alert("notify_signin", "Twitch sign-in stopped working",
                                   "Mining has stopped. Open Dropwatch and get a new sign-in code.",
                                   track="signin")
            self._earning_since = None
            return out
        if kind == "state":
            state = data.get("state")
            if data.get("error") and state == "idle":
                if "stopped" not in self._sent:
                    out += self._alert("notify_stopped", "Mining stopped on an error",
                                       f"{data['error']}. Restart Dropwatch to start mining again.",
                                       track="stopped")
                self._earning_since = None
                return out
            if state == "twitch_unreachable":
                self._unreachable_since = self._unreachable_since or now
                self._earning_since = None
                return out
            if self._unreachable_since is not None:
                self._unreachable_since = None
                out += self._clear("unreachable", "notify_unreachable", "Twitch is reachable again",
                                   "Mining carries on.")
            if state in MINING:
                if self._earning_since is None:
                    self._earning_since = now
                out += self._clear("signin", "notify_signin", "Twitch sign-in is working again",
                                   "Mining has resumed.")
                out += self._clear("stopped", "notify_stopped", "Mining is running again",
                                   "Mining has resumed.")
            else:
                self._earning_since = None
            return out
        if kind == "progress":
            self._earning_since = now
            return self._clear("not_earning", "notify_not_earning", "Mining is earning again",
                               "New minutes are coming in.")
        if kind == "claim_failed":
            key = (data.get("campaign", ""), data.get("reward", ""))
            if key in self._failed_claims:
                return []
            alert = self._alert("notify_claim_failed", "A reward couldn't be claimed",
                                f"{key[1]} from {key[0]}. Dropwatch will try again.")
            if alert:
                self._failed_claims.add(key)
            return alert
        if kind == "claimed":
            key = (data.get("campaign", ""), data.get("reward", ""))
            if key in self._failed_claims:
                self._failed_claims.discard(key)
                return [Alert("notify_claim_failed", PREFIX + "Claimed after all",
                              f"{key[1]} from {key[0]}.")]
        return out

    def check(self, snap: Snapshot) -> list[Alert]:
        now = self._clock()
        s = self._store.get_settings()
        out: list[Alert] = []
        wait = timedelta(minutes=s["notify_unreachable_minutes"])
        down = self._unreachable_since
        if down and now - down >= wait and "unreachable" not in self._sent:
            out += self._alert("notify_unreachable", "Can't reach Twitch",
                               f"Checks have been failing for {s['notify_unreachable_minutes']} minutes. "
                               "Dropwatch keeps retrying.", track="unreachable")
        wait = timedelta(minutes=s["notify_not_earning_minutes"])
        if self._earning_since and now - self._earning_since >= wait and "not_earning" not in self._sent:
            where = f"Watched {snap.channel}" if snap.channel else "Watched"
            on = f" on {snap.campaign}" if snap.campaign else ""
            out += self._alert("notify_not_earning", "Mining isn't earning",
                               f"{where} for {s['notify_not_earning_minutes']} minutes with no new "
                               f"minutes{on}. "
                               "Twitch may have changed something.", track="not_earning")
        out += self._needs_you(snap.needs_you, s)
        return out

    def _needs_you(self, campaigns: list[tuple[str, str, str]], s: dict) -> list[Alert]:
        if not s.get("notify_needs_you"):
            return []  # nothing recorded while off, so switching it on reports what is waiting
        told = set(json.loads(self._store.get_setting("notify_needs_you_sent") or "[]"))
        current = {cid for cid, _, _ in campaigns}
        new = [c for c in campaigns if c[0] not in told]
        keep = (told & current) | {c[0] for c in new}  # forget ones that left Needs you: they may come back
        if keep != told:
            self._store.set_setting("notify_needs_you_sent", json.dumps(sorted(keep)))
        if not new:
            return []
        if len(new) == 1:
            _, name, game = new[0]
            return [Alert("notify_needs_you", f"{PREFIX}{name} needs your account linked",
                          f"{game}: link your account to mine it.")]
        listed = ", ".join(f"{name} ({game})" for _, name, game in new[:10])
        more = f", and {len(new) - 10} more" if len(new) > 10 else ""
        return [Alert("notify_needs_you", f"{PREFIX}{len(new)} campaigns need your account linked",
                      listed + more)]

    async def run(self, bus, snapshot: Callable[[], Snapshot],
                  send: Callable[[str, str], Awaitable[list[dict]]]) -> None:
        """Until cancelled: the bus's events as they come, the timed checks every 30 s."""
        q = bus.subscribe()
        try:
            while True:
                alerts: list[Alert] = []
                with contextlib.suppress(TimeoutError):
                    kind, data = await asyncio.wait_for(q.get(), timeout=CHECK_EVERY_S)
                    alerts += self.handle(kind, data)
                alerts += self.check(snapshot())
                for a in alerts:
                    try:
                        results = await send(a.title, a.body)
                    except Exception as exc:  # noqa: BLE001 - a broken send must not end notifications
                        log.warning("Notifying %r failed: %s", a.title, type(exc).__name__)
                        continue
                    got = "; ".join(f"{r['name']} {r['message']}" for r in results)
                    log.info("Notified %r: %s", a.title, got or "no channels set up")
        finally:
            bus.unsubscribe(q)


def snapshot_of(runner) -> Snapshot:
    """What the timed checks need from the miner right now (no Twitch calls)."""
    plan = getattr(runner, "plan", None)
    if runner is None or plan is None:
        return Snapshot(None, None, [])
    by_id = {c.id: c for c in runner.campaigns}
    cur = by_id.get(plan.current.campaign_id) if plan.current else None
    watching = runner.watching.login if runner.watching else None
    return Snapshot(cur.name if cur else None, watching,
                    [(c.id, c.name, c.game.name) for cid in plan.needs_you if (c := by_id.get(cid))])
