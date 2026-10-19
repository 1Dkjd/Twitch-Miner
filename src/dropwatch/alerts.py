"""When to notify (approved mockup docs/design/notifications-mockup.html, 2026-10-10).

Failures, each said once when it starts and once when it clears (a recovery only follows an alert that was
actually sent, so a switched-off alert stays silent both ways):
- Twitch sign-in stopped working (state signed_out, or the service's "signin expired"), and, for a login-page
  sign-in, Twitch going quiet on its campaign list while the catalogue still lists plenty (2026-10-18)
- Can't reach Twitch: twitch_unreachable for notify_unreachable_minutes (default 15)
- Mining isn't earning: mining for notify_not_earning_minutes (default 30) since mining began or the last
  progress event, not counting paused or idle time
- A reward couldn't be claimed (runner's claim_failed), once per reward until it is claimed
- Mining stopped on an error (the service's {"state": "idle", "error": ...} after a crash)
Plus "ending soon" (2026-10-18, on by default): a reward already started whose window closes within
notify_ending_hours, while it can still be finished, once per reward. And "a campaign needs you"
(account link), off by default: one batched message for campaigns not yet
reported, remembered across restarts. And two summaries, both off by default (2026-10-10): "a reward is
claimed" (claims within a minute of the first arrive as one message) and a weekly summary at a chosen
day and hour of the server's local time, sent once per week and up to WEEKLY_LATE after if Dropwatch was
off at that moment.

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

from .tz import zone_or_none

log = logging.getLogger("dropwatch.alerts")
PREFIX = "Dropwatch: "
CHECK_EVERY_S = 30
CLAIM_BATCH = timedelta(minutes=1)
WEEKLY_LATE = timedelta(hours=6)
WEEKLY_RETRY = timedelta(minutes=10)
MINING = {"mining", "switched"}


@dataclass(frozen=True)
class Alert:
    key: str  # the setting that switches it on
    title: str
    body: str
    # a setting to store once a channel actually delivered it (the weekly summary's sent week)
    after_sent: tuple[str, str] | None = None
    image: str = ""  # a picture for services that show one (2026-10-18): the reward, else the game's box art


@dataclass(frozen=True)
class Snapshot:
    campaign: str | None  # what is being mined, for the "isn't earning" message
    channel: str | None
    needs_you: list[tuple[str, str, str]] = field(default_factory=list)  # (campaign id, name, game)
    list_lost: bool = False  # a login-page sign-in lost Twitch's campaign list (runner.full_list_lost)
    # announced campaigns, for the weekly summary: (game, campaign, starts_at, linked: True/False/None)
    upcoming: list[tuple[str, str, datetime, bool | None]] = field(default_factory=list)
    # started rewards that can still finish: (drop id, reward, game, minutes left, ends, image)
    started: list[tuple[str, str, str, int, datetime, str]] = field(default_factory=list)


class Notifier:
    def __init__(self, store, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC), tz=None):
        self._store, self._clock = store, clock
        self._tz = tz  # None: the server's local zone, read at each check so DST changes apply
        self._claims: list[dict] = []  # claimed rewards waiting to go out as one message
        self._claims_since: datetime | None = None
        self._weekly_tried: datetime | None = None
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

    def _sign_in_again(self) -> str:
        session = getattr(self._store, "get_session", lambda: None)()
        from .twitch.constants import SMARTBOX
        if session is not None and session.client_id != SMARTBOX.client_id:
            return ("Open Dropwatch and sign in again on Twitch's page "
                    "(Settings > Account & security), or get a sign-in code.")
        return "Open Dropwatch and get a new sign-in code."

    def handle(self, kind: str, data: dict) -> list[Alert]:
        now = self._clock()
        out: list[Alert] = []
        expired = kind == "signin" and data.get("status") == "expired"
        if expired or kind == "state" and data.get("state") == "signed_out":
            if "signin" not in self._sent:
                out += self._alert("notify_signin", "Twitch sign-in stopped working",
                                   "Mining has stopped. " + self._sign_in_again(), track="signin")
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
            if self._on("notify_claimed"):
                self._claims.append(data)
                self._claims_since = self._claims_since or now
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
        if snap.list_lost and "list" not in self._sent:
            out += self._alert("notify_signin", "Twitch stopped sending the full campaign list",
                               "Mining carries on from the backup catalogue, but account links are unknown "
                               "again until a campaign starts. " + self._sign_in_again(), track="list")
        elif not snap.list_lost:
            out += self._clear("list", "notify_signin", "Twitch is sending the full campaign list again",
                               "Account links are known again.")
        out += self._needs_you(snap.needs_you, s)
        out += self._ending(now, snap, s)
        if self._claims and now - self._claims_since >= CLAIM_BATCH:
            out += self._claimed_alert()
        if s.get("notify_weekly"):
            out += self._weekly(now, s, snap)
        return out

    def _claimed_alert(self) -> list[Alert]:
        claims, self._claims, self._claims_since = self._claims, [], None
        if len(claims) == 1:
            c = claims[0]
            where = f"{c.get('campaign')} ({c.get('game')})" if c.get("game") else str(c.get("campaign"))
            facts = []
            if c.get("minutes"):
                facts.append(f"after {_dur(c['minutes'])} watched")
            if c.get("channel"):
                facts.append(f"on {c['channel']}")
            body = f"{where}, {' '.join(facts)}." if facts else f"{where}."
            return [Alert("notify_claimed", f"{PREFIX}Claimed {c.get('reward')}", body,
                          image=_picture(c.get("image"), c.get("box_art")))]
        names = _and([str(c.get("reward")) for c in claims])
        camps = {(c.get("campaign"), c.get("game")) for c in claims}
        if len(camps) == 1:
            (camp, game), = camps
            body = f"{names} from {camp} ({game})." if game else f"{names} from {camp}."
        else:
            body = _and([f"{c.get('reward')} ({c.get('campaign')})" for c in claims]) + "."
        return [Alert("notify_claimed", f"{PREFIX}Claimed {len(claims)} rewards", body,
                      image=_picture(*(c.get("image") for c in claims), *(c.get("box_art") for c in claims)))]

    def _weekly(self, now: datetime, s: dict, snap: Snapshot) -> list[Alert]:
        zone = zone_or_none(s.get("notify_weekly_tz") or "") or self._tz  # chosen, else the server's
        local = now.astimezone(zone) if zone else now.astimezone()
        due = local.replace(hour=s["notify_weekly_hour"], minute=0, second=0, microsecond=0)
        due -= timedelta(days=(local.weekday() - s["notify_weekly_day"]) % 7)
        if due > local:
            due -= timedelta(days=7)
        key = due.date().isoformat()
        if local - due > WEEKLY_LATE or self._store.get_setting("notify_weekly_sent") == key:
            return []
        if self._weekly_tried and now - self._weekly_tried < WEEKLY_RETRY:
            return []  # the last try reached no channel
        week = now - timedelta(days=7)
        claims = self._store.claims_since(week)
        rewards = sum(len(c["rewards"]) for c in claims)
        camps = len({c["campaign_id"] for c in claims})
        missed = sum(1 for m in self._store.missed_between(week, now) if notable(m))
        games = list(dict.fromkeys(game for _, _, game in snap.needs_you))
        parts = []
        if rewards:
            parts.append(f"{rewards} {_n(rewards, 'reward')} claimed from {camps} {_n(camps, 'campaign')}.")
        pts = self._store.points_since(week) if hasattr(self._store, "points_since") else {"points": 0}
        if not rewards:
            quiet = not (missed or games or pts["points"])
            parts.append("A quiet week: nothing claimed." if quiet else "Nothing claimed.")
        if pts["points"]:
            chests = pts.get("chests", 0)
            parts.append(f"{pts['points']:,} channel points"
                         + (f" ({chests} {_n(chests, 'chest')})." if chests else "."))
        if missed:
            parts.append(f"{missed} {_n(missed, 'campaign')} missed (History says why).")
        if games:
            parts.append(f"{len(games)} {'needs' if len(games) == 1 else 'need'} your account linked: "
                         f"{', '.join(games)}.")
        parts += self._coming_up(now, local, snap)
        self._weekly_tried = now
        return [Alert("notify_weekly", f"{PREFIX}Your week", " ".join(parts),
                      after_sent=("notify_weekly_sent", key))]

    def _coming_up(self, now: datetime, local: datetime, snap: Snapshot) -> list[str]:
        """The week ahead (2026-10-18): campaigns starting in the next 7 days, Priority games first, and the
        ones to link before they start (known with a login-page sign-in)."""
        prefs = getattr(self._store, "get_prefs", None)
        p = prefs() if prefs else None
        soon = [u for u in snap.upcoming if u[2] <= now + timedelta(days=7)
                and not (p and p.in_never(u[0]))]
        if not soon:
            return []
        rank = (lambda g: p.priority_rank(g)) if p else (lambda g: None)
        soon.sort(key=lambda u: (rank(u[0]) is None, rank(u[0]) or 0, u[2]))
        first: dict[str, datetime] = {}  # one line per game, at its earliest start
        for game, _, start, _ in soon:
            first.setdefault(game, start)
        shown = [f"{g}{' (Priority)' if rank(g) is not None else ''} on {u_day(at, local.tzinfo)}"
                 for g, at in list(first.items())[:5]]
        more = len(first) - len(shown)
        out = [f"Starting this week: {', '.join(shown)}" + (f" and {more} more." if more > 0 else ".")]
        link = list(dict.fromkeys(game for game, _, _, linked in soon if linked is False))
        if link:
            out.append(f"Link before they start: {', '.join(link)}.")
        return out

    def _ending(self, now: datetime, snap: Snapshot, s: dict) -> list[Alert]:
        if not s.get("notify_ending_soon"):
            return []
        window = timedelta(hours=s.get("notify_ending_hours") or 6)
        due = [x for x in snap.started if now < x[4] <= now + window]
        if not due:
            return []
        told = json.loads(self._store.get_setting("notify_ending_sent") or "[]")
        new = [x for x in due if x[0] not in told]
        if not new:
            return []
        self._store.set_setting("notify_ending_sent", json.dumps((told + [x[0] for x in new])[-300:]))
        new.sort(key=lambda x: x[4])

        def line(x) -> str:
            left = _until(x[4] - now)
            return f"{x[1]} ({x[2]}): {_dur(x[3])} to go, ends in {left}."
        image = _picture(*(x[5] for x in new))
        if len(new) == 1:
            return [Alert("notify_ending_soon", f"{PREFIX}Ending soon: {new[0][1]}", line(new[0]),
                          image=image)]
        more = f" And {len(new) - 8} more." if len(new) > 8 else ""
        return [Alert("notify_ending_soon", f"{PREFIX}Ending soon: {len(new)} rewards",
                      " ".join(line(x) for x in new[:8]) + more, image=image)]

    def _needs_you(self, campaigns: list[tuple[str, str, str]], s: dict) -> list[Alert]:
        if not s.get("notify_needs_you"):
            return []  # nothing recorded while off, so switching it on reports what is waiting
        told = set(json.loads(self._store.get_setting("notify_needs_you_sent") or "[]"))
        current = {cid for cid, _, _ in campaigns}
        new = [c for c in campaigns if c[0] not in told]
        # forget ones that left Needs you: they may come back. Not while Priority only is on: then they only
        # left because of the switch, and turning it off would announce them again (review fix 2026-10-12)
        keep = (told if s.get("priority_only") else told & current) | {c[0] for c in new}
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

    def delivered(self, a: Alert) -> None:
        """A channel delivered it: record what must not be sent twice (the weekly summary's week)."""
        if a.after_sent:
            self._store.set_setting(*a.after_sent)

    @staticmethod
    def _safely(fn, *args) -> list[Alert]:
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 - one bad check must not end notifications
            log.warning("Notification check failed: %s: %s", type(exc).__name__, exc)
            return []

    async def run(self, bus, snapshot: Callable[[], Snapshot],
                  send: Callable[[str, str], Awaitable[list[dict]]]) -> None:
        """Until cancelled: the bus's events as they come, the timed checks every 30 s."""
        q = bus.subscribe()
        try:
            while True:
                alerts: list[Alert] = []
                with contextlib.suppress(TimeoutError):
                    kind, data = await asyncio.wait_for(q.get(), timeout=CHECK_EVERY_S)
                    alerts += self._safely(self.handle, kind, data)
                alerts += self._safely(lambda: self.check(snapshot()))
                for a in alerts:
                    try:
                        results = await send(a.title, a.body, **({"image": a.image} if a.image else {}))
                    except Exception as exc:  # noqa: BLE001 - a broken send must not end notifications
                        log.warning("Notifying %r failed: %s", a.title, type(exc).__name__)
                        continue
                    got = "; ".join(f"{r['name']} {r['message']}" for r in results)
                    if results:  # Activity: where it went (names only; never a target or a secret)
                        self._safely(lambda a=a, results=results: self._store.log_event("notified", {
                            "title": a.title, "sent": [r["name"] for r in results if r.get("ok")],
                            "failed": [r["name"] for r in results if not r.get("ok")]}))
                    log.info("Notified %r: %s", a.title, got or "no channels set up")
                    # delivered, or no channel to deliver to: done. All channels failed: retried later
                    if a.after_sent and (not results or any(r.get("ok") for r in results)):
                        self.delivered(a)
        finally:
            bus.unsubscribe(q)


def _until(left: timedelta) -> str:
    """'3 h', '40 min', '1 day 2 h': how long until a window closes."""
    m = max(1, int(left.total_seconds() // 60))
    if m < 60:
        return f"{m}\u00a0min"
    h = round(m / 60)
    if h < 24:
        return f"{h}\u00a0h"
    days = f"{h // 24}\u00a0{'day' if h // 24 == 1 else 'days'}"
    return days + (f" {h % 24}\u00a0h" if h % 24 else "")


def _picture(*urls) -> str:
    """The first image Twitch serves itself (its CDN); nothing else is ever put in a notification."""
    return next((u for u in urls if isinstance(u, str) and u.startswith("https://static-cdn.jtvnw.net/")), "")


def u_day(at: datetime, tz) -> str:
    """'Sat 24 Oct' in the summary's zone."""
    d = at.astimezone(tz) if tz else at.astimezone()
    return d.strftime("%a ") + str(d.day) + d.strftime(" %b")


def notable(m: dict) -> bool:
    """A missed campaign worth naming (the same rule as History's full rows): Dropwatch started it, it is a
    Priority or pinned game, or it needs an account linked."""
    return m["reason"] != "never_list" and (m["started"] or m["priority"] or m["pinned"]
                                             or m["reason"] == "not_linked")


def _n(k: int, word: str) -> str:
    return word if k == 1 else word + "s"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _dur(minutes: int) -> str:
    """'45 min', '4 h', '1 h 30 min', joined by non-breaking spaces as the page writes them."""
    if minutes < 60:
        return f"{minutes}\u00a0min"
    h, m = divmod(minutes, 60)
    return f"{h}\u00a0h" + (f" {m}\u00a0min" if m else "")


def snapshot_of(runner) -> Snapshot:
    """What the timed checks need from the miner right now (no Twitch calls)."""
    plan = getattr(runner, "plan", None)
    if runner is None or plan is None:
        return Snapshot(None, None, [])
    by_id = {c.id: c for c in runner.campaigns}
    cur = by_id.get(plan.current.campaign_id) if plan.current else None
    watching = runner.watching.login if runner.watching else None
    now = getattr(runner, "_clock", lambda: datetime.now(UTC))()
    return Snapshot(cur.name if cur else None, watching,
                    [(c.id, c.name, c.game.name) for cid in plan.needs_you if (c := by_id.get(cid))],
                    list_lost=bool(getattr(runner, "full_list_lost", False)),
                    upcoming=[(c.game.name, c.name, c.starts_at, None if c.has_badge_or_emote else c.linked)
                              for c in runner.campaigns if c.starts_at > now],
                    started=_started(runner, now))


def _started(runner, now: datetime) -> list[tuple[str, str, str, int, datetime, str]]:
    """Rewards with minutes watched, not claimed, that can still be finished, outside Never games."""
    from .models import drop_finishable, total_remaining
    store = getattr(runner, "_store", None)
    prefs = store.get_prefs() if store is not None and hasattr(store, "get_prefs") else None
    out = []
    for c in runner.campaigns:
        if prefs is not None and prefs.in_never(c.game.name):
            continue
        for d in c.drops:
            if d.claimed or d.current_minutes <= 0 or d.required_subs or not d.rewards:
                continue
            if drop_finishable(c, d, now):
                image = next((r.image_url for r in d.rewards if r.image_url), c.game.box_art_url)
                out.append((d.id, d.rewards[0].name, c.game.name, total_remaining(c, d),
                            min(d.ends_at, c.ends_at), image))
    return out
