import json
from datetime import UTC, datetime
from pathlib import Path

from dropsminer.models import Prefs
from dropsminer.twitch.client import TwitchClient

FX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


class FakeGql:
    def __init__(self):
        self.ops = []

    async def run(self, payload):
        self.ops.append(payload["operationName"])
        return {
            "Inventory": load("inventory.json"),
            "ViewerDropsDashboard": load("campaigns.json"),
            "DirectoryPage_Game": load("directory.json"),
            "DropsPage_ClaimDropRewards": {"data": {"claimDropRewards": {"status": "ELIGIBLE_FOR_ALL"}}},
            "DropCurrentSessionContext": {"data": {"currentUser": {"dropCurrentSession": {
                "dropID": "d1", "currentMinutesWatched": 23}}}},
        }[payload["operationName"]]

    async def run_many(self, payloads):
        details = {d["data"]["user"]["dropCampaign"]["id"]: d for d in load("campaign_details.json")}
        out = []
        for p in payloads:
            cid = p["variables"]["dropID"]
            out.append(details.get(cid) or {"data": {"user": {"dropCampaign": {"id": cid}}}})
        return out


async def test_campaigns_merges_inventory_dashboard_and_details():
    camps = await TwitchClient(FakeGql(), 42).campaigns()
    assert any(c.name == "Frights & Delights" for c in camps)
    assert len({c.id for c in camps}) == len(camps)


async def test_claim_and_current_drop():
    c = TwitchClient(FakeGql(), 42)
    assert await c.claim("inst") is True
    assert await c.current_drop(123) == ("d1", 23)


async def test_live_channels_skips_never_games():
    g = FakeGql()
    c = TwitchClient(g, 42)
    camps = await c.campaigns()
    never = frozenset(x.game.name for x in camps)
    await c.live_channels(camps, Prefs(never=never), datetime.now(UTC))
    assert "DirectoryPage_Game" not in g.ops
