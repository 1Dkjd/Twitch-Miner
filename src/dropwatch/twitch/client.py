"""Twitch reads and writes the runner needs, built on Gql + parse."""
from __future__ import annotations

import logging
from datetime import datetime

from ..models import (
    Campaign,
    LiveChannel,
    Prefs,
    account_eligible,
    campaign_active,
    drop_earnable_now,
)
from . import parse
from .gql import GqlError, op

log = logging.getLogger("dropwatch.client")


class TwitchClient:
    def __init__(self, gql, user_id: int, catalog=None):
        self._gql, self._user_id = gql, user_id
        self.catalog = catalog  # campaign list when Twitch hides it (TV login, spec §4)

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
        elif self.catalog is not None:
            # the TV login sees no dashboard: discover from the catalogue, the account's Inventory wins
            data = parse.merge(data, await self.catalog.campaigns())
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
        # Only campaigns the planner could actually pick: active, not Never, account-eligible,
        # with a drop earnable now. Games whose minable campaigns are all channel-restricted
        # need no directory lookup, only their allowed channels (reference twitch.py ~760-800).
        minable = [c for c in campaigns
                   if campaign_active(c, now) and c.game.name not in prefs.never
                   and account_eligible(c, prefs)
                   and any(drop_earnable_now(c, d, now) for d in c.drops)]
        open_games = {c.game.id: c.game for c in minable if not c.allowed_logins}
        seen: dict[str, LiveChannel] = {}
        for game in open_games.values():
            resp = await self._gql.run(op("GameDirectory", slug=game.slug,
                                          options={"systemFilters": ["DROPS_ENABLED"]}))
            for ch in parse.directory_channels(resp, game):
                seen.setdefault(ch.login, ch)
        acl = {lg for c in minable for lg in c.allowed_logins} - set(seen)
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
