"""Pure snapshots of runner/store state for the API. No I/O beyond the store reads passed in."""
from __future__ import annotations

from datetime import datetime

from ..models import Campaign, campaign_minutes_needed, campaign_ratio, deadline_verdict
from .models import (
    CampaignOut,
    ChannelOut,
    ClaimOut,
    CurrentOut,
    DropOut,
    HistoryOut,
    RewardOut,
    StateOut,
)


def campaign_out(c: Campaign, now: datetime, verdict: str | None) -> CampaignOut:
    return CampaignOut(
        id=c.id, name=c.name, game=c.game.name, box_art_url=c.game.box_art_url, ends_at=c.ends_at,
        linked=c.linked, link_url=c.link_url, allowed_channels=list(c.allowed_logins),
        minutes_needed=campaign_minutes_needed(c, now), verdict=verdict,
        drops=[DropOut(id=d.id, name=d.name, required_minutes=d.required_minutes,
                       current_minutes=d.current_minutes, claimed=d.claimed, starts_at=d.starts_at,
                       ends_at=d.ends_at, rewards=[RewardOut(name=r.name, image_url=r.image_url)
                                                   for r in d.rewards])
               for d in c.drops],
    )


def state_view(runner, store, now: datetime) -> StateOut:
    session = store.get_session()
    if runner is None:
        return StateOut(state="signed_out" if session is None else "idle", signed_in=session is not None,
                        login=session.login if session else None, paused_until=None, last_refresh=None,
                        current=None, needs_you=[], up_next=[], done=[])
    by_id = {c.id: c for c in runner.campaigns}
    plan = runner.plan
    verdicts = plan.verdicts if plan else {}

    def out(cid: str):
        c = by_id.get(cid)
        if c is None:
            return None
        v = verdicts.get(cid)
        if v is None and campaign_minutes_needed(c, now) > 0:
            v = deadline_verdict(campaign_ratio(c, now))
        return campaign_out(c, now, v)

    current = None
    if plan and plan.current and runner.watching and (camp := out(plan.current.campaign_id)):
        favs = store.get_prefs().favourites
        w = runner.watching
        current = CurrentOut(
            campaign=camp, channel=ChannelOut(login=w.login, viewers=w.viewers, favourite=w.login in favs),
            reason=plan.current.reason, channel_reason=plan.current.channel_reason,
            also_credited=list(plan.also_credited))
    keep = lambda ids: [o for i in ids if (o := out(i)) is not None]  # noqa: E731
    return StateOut(
        state=str(runner.state), signed_in=session is not None, login=session.login if session else None,
        paused_until=runner.paused_until, last_refresh=runner.last_refresh, current=current,
        needs_you=keep(plan.needs_you if plan else ()), up_next=keep(plan.queue if plan else ()),
        done=keep(plan.done if plan else ()),
    )


def history_view(claims: list[dict]) -> HistoryOut:
    """Flat and newest first. Day grouping is the page's job: only the browser knows the viewer's zone."""
    out = [ClaimOut(at=row["at"], campaign_id=row["campaign_id"], campaign=row["campaign"], game=row["game"],
                    rewards=[RewardOut(**r) for r in row["rewards"]]) for row in claims]
    return HistoryOut(total_rewards=sum(len(c.rewards) for c in out), claims=out)
