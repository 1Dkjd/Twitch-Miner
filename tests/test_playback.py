"""Simulated HLS playback (Twitch credits drop minutes only while 'playing', upstream DevilXD#1183).

Port of JourneyDocker/TwitchDropsMiner 870c8b5 (MIT), see reference/journeydocker/channel.py.
"""
from datetime import UTC, datetime

from dropsminer.models import LiveChannel
from dropsminer.twitch.session import TwitchSession
from dropsminer.twitch.transport import HttpResponse
from dropsminer.twitch.watch import Watcher, playlist_urls

CH = LiveChannel(77, "streamer", 1, 10, True, "b123", "Palia")
S = TwitchSession("tok", 42, "me", "dev", "cid", "sess")
NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=6000000
https://video.example/chunked/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=200000
https://video.example/160p/index.m3u8
"""


def media(*names):
    body = "#EXTM3U\n#EXT-X-TARGETDURATION:2\n"
    return body + "".join(f"#EXTINF:2.000,live\n{n}\n" for n in names)


def test_playlist_urls_master_and_media():
    assert playlist_urls(MASTER, "https://usher.example/x.m3u8", master=True) == [
        "https://video.example/chunked/index.m3u8", "https://video.example/160p/index.m3u8"]
    assert playlist_urls(media("a.ts", "b.ts"), "https://video.example/160p/index.m3u8") == [
        "https://video.example/160p/a.ts", "https://video.example/160p/b.ts"]


def test_playlist_urls_rejects_garbage():
    assert playlist_urls("not a playlist", "https://x/y.m3u8") == []
    assert playlist_urls("#EXTM3U\nstray.ts\n", "https://x/y.m3u8") == []           # URI without tag
    assert playlist_urls("#EXTM3U\n#EXT-X-STREAM-INF:B=1\nfile.ts\n", "https://x/y.m3u8", master=True) == []


class FakeGql:
    def __init__(self, token=True):
        self.token, self.calls = token, 0

    async def run(self, payload):
        self.calls += 1
        assert payload["operationName"] == "PlaybackAccessToken"
        assert payload["variables"]["login"] == "streamer"
        tok = {"value": "v", "signature": "s"} if self.token else None
        return {"data": {"streamPlaybackAccessToken": tok}}


class Net:
    """Scripted CDN: serves the master, then successive media playlists; records every call."""

    def __init__(self, medias, *, media_status=200, raise_on=None):
        self.medias, self.media_status, self.raise_on, self.calls = list(medias), media_status, raise_on, []

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append((method, url))
        if self.raise_on and self.raise_on in url:
            raise OSError("reset")
        if "usher" in url:
            assert "sig=s" in url and "token=v" in url
            return HttpResponse(200, MASTER)
        if url.endswith("160p/index.m3u8"):
            return HttpResponse(self.media_status, self.medias.pop(0) if self.media_status == 200 else "")
        if method == "HEAD":
            return HttpResponse(200, "")
        if method == "GET":  # channel page for the spade URL
            return HttpResponse(200, '"spade_url": "https://spade.example/x"')
        if method == "POST":
            return HttpResponse(204, "")
        raise AssertionError(url)


async def test_send_plays_lowest_quality_heads_segments_and_spades_once():
    clock = [1000.0]
    net = Net([media("a.ts", "b.ts"), media("b.ts", "c.ts")])
    w = Watcher(net, lambda: S, FakeGql(), clock=lambda: clock[0])
    assert await w.send(CH, NOW) is True
    heads = [u for m, u in net.calls if m == "HEAD"]
    assert heads == ["https://video.example/160p/a.ts", "https://video.example/160p/b.ts"]
    assert [u for m, u in net.calls if m == "POST"] == ["https://spade.example/x"]
    net.calls.clear()
    clock[0] += 10
    assert await w.send(CH, NOW) is True
    assert [u for m, u in net.calls if m == "HEAD"] == ["https://video.example/160p/c.ts"]  # only new
    assert not [c for c in net.calls if c[0] == "POST"]                                    # spade waits 59 s
    assert not [c for c in net.calls if "usher" in c[1]]                                   # master cached


async def test_spade_resent_after_interval():
    clock = [1000.0]
    net = Net([media("a.ts"), media("b.ts")])
    w = Watcher(net, lambda: S, FakeGql(), clock=lambda: clock[0])
    await w.send(CH, NOW)
    clock[0] += 60
    net.calls.clear()
    await w.send(CH, NOW)
    assert [c for c in net.calls if c[0] == "POST"]


async def test_no_spade_when_playback_fails():
    net = Net([], media_status=404)
    w = Watcher(net, lambda: S, FakeGql(), clock=lambda: 0.0)
    assert await w.send(CH, NOW) is False
    assert not [c for c in net.calls if c[0] == "POST"]


async def test_no_token_means_no_playback():
    net = Net([media("a.ts")])
    assert await Watcher(net, lambda: S, FakeGql(token=False), clock=lambda: 0.0).send(CH, NOW) is False


async def test_media_404_drops_cached_url_and_refetches_master():
    clock = [0.0]
    net = Net([media("a.ts")])
    gql = FakeGql()
    w = Watcher(net, lambda: S, gql, clock=lambda: clock[0])
    assert await w.send(CH, NOW) is True
    net.media_status = 404
    assert await w.send(CH, NOW) is False
    net.media_status, net.medias = 200, [media("z.ts")]
    assert await w.send(CH, NOW) is True
    assert gql.calls == 2  # new token after the 404


async def test_new_broadcast_resets_segment_memory():
    net = Net([media("a.ts"), media("a.ts")])
    w = Watcher(net, lambda: S, FakeGql(), clock=lambda: 0.0)
    await w.send(CH, NOW)
    other = LiveChannel(77, "streamer", 1, 10, True, "b999", "Palia")
    net.calls.clear()
    await w.send(other, NOW)
    assert [u for m, u in net.calls if m == "HEAD"] == ["https://video.example/160p/a.ts"]


async def test_network_error_is_a_failed_send():
    net = Net([media("a.ts")], raise_on="usher")
    assert await Watcher(net, lambda: S, FakeGql(), clock=lambda: 0.0).send(CH, NOW) is False
