"""Phase 2b Task 1: every Twitch call is sent as the session's own client (TV or Android)."""
from datetime import UTC, datetime

from dropwatch.models import LiveChannel
from dropwatch.twitch.constants import ANDROID_APP, SMARTBOX, client_for
from dropwatch.twitch.gql import Gql, op
from dropwatch.twitch.session import TwitchSession
from dropwatch.twitch.transport import HttpResponse
from dropwatch.twitch.watch import Watcher

TV = TwitchSession("tok", 42, "me", "dev", SMARTBOX.client_id, "sess")
ANDROID = TwitchSession("tok", 42, "me", "dev", ANDROID_APP.client_id, "sess")
CH = LiveChannel(7, "streamer", 1, 10, True, "b1", "Palia")


class Rec:
    def __init__(self, replies=None):
        self.calls, self.replies = [], replies or {}

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append((method, url, dict(headers)))
        for key, resp in self.replies.items():
            if key in url:
                return resp
        return HttpResponse(200, '{"data": {}}')


def test_client_for_known_and_unknown():
    assert client_for(SMARTBOX.client_id) is SMARTBOX
    assert client_for(ANDROID_APP.client_id) is ANDROID_APP
    assert client_for("someone-else") is ANDROID_APP


async def test_gql_sends_session_client():
    for session, client in ((TV, SMARTBOX), (ANDROID, ANDROID_APP)):
        t = Rec()
        await Gql(t, lambda s=session: s).run(op("Inventory"))
        headers = t.calls[0][2]
        assert headers["Client-Id"] == client.client_id
        assert headers["User-Agent"] == client.user_agent


async def test_explicit_client_still_wins():
    t = Rec()
    await Gql(t, lambda: TV, client=ANDROID_APP).run(op("Inventory"))
    assert t.calls[0][2]["Client-Id"] == ANDROID_APP.client_id


async def test_spade_post_uses_session_client_page_fetch_stays_android():
    page = HttpResponse(200, '"spade_url":"https://spade.example/track"')
    t = Rec({"www.twitch.tv": page, "spade.example": HttpResponse(204, "")})
    w = Watcher(t, lambda: TV, None)
    await w._post_spade(CH, datetime(2026, 10, 10, tzinfo=UTC))
    page_call = next(c for c in t.calls if "www.twitch.tv" in c[1])
    spade_call = next(c for c in t.calls if c[0] == "POST")
    assert page_call[2]["Client-Id"] == ANDROID_APP.client_id
    assert spade_call[2]["Client-Id"] == SMARTBOX.client_id
