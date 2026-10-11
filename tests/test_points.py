"""Channel points (2026-10-10): claim the bonus chest on whichever channel is being watched, while
"Also claim channel points" (claim_points, on by default per the approved v7 mockup) is on. A read-only probe
the same day showed Twitch answers ChannelPointsContext for the TV session."""
from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.runner import Runner
from dropwatch.store import Store
from dropwatch.twitch.client import TwitchClient
from dropwatch.twitch.pubsub import PointsClaimable, topic


class PointsClient(FakeClient):
    def __init__(self, *a, waiting=None):
        super().__init__(*a)
        self.points_claims, self.waiting, self.context_calls = [], waiting, []

    async def claim_points(self, channel_id, claim_id):
        self.points_claims.append((channel_id, claim_id))
        return True

    async def waiting_points_claim(self, login):
        self.context_calls.append(login)
        return self.waiting


def make(tmp_path, on=True, waiting=None):
    st = Store(tmp_path / "d.db")
    st.put_settings({"claim_points": on})
    client = PointsClient([camp()], [chan("a", 7)], waiting=waiting)
    pubsub = FakePubSub()
    return Runner(client, FakeWatcher(), pubsub, st, user_id=42, clock=lambda: NOW), client, pubsub


async def test_listens_and_claims_a_chest_as_it_appears(tmp_path):
    r, client, pubsub = make(tmp_path)
    await r.refresh()
    assert topic("user_points", 42) in pubsub.topics
    await r.handle(PointsClaimable(7, "claim-1"))
    assert client.points_claims == [(7, "claim-1")]


async def test_a_chest_already_waiting_is_claimed_at_the_refresh(tmp_path):
    r, client, _ = make(tmp_path, waiting=(7, "claim-0"))
    await r.refresh()
    assert client.context_calls == ["a"] and client.points_claims == [(7, "claim-0")]


async def test_switched_off_neither_listens_nor_claims(tmp_path):
    r, client, pubsub = make(tmp_path, on=False, waiting=(7, "claim-0"))
    await r.refresh()
    await r.handle(PointsClaimable(7, "claim-1"))
    assert topic("user_points", 42) not in pubsub.topics
    assert client.points_claims == [] and client.context_calls == []


async def test_client_claim_and_context_requests():
    sent = []

    class G:
        async def run(self, payload):
            sent.append(payload)
            if payload["operationName"] == "ChannelPointsContext":
                return {"data": {"community": {"channel": {"id": "7", "self": {"communityPoints": {
                    "availableClaim": {"id": "claim-9"}}}}}}}
            return {"data": {"claimCommunityPoints": {"claim": {"id": "claim-9"}, "currentPoints": 10480}}}

    c = TwitchClient(G(), 42)
    assert await c.waiting_points_claim("lvndmark") == (7, "claim-9")
    assert sent[0]["variables"] == {"channelLogin": "lvndmark"}
    assert await c.claim_points(7, "claim-9") is True
    assert sent[1]["variables"] == {"input": {"claimID": "claim-9", "channelID": "7"}}


async def test_a_broken_points_check_never_breaks_the_refresh(tmp_path):
    r, client, _ = make(tmp_path)

    async def boom(login):
        raise AttributeError("not an error the runner already expects")

    client.waiting_points_claim = boom
    await r.refresh()
    assert r.plan.current is not None and r.state == "mining"
