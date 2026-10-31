import json

import pytest

from dropwatch.twitch.constants import ANDROID_APP
from dropwatch.twitch.gql import AuthExpired, Gql, GqlError, TwitchUnreachable, op
from dropwatch.twitch.session import TwitchSession, gql_headers
from dropwatch.twitch.transport import HttpResponse

S = TwitchSession("tok", 42, "me", "dev", ANDROID_APP.client_id, "sess")


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append((method, url, headers, json))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


async def nosleep(_):
    return None


def ok(payload):
    return HttpResponse(200, json.dumps(payload))


def test_op_merges_variables():
    p = op("CampaignDetails", channelLogin="42", dropID="c1")
    assert p["operationName"] == "DropCampaignDetails"
    assert p["variables"] == {"channelLogin": "42", "dropID": "c1"}
    assert p["extensions"]["persistedQuery"]["version"] == 1
    nested = op("GameDirectory", slug="palia", options={"systemFilters": ["DROPS_ENABLED"]})
    assert nested["variables"]["options"]["systemFilters"] == ["DROPS_ENABLED"]
    assert nested["variables"]["options"]["sort"] == "RELEVANCE"


def test_gql_headers_carry_auth_and_client():
    h = gql_headers(S, ANDROID_APP)
    assert h["Authorization"] == "OAuth tok"
    assert h["Client-Id"] == ANDROID_APP.client_id
    assert h["X-Device-Id"] == "dev"
    assert h["Client-Session-Id"] == "sess"


async def test_run_returns_data():
    t = FakeTransport([ok({"data": {"x": 1}})])
    assert await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory")) == {"data": {"x": 1}}


async def test_run_many_batches_by_20():
    t = FakeTransport([ok([{"data": {}}] * 20), ok([{"data": {}}] * 5)])
    out = await Gql(t, lambda: S, sleep=nosleep).run_many([op("Inventory")] * 25)
    assert len(out) == 25
    assert [len(c[3]) for c in t.calls] == [20, 5]


async def test_retries_once_on_service_error():
    err = ok({"errors": [{"message": "service error"}], "extensions": {"operationName": "Inventory"}})
    t = FakeTransport([err, ok({"data": {"y": 2}})])
    assert (await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory")))["data"] == {"y": 2}


async def test_other_gql_error_raises():
    t = FakeTransport([ok({"errors": [{"message": "boom"}]})])
    with pytest.raises(GqlError, match="boom"):
        await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory"))


async def test_401_raises_auth_expired():
    t = FakeTransport([HttpResponse(401, '{"error":"Unauthorized"}')])
    with pytest.raises(AuthExpired):
        await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory"))


async def test_network_errors_become_unreachable_after_3_tries():
    t = FakeTransport([OSError("down")] * 3)
    with pytest.raises(TwitchUnreachable):
        await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory"))
    assert len(t.calls) == 3


async def test_5xx_retried_then_succeeds():
    t = FakeTransport([HttpResponse(503, "busy"), ok({"data": {}})])
    assert await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory")) == {"data": {}}


TIMEOUT = {"errors": [{"message": "service timeout"}], "data": None}


async def test_run_many_retries_only_the_ops_that_timed_out():
    # 2026-10-31: one timed-out op used to resend (and then fail) its whole chunk
    t = FakeTransport([ok([{"data": {"a": 1}}, TIMEOUT, {"data": {"c": 3}}]), ok([{"data": {"b": 2}}])])
    out = await Gql(t, lambda: S, sleep=nosleep).run_many([op("Inventory")] * 3)
    assert [o["data"] for o in out] == [{"a": 1}, {"b": 2}, {"c": 3}]
    assert [len(c[3]) for c in t.calls] == [3, 1]


async def test_run_many_keeps_partial_results_when_an_op_keeps_failing():
    t = FakeTransport([ok([{"data": {"a": 1}}, TIMEOUT]), ok([TIMEOUT]), ok([TIMEOUT])])
    out = await Gql(t, lambda: S, sleep=nosleep).run_many([op("Inventory")] * 2)
    assert out[0]["data"] == {"a": 1} and not out[1].get("data")
    assert len(t.calls) == 3


async def test_run_many_raises_when_every_op_failed_with_a_short_message():
    t = FakeTransport([ok([TIMEOUT] * 3)] * 3)
    with pytest.raises(GqlError) as e:
        await Gql(t, lambda: S, sleep=nosleep).run_many([op("Inventory")] * 3)
    assert str(e.value) == "service timeout ×3"
