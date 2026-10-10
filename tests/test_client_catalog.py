"""Phase 2b Task 4: TwitchClient falls back to the catalogue when the dashboard is empty."""
import copy

from test_runner import FakePubSub, FakeStore, FakeWatcher

from dropwatch.runner import Runner
from dropwatch.twitch.client import TwitchClient

DROP = {"id": "d1", "name": "d", "requiredMinutesWatched": 60, "startAt": "2026-10-01T00:00:00Z",
        "endAt": "2026-10-20T00:00:00Z",
        "benefitEdges": [{"benefit": {"id": "b1", "name": "Hat", "imageAssetURL": "",
                                      "distributionType": "DIRECT_ENTITLEMENT"}}]}


def camp(cid, **extra):
    return {"id": cid, "name": f"name-{cid}", "status": "ACTIVE", "accountLinkURL": "https://link",
            "game": {"id": "1", "displayName": "Palia", "slug": "palia"}, "allow": {"isEnabled": False},
            "startAt": "2026-10-01T00:00:00Z", "endAt": "2026-10-20T00:00:00Z",
            "timeBasedDrops": [copy.deepcopy(DROP)], **extra}


def inventory(*camps):
    inv = {"dropCampaignsInProgress": list(camps), "gameEventDrops": []}
    return {"data": {"currentUser": {"inventory": inv}}}


class FakeGql:
    def __init__(self, inv, dash):
        self.inv, self.dash, self.ops = inv, dash, []

    async def run(self, payload):
        self.ops.append(payload["operationName"])
        if payload["operationName"] == "Inventory":
            return copy.deepcopy(self.inv)
        return {"data": {"currentUser": {"dropCampaigns": copy.deepcopy(self.dash)}}}

    async def run_many(self, payloads):
        return [{"data": {"user": {"dropCampaign": copy.deepcopy(next(
            c for c in self.dash if c["id"] == p["variables"]["dropID"]))}}} for p in payloads]


class FakeCatalog:
    def __init__(self, campaigns, status=("ok", None)):
        self._c, self.status, self.calls = campaigns, status, 0

    async def campaigns(self, *, force=False):
        self.calls += 1
        return copy.deepcopy(self._c)


async def test_dashboard_wins_when_present():
    cat = FakeCatalog({"x": camp("x")})
    c = TwitchClient(FakeGql(inventory(), [camp("a", self={"isAccountConnected": True})]), 42, catalog=cat)
    got = await c.campaigns()
    assert [x.id for x in got] == ["a"] and cat.calls == 0


async def test_catalog_used_when_dashboard_empty():
    c = TwitchClient(FakeGql(inventory(), None), 42, catalog=FakeCatalog({"x": camp("x")}))
    got = await c.campaigns()
    assert [x.id for x in got] == ["x"] and got[0].linked is None


async def test_inventory_overrides_catalog_fields():
    progressed = camp("x", self={"isAccountConnected": True})
    progressed["timeBasedDrops"][0]["self"] = {"currentMinutesWatched": 33, "isClaimed": False,
                                               "dropInstanceID": None}
    c = TwitchClient(FakeGql(inventory(progressed), None), 42, catalog=FakeCatalog({"x": camp("x")}))
    (x,) = await c.campaigns()
    assert x.linked is True and x.drops[0].current_minutes == 33


async def test_no_catalog_keeps_inventory_only():
    c = TwitchClient(FakeGql(inventory(camp("i", self={"isAccountConnected": True})), None), 42)
    assert [x.id for x in await c.campaigns()] == ["i"]


async def test_runner_reports_catalog_status():
    cat = FakeCatalog({}, status=("unreachable", "since"))
    r = Runner(TwitchClient(FakeGql(inventory(), None), 42, catalog=cat), FakeWatcher(), FakePubSub(),
               FakeStore(), user_id=42)
    assert r.catalog_status == ("unreachable", "since")
    r2 = Runner(TwitchClient(FakeGql(inventory(), None), 42), FakeWatcher(), FakePubSub(), FakeStore(),
                user_id=42)
    assert r2.catalog_status is None
