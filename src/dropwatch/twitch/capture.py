"""Record real responses from the signed-in account into scrubbed test fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import game_slug
from .constants import ANDROID_APP
from .gql import Gql, op
from .session import TwitchSession, base_headers
from .transport import HttpTransport


def scrub(obj: Any, secrets: dict[str, str]) -> Any:
    secrets = {k: v for k, v in secrets.items() if k}
    if isinstance(obj, dict):
        return {k: scrub(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, secrets) for v in obj]
    if isinstance(obj, int) and not isinstance(obj, bool) and str(obj) in secrets:
        return secrets[str(obj)]
    if isinstance(obj, str):
        for secret, placeholder in secrets.items():
            obj = obj.replace(secret, placeholder)
    return obj


async def run_capture(gql: Gql, transport: HttpTransport, s: TwitchSession, out: Path) -> list[Path]:
    secrets = {s.access_token: "<TOKEN>", str(s.user_id): "<USER_ID>", s.login: "<LOGIN>",
               s.device_id: "<DEVICE_ID>", s.session_id: "<SESSION_ID>"}
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(name: str, data: Any) -> None:
        p = out / name
        text = json.dumps(scrub(data, secrets), indent=1, sort_keys=True) if not isinstance(data, str) \
            else scrub(data, secrets)
        p.write_bytes(text.encode("utf-8"))
        written.append(p)

    inventory = await gql.run(op("Inventory"))
    save("inventory.json", inventory)
    campaigns = await gql.run(op("Campaigns"))
    save("campaigns.json", campaigns)
    listed = (campaigns["data"]["currentUser"]["dropCampaigns"] or [])[:3]
    details = await gql.run_many(
        [op("CampaignDetails", channelLogin=str(s.user_id), dropID=c["id"]) for c in listed]
    )
    save("campaign_details.json", details)
    # Try games until one has live drops-enabled streams, so the directory, stream and
    # channel-page fixtures contain real channels rather than an empty list.
    active = [c for c in (campaigns["data"]["currentUser"]["dropCampaigns"] or [])
              if c.get("status") == "ACTIVE"]
    for camp in active[:15]:
        g = camp["game"]
        slug = g.get("slug") or game_slug(g.get("displayName") or g.get("name") or "")
        directory = await gql.run(op(
            "GameDirectory", slug=slug, limit=5, options={"systemFilters": ["DROPS_ENABLED"]}))
        edges = (directory.get("data", {}).get("game") or {}).get("streams", {}).get("edges") or []
        if not edges:
            continue
        save("directory.json", directory)
        login = edges[0]["node"]["broadcaster"]["login"]
        save("stream_info.json", await gql.run(op("GetStreamInfo", channel=login)))
        page = await transport.request("GET", f"https://www.twitch.tv/{login}",
                                       headers=base_headers(None, ANDROID_APP))
        save("channel_page.html", page.text)  # str: scrubbed as text, not JSON-encoded
        break
    return written
