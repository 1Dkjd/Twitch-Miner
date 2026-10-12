"""Raw GQL JSON -> models. Field names ported from reference inventory.py and channel.py."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import chain

from ..models import Campaign, Drop, Game, LiveChannel, Reward, game_slug


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _game(g: dict) -> Game:
    art = re.sub(r"-\d+x\d+(?=\.\w+$)", "", g.get("boxArtURL") or "")
    name = g.get("displayName") or g["name"]
    slug = g.get("slug") or game_slug(name)
    return Game(int(g["id"]), name, slug, art)


def claimed_benefits(inventory_resp: dict) -> dict[str, datetime]:
    inv = inventory_resp["data"]["currentUser"]["inventory"]
    return {b["id"]: ts(b["lastAwardedAt"]) for b in (inv.get("gameEventDrops") or [])}


def inventory_campaigns(inventory_resp: dict) -> dict[str, dict]:
    inv = inventory_resp["data"]["currentUser"]["inventory"]
    return {c["id"]: c for c in (inv.get("dropCampaignsInProgress") or [])}


def dashboard_campaigns(campaigns_resp: dict) -> dict[str, dict]:
    listed = campaigns_resp["data"]["currentUser"]["dropCampaigns"] or []
    return {c["id"]: c for c in listed if c.get("status") in ("ACTIVE", "UPCOMING")}


def merge(primary: dict, secondary: dict) -> dict:
    out: dict = {}
    for key in set(chain(primary, secondary)):
        if key in primary and key in secondary:
            a, b = primary[key], secondary[key]
            out[key] = merge(a, b) if isinstance(a, dict) and isinstance(b, dict) else a
        else:
            out[key] = primary[key] if key in primary else secondary[key]
    return out


def _drop(d: dict, claimed: dict[str, datetime]) -> Drop:
    rewards = tuple(
        Reward(b["benefit"]["id"], b["benefit"]["name"].strip(), b["benefit"].get("imageAssetURL", ""),
               b["benefit"].get("distributionType", "UNKNOWN"))
        for b in (d.get("benefitEdges") or [])
    )
    start, end = ts(d["startAt"]), ts(d["endAt"])
    me = d.get("self")
    if me:
        is_claimed, claim_id = bool(me.get("isClaimed")), me.get("dropInstanceID")
        current = me.get("currentMinutesWatched") or 0
    else:
        stamps = [claimed[r.id] for r in rewards if r.id in claimed]
        is_claimed = bool(stamps) and all(start <= s < end for s in stamps)
        claim_id, current = None, 0
    required = d["requiredMinutesWatched"]
    if is_claimed:
        current = required
    return Drop(d["id"], d["name"].strip(), rewards, start, end, required, current, is_claimed, claim_id,
                tuple(p["id"] for p in (d.get("preconditionDrops") or [])))


def to_campaign(raw: dict, claimed: dict[str, datetime]) -> Campaign | None:
    if raw.get("game") is None or "timeBasedDrops" not in raw:
        return None
    allow = raw.get("allow") or {}
    allowed = tuple(
        ch["name"] for ch in (allow.get("channels") or [])
    ) if allow.get("isEnabled", True) else ()
    return Campaign(
        # display names are trimmed (Twitch sends "DbD: October of Horror "); game names are not: they key
        # the saved Priority and Never lists
        raw["id"], raw["name"].strip(), _game(raw["game"]), ts(raw["startAt"]), ts(raw["endAt"]),
        # no "self" (catalogue records): Twitch hasn't told us whether the account is linked
        bool(raw["self"].get("isAccountConnected")) if isinstance(raw.get("self"), dict) else None,
        raw.get("accountLinkURL") or "",
        allowed, tuple(_drop(d, claimed) for d in raw["timeBasedDrops"]),
    )


def directory_channels(resp: dict, game: Game) -> list[LiveChannel]:
    g = (resp.get("data") or {}).get("game")
    if not g:
        return []
    out = []
    for edge in g["streams"]["edges"]:
        node = edge["node"]
        b = node.get("broadcaster")
        if b is None:
            continue
        out.append(LiveChannel(int(b["id"]), b["login"], game.id, node.get("viewersCount") or 0,
                               True, str(node["id"]), game.name))
    return out


def stream_channel(resp: dict) -> LiveChannel | None:
    user = (resp.get("data") or {}).get("user")
    if not user or not user.get("stream"):
        return None
    game = (user.get("broadcastSettings") or {}).get("game")
    return LiveChannel(int(user["id"]), user["login"], int(game["id"]) if game else None,
                       user["stream"].get("viewersCount") or 0, True, str(user["stream"]["id"]),
                       (game or {}).get("displayName") or (game or {}).get("name") or "")
