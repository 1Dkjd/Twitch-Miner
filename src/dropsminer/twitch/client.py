"""Twitch reads and writes the runner needs, built on Gql + parse."""
from __future__ import annotations

import logging
from datetime import datetime

from ..models import Campaign, LiveChannel, Prefs, campaign_active
from . import parse
from .gql import GqlError, op

log = logging.getLogger("dropsminer.client")


class TwitchClient:
    def __init__(self, gql, user_id: int):
        self._gql, self._user_id = gql, user_id

    async def campaigns(self) -> list[Campaign]:
        inv = await self._gql.run(op("Inventory"))
        claimed = parse.claimed_benefits(inv)
        data = parse.inventory_campaigns(inv)
        dash = parse.dashboard_campaigns(await self._gql.run(op("Campaigns")))
        if dash:
            ids = list(dash)
            details = await self._gql.run_many(
                [op("CampaignDetails", channelLogin=str(self._user_id), dropID=i) for i in ids])
            fetched = {}
            for item in details:
                dc = ((item.get("data") or {}).get("user") or {}).get("dropCampaign")
                if dc:
                    fetched[dc["id"]] = parse.merge(dash.get(dc["id"], {}), dc)
            data = parse.merge(data, fetched)
        out = []
        for raw in data.values():
            try:
                c = parse.to_campaign(raw, claimed)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Skipping campaign %s: unexpected shape (%s)", raw.get("id"), exc)
                continue
            if c is not None:
                out.append(c)
        return out

    async def live_channels(
        self, campaigns: list[Campaign], prefs: Prefs, now: datetime
    ) -> list[LiveChannel]:
        wanted = {c.game.id: c.game for c in campaigns
                  if campaign_active(c, now) and c.game.name not in prefs.never}
        seen: dict[str, LiveChannel] = {}
        for game in wanted.values():
            resp = await self._gql.run(op("GameDirectory", slug=game.slug,
                                          options={"systemFilters": ["DROPS_ENABLED"]}))
            for ch in parse.directory_channels(resp, game):
                seen.setdefault(ch.login, ch)
        acl = {lg for c in campaigns if c.game.id in wanted for lg in c.allowed_logins} - set(seen)
        acl |= set(prefs.favourites) - set(seen)
        if acl:
            for resp in await self._gql.run_many([op("GetStreamInfo", channel=lg) for lg in sorted(acl)]):
                ch = parse.stream_channel(resp)
                if ch is not None:
                    seen.setdefault(ch.login, ch)
        return list(seen.values())

    async def claim(self, claim_id: str) -> bool:
        try:
            resp = await self._gql.run(op("ClaimDrop", input={"dropInstanceID": claim_id}))
        except GqlError as exc:
            log.warning("Claim failed: %s", exc)
            return False
        result = (resp.get("data") or {}).get("claimDropRewards")
        return bool(result) and result.get("status") in (
            "ELIGIBLE_FOR_ALL", "DROP_INSTANCE_ALREADY_CLAIMED")

    async def current_drop(self, channel_id: int) -> tuple[str, int] | None:
        resp = await self._gql.run(op("CurrentDrop", channelID=str(channel_id)))
        cur = ((resp.get("data") or {}).get("currentUser") or {}).get("dropCurrentSession")
        return (cur["dropID"], cur["currentMinutesWatched"]) if cur else None
