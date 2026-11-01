"""What gets mined when, and which rewards won't make it. Pure: no I/O and no clock reads.

An estimate: it walks the planner's queue back to back as if a qualifying stream stays live throughout. The
planner re-sorts unlisted games by urgency and streams come and go, so times further out are rougher.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Campaign, campaign_minutes_needed, drop_open, total_remaining


@dataclass(frozen=True)
class Step:
    campaign: Campaign
    starts_at: datetime
    finishes_at: datetime
    status: str  # "ok": every reward left makes it | "partial": some do | "miss": none do
    earned: int  # rewards still to come that make it
    missed: tuple[str, ...]  # names of the rewards that don't
    alongside: bool = False  # earned on the current stream, at the same time


def _step(c: Campaign, start: datetime, now: datetime, skip_too_late: bool, alongside: bool) -> Step:
    earned = 0
    missed: list[str] = []
    last = start
    for d in c.drops:
        if not d.rewards or not drop_open(c, d, now):
            continue
        due = start + timedelta(minutes=total_remaining(c, d))
        if due <= min(d.ends_at, c.ends_at):
            earned += len(d.rewards)
            last = max(last, due)
        else:
            missed.extend(r.name for r in d.rewards)
    # with "skip what can't finish" the miner moves on after the last reward in reach; otherwise it stays
    # until the campaign is done or over
    needed = start + timedelta(minutes=campaign_minutes_needed(c, now))
    end = last if skip_too_late else max(start, min(needed, c.ends_at))
    status = "ok" if not missed else "partial" if earned else "miss"
    return Step(c, start, end, status, earned, tuple(missed), alongside)


def forecast(
    current: str | None, queue: Sequence[str], alongside: Collection[str], campaigns: Mapping[str, Campaign],
    start: datetime, now: datetime, *, skip_too_late: bool = False,
) -> list[Step]:
    """The current campaign and what's earned alongside it, then the rest of the queue, returned in queue
    order. `start` is when mining (re)starts: now, unless paused. Whatever rides along can outlast the current
    campaign, and that watching still has to happen before the rest gets a turn."""
    first = [current] if current else []
    steps: dict[str, Step] = {}
    t = start
    for cid in [*first, *(q for q in queue if q in alongside)]:
        if c := campaigns.get(cid):
            steps[cid] = _step(c, start, now, skip_too_late, cid != current)
            t = max(t, steps[cid].finishes_at)
    for cid in queue:
        if cid not in steps and (c := campaigns.get(cid)):
            steps[cid] = _step(c, t, now, skip_too_late, False)
            t = steps[cid].finishes_at
    return [steps[cid] for cid in [*first, *queue] if cid in steps]
