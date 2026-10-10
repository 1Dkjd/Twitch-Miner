"""Pure snapshots of runner/store state for the API. No I/O beyond the store reads passed in."""
from __future__ import annotations

from datetime import datetime, timedelta

from ..models import Campaign, campaign_active, campaign_minutes_needed, campaign_ratio, deadline_verdict
from ..planner import qualifies
from .models import (
    CampaignOut,
    CatalogOut,
    ChannelOut,
    ClaimOut,
    CurrentOut,
    DropOut,
    HistoryOut,
    RewardOut,
    StateOut,
    SwitchOut,
)

SWITCH_NOTICE_FOR = timedelta(minutes=10)


def campaign_out(c: Campaign, now: datetime, verdict: str | None,
                 maybe_unlinked: bool = False) -> CampaignOut:
    return CampaignOut(
        id=c.id, name=c.name, game=c.game.name, box_art_url=c.game.box_art_url, ends_at=c.ends_at,
        linked=c.linked, maybe_unlinked=maybe_unlinked, link_url=c.link_url,
        allowed_channels=list(c.allowed_logins),
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
                        current=None, needs_you=[], up_next=[], done=[], catalog=None)
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
        return campaign_out(c, now, v, maybe_unlinked=cid in getattr(runner, "maybe_unlinked", {}))

    current = None
    if plan and plan.current and runner.watching and (camp := out(plan.current.campaign_id)):
        favs = store.get_prefs().favourites
        w = runner.watching
        chosen = by_id[plan.current.campaign_id]
        others = sorted((ch for ch in runner.live if ch.login != w.login and qualifies(chosen, ch)),
                        key=lambda ch: (ch.login not in favs, -ch.viewers, ch.login))
        current = CurrentOut(
            campaign=camp, channel=ChannelOut(login=w.login, viewers=w.viewers, favourite=w.login in favs),
            reason=plan.current.reason, channel_reason=plan.current.channel_reason,
            also_credited=list(plan.also_credited),
            channels=[ChannelOut(login=ch.login, viewers=ch.viewers, favourite=ch.login in favs)
                      for ch in others])
    keep = lambda ids: [o for i in ids if (o := out(i)) is not None]  # noqa: E731
    never_games = store.get_prefs().never
    never = sorted((c for c in runner.campaigns if c.game.name in never_games and campaign_active(c, now)),
                   key=lambda c: (c.ends_at, c.id))
    return StateOut(
        state=str(runner.state), signed_in=session is not None, login=session.login if session else None,
        paused_until=runner.paused_until, last_refresh=runner.last_refresh, current=current,
        needs_you=keep(plan.needs_you if plan else ()), up_next=keep(plan.queue if plan else ()),
        done=keep(plan.done if plan else ()), catalog=_catalog(runner),
        last_switch=_switch(runner, now), next_check_at=runner.next_check_at,
        never=[campaign_out(c, now, None) for c in never],
    )


def _switch(runner, now: datetime) -> SwitchOut | None:
    sw = getattr(runner, "last_switch", None)
    if not sw or now - sw["at"] >= SWITCH_NOTICE_FOR:
        return None
    return SwitchOut(from_=sw["from"], to=sw["to"], at=sw["at"])


def _catalog(runner) -> CatalogOut | None:
    st = getattr(runner, "catalog_status", None)
    return CatalogOut(status=st[0], since=st[1]) if st else None


def history_view(claims: list[dict]) -> HistoryOut:
    """Flat and newest first. Day grouping is the page's job: only the browser knows the viewer's zone."""
    out = [ClaimOut(at=row["at"], campaign_id=row["campaign_id"], campaign=row["campaign"], game=row["game"],
                    rewards=[RewardOut(**r) for r in row["rewards"]]) for row in claims]
    return HistoryOut(total_rewards=sum(len(c.rewards) for c in out), claims=out)
