"""Decide what to mine and where. Pure: no I/O and no clock reads (spec §6)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .models import (
    Campaign,
    LiveChannel,
    Prefs,
    account_eligible,
    campaign_active,
    campaign_minutes_needed,
    campaign_ratio,
    deadline_verdict,
    drop_earnable_now,
)


@dataclass(frozen=True)
class Choice:
    campaign_id: str
    channel_login: str
    reason: str
    channel_reason: str


@dataclass(frozen=True)
class Plan:
    current: Choice | None
    queue: tuple[str, ...] = ()
    needs_you: tuple[str, ...] = ()
    done: tuple[str, ...] = ()
    verdicts: dict[str, str] = field(default_factory=dict)
    also_credited: tuple[str, ...] = ()
    waiting: tuple[str, ...] = ()  # could be mined but nobody qualifying is live, in queue order


def qualifies(c: Campaign, ch: LiveChannel) -> bool:
    if not ch.drops_enabled:
        return False
    if c.allowed_logins and ch.login not in c.allowed_logins:
        return False
    return c.game.special or ch.game_id == c.game.id


def _channel_rank(c: Campaign, ch: LiveChannel, prefs: Prefs) -> tuple:
    if ch.login in prefs.favourites:
        return (0, prefs.favourites.index(ch.login), -ch.viewers, ch.login)
    if ch.login in c.allowed_logins:
        return (1, 0, -ch.viewers, ch.login)
    return (2, 0, -ch.viewers, ch.login)


_TIER = {0: "favourite", 1: "allowed channel", 2: "any channel"}


def plan(
    campaigns: Sequence[Campaign],
    live: Sequence[LiveChannel],
    prefs: Prefs,
    now: datetime,
    *,
    watching: str | None = None,
    override_campaign: str | None = None,
    override_channel: str | None = None,
    current_campaign: str | None = None,
) -> Plan:
    considered = [c for c in campaigns if campaign_active(c, now) and c.game.name not in prefs.never]
    needs_you = tuple(
        c.id for c in sorted(considered, key=lambda c: (c.ends_at, c.id))
        if c.linked is False and not c.has_badge_or_emote and campaign_minutes_needed(c, now) > 0
    )
    done = tuple(
        c.id for c in sorted(considered, key=lambda c: (c.ends_at, c.id))
        if c.drops and all(d.claimed for d in c.drops)
    )
    verdicts = {
        c.id: deadline_verdict(campaign_ratio(c, now))
        for c in considered if campaign_minutes_needed(c, now) > 0
    }

    qualifying: dict[str, list[LiveChannel]] = {}
    offline: list[Campaign] = []
    for c in considered:
        if not account_eligible(c, prefs):
            continue
        if not any(drop_earnable_now(c, d, now) for d in c.drops):
            continue
        chans = [ch for ch in live if qualifies(c, ch)]
        if chans:
            qualifying[c.id] = sorted(chans, key=lambda ch: _channel_rank(c, ch, prefs))
        else:
            offline.append(c)

    eligible = [c for c in considered if c.id in qualifying]
    # spec §4 (2026-10-10): outside Priority, campaigns known (or very likely) to be linked come
    # before ones whose link is unknown, so testing unknown links only fills otherwise idle time.
    linked_games = {c.game.id for c in considered if c.linked is True}

    def link_rank(c: Campaign) -> int:
        return 0 if c.linked is True or c.has_badge_or_emote or c.game.id in linked_games else 1

    def order(c: Campaign) -> tuple:
        if c.game.name in prefs.priority:
            return (0, prefs.priority.index(c.game.name), 0, 0.0, c.ends_at, c.id)
        if c.id in prefs.pins:  # "Arrange myself": pins next, in the order Nick set
            return (1, prefs.pins.index(c.id), 0, 0.0, c.ends_at, c.id)
        return (2, 0, link_rank(c), campaign_ratio(c, now), c.ends_at, c.id)

    eligible.sort(key=order)
    waiting = tuple(c.id for c in sorted(offline, key=order))
    if not eligible:
        return Plan(None, (), needs_you, done, verdicts, (), waiting)

    chosen = next((c for c in eligible if c.id == override_campaign), eligible[0])
    if chosen.id != override_campaign:
        chosen = _hold_current(chosen, eligible, current_campaign, prefs, now, link_rank)
    if chosen.id == override_campaign:
        reason = "you picked it"
    elif chosen.game.name in prefs.priority:
        reason = f"priority {prefs.priority.index(chosen.game.name) + 1}"
    elif chosen.id in prefs.pins:
        reason = "you pinned it"
    else:
        reason = "most urgent"

    chans = qualifying[chosen.id]
    best = chans[0]
    by_login = {ch.login: ch for ch in chans}
    if override_channel in by_login:
        channel, channel_reason = by_login[override_channel], "you picked it"
    elif watching in by_login and not _favourite_outranks(chosen, best, by_login[watching], prefs):
        channel, channel_reason = by_login[watching], "already watching"
    else:
        channel, channel_reason = best, _TIER[_channel_rank(chosen, best, prefs)[0]]

    also = tuple(
        c.id for c in eligible
        if c.id != chosen.id and c.game.id == chosen.game.id and qualifies(c, channel)
    )
    queue = tuple(c.id for c in eligible if c.id != chosen.id)
    return Plan(
        Choice(chosen.id, channel.login, reason, channel_reason),
        queue, needs_you, done, verdicts, also, waiting,
    )


def _favourite_outranks(c: Campaign, best: LiveChannel, current: LiveChannel, prefs: Prefs) -> bool:
    if best.login not in prefs.favourites or best.login == current.login:
        return False
    return _channel_rank(c, best, prefs) < _channel_rank(c, current, prefs)


HYSTERESIS = 0.8  # a challenger must have 20% less spare time to take over


def _hold_current(
    chosen: Campaign, eligible: list[Campaign], current: str | None, prefs: Prefs, now: datetime,
    link_rank=lambda c: 0,
) -> Campaign:
    """Keep mining the current non-priority campaign unless the challenger is clearly more urgent.

    Mining a campaign raises its spare-time ratio while the others fall, so a strict re-sort
    every refresh would alternate between near-equal campaigns. Priority order always wins.
    """
    cur = next((c for c in eligible if c.id == current), None)
    if cur is None or cur.id == chosen.id:
        return chosen
    if cur.game.name in prefs.priority or chosen.game.name in prefs.priority:
        return chosen
    if cur.id in prefs.pins or chosen.id in prefs.pins:
        return chosen  # pins are an explicit order, like Priority: no hysteresis
    if link_rank(chosen) < link_rank(cur):
        return chosen  # a known-linked campaign always replaces a link test
    rc, rn = campaign_ratio(cur, now), campaign_ratio(chosen, now)
    if rn < HYSTERESIS * rc or rn < 1 <= rc:
        return chosen
    return cur
