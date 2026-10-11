import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from dropwatch.models import LiveChannel
from dropwatch.twitch.watch import find_settings_js, find_spade_url, watch_payload

CH = LiveChannel(77, "streamer", 1, 10, True, "b123", "Palia")
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


def test_client_time_matches_reference_format():
    # reference utils.isonow(): milliseconds and a literal Z, e.g. 2026-10-09T12:00:00.000Z
    import re
    props = json.loads(base64.b64decode(watch_payload(CH, 42, NOW)["data"]))[0]["properties"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", props["client_time"])


def test_heartbeat_says_it_comes_from_the_site_player():
    # 2026-10-11: without player=site the account earned no channel points at all (so no chests); the
    # reference points miner (rdavydov, same TV client) sends it
    props = json.loads(base64.b64decode(watch_payload(CH, 42, NOW)["data"]))[0]["properties"]
    assert props["player"] == "site"
