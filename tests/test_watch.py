import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from dropsminer.models import LiveChannel
from dropsminer.twitch.session import TwitchSession
from dropsminer.twitch.transport import HttpResponse
from dropsminer.twitch.watch import Watcher, find_settings_js, find_spade_url, watch_payload

CH = LiveChannel(77, "streamer", 1, 10, True, "b123", "Palia")
S = TwitchSession("tok", 42, "me", "dev", "cid", "sess")
NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def test_payload_is_base64_minute_watched():
    body = watch_payload(CH, 42, NOW)
    events = json.loads(base64.b64decode(body["data"]))
    props = events[0]["properties"]
    assert events[0]["event"] == "minute-watched"
    assert props["broadcast_id"] == "b123" and props["channel_id"] == "77"
    assert props["channel"] == "streamer" and props["user_id"] == 42
    assert props["minutes_logged"] == 1 and props["game"] == "Palia" and props["game_id"] == "1"


def test_find_spade_url_variants():
    assert find_spade_url('x "spade_url": "https://video-edge.example/abc" y') == \
        "https://video-edge.example/abc"
    assert find_spade_url('"spadeUrl":"https://spade.twitch.tv/track"') == "https://spade.twitch.tv/track"
    assert find_spade_url("nothing here") is None


def test_find_settings_js():
    html = '<script src="https://static.twitchcdn.net/config/settings.0123456789abcdef0123456789abcdef.js">'
    assert find_settings_js(html).endswith(".js")


def test_real_channel_page_yields_a_url():
    html = (Path(__file__).parent / "fixtures" / "channel_page.html").read_text(encoding="utf-8")
    assert find_spade_url(html) or find_settings_js(html)


class T:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append((method, url, data))
        return self.replies.pop(0)


async def test_send_fetches_spade_once_then_posts():
    page = HttpResponse(200, '"spade_url": "https://spade.example/x"')
    t = T([page, HttpResponse(204, ""), HttpResponse(204, "")])
    w = Watcher(t, lambda: S)
    assert await w.send(CH, NOW) is True
    assert await w.send(CH, NOW) is True
    assert [c[0] for c in t.calls] == ["GET", "POST", "POST"]
    assert t.calls[1][1] == "https://spade.example/x"


async def test_send_reports_failure():
    t = T([HttpResponse(200, '"spade_url": "https://spade.example/x"'), HttpResponse(400, "")])
    assert await Watcher(t, lambda: S).send(CH, NOW) is False
