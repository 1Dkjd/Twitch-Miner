"""Phase 2b Task 3: the public campaign catalogue (spec §4, 2026-10-10)."""
import json
from datetime import UTC, datetime, timedelta

from dropwatch.twitch.catalog import CATALOG_URL, Catalog
from dropwatch.twitch.transport import HttpResponse

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def reward(cid, end="2026-10-20T00:00:00Z", status="ACTIVE"):
    return {"id": cid, "name": cid, "status": status, "startAt": "2026-10-01T00:00:00Z", "endAt": end,
            "game": {"id": "1", "displayName": "Palia", "slug": "palia"}, "allow": {"isEnabled": False},
            "accountLinkURL": "https://link.example/palia", "timeBasedDrops": []}


def body(*rewards, updated=NOW):
    game = {"gameId": "1", "gameDisplayName": "Palia", "gameBoxArtURL": "https://static-cdn.jtvnw.net/ttv-boxart/1-120x160.jpg",
            "rewards": list(rewards)}
    return json.dumps({"lastUpdatedAt": updated.isoformat().replace("+00:00", "Z"),
                       "refreshIntervalSeconds": 60, "data": [game]})


class Net:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append((method, url, dict(headers)))
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return r


def make(tmp_path, *replies, now=None):
    clock = [now or NOW]
    return Catalog(Net(*replies), tmp_path / "catalog.json", clock=lambda: clock[0]), clock


async def test_flattens_and_filters_ended(tmp_path):
    cat, _ = make(tmp_path, HttpResponse(200, body(reward("a"), reward("old", end="2026-10-09T00:00:00Z"),
                                                    reward("up", status="UPCOMING"))))
    got = await cat.campaigns()
    assert set(got) == {"a", "up"}  # upcoming listed (Coming up); the planner only mines started ones
    assert cat.status == ("ok", None)


async def test_box_art_copied_into_game(tmp_path):
    cat, _ = make(tmp_path, HttpResponse(200, body(reward("a"))))
    assert (await cat.campaigns())["a"]["game"]["boxArtURL"] == "https://static-cdn.jtvnw.net/ttv-boxart/1-120x160.jpg"


async def test_fetches_at_most_hourly(tmp_path):
    cat, clock = make(tmp_path, HttpResponse(200, body(reward("a"))))
    await cat.campaigns()
    clock[0] = NOW + timedelta(minutes=59)
    await cat.campaigns()
    assert len(cat._t.calls) == 1
    clock[0] = NOW + timedelta(minutes=61)
    await cat.campaigns()
    assert len(cat._t.calls) == 2


async def test_unreachable_uses_cache_file_and_reports(tmp_path):
    first, _ = make(tmp_path, HttpResponse(200, body(reward("a"))))
    await first.campaigns()
    cat, _ = make(tmp_path, OSError("down"))
    got = await cat.campaigns()
    assert set(got) == {"a"}
    assert cat.status == ("unreachable", NOW)


async def test_unreachable_keeps_first_failure_time_and_retries_in_5_min(tmp_path):
    cat, clock = make(tmp_path, HttpResponse(503, "busy"))
    await cat.campaigns()
    clock[0] = NOW + timedelta(minutes=4)
    await cat.campaigns()
    assert len(cat._t.calls) == 1
    clock[0] = NOW + timedelta(minutes=6)
    await cat.campaigns()
    assert len(cat._t.calls) == 2 and cat.status == ("unreachable", NOW)


async def test_recovers_to_ok(tmp_path):
    cat, clock = make(tmp_path, OSError("down"), HttpResponse(200, body(reward("a"))))
    await cat.campaigns()
    clock[0] = NOW + timedelta(minutes=6)
    assert set(await cat.campaigns()) == {"a"} and cat.status == ("ok", None)


async def test_corrupt_cache_and_bad_body_are_empty_not_a_crash(tmp_path):
    (tmp_path / "catalog.json").write_bytes(b"{not json")
    cat, _ = make(tmp_path, HttpResponse(200, '{"data": "nope"}'))
    assert await cat.campaigns() == {}
    assert cat.status[0] == "unreachable"


async def test_one_malformed_record_is_skipped(tmp_path):
    bad = {"id": "x"}  # no endAt / status
    cat, _ = make(tmp_path, HttpResponse(200, body(reward("a"), bad)))
    assert set(await cat.campaigns()) == {"a"}


async def test_stale_after_6h(tmp_path):
    cat, _ = make(tmp_path, HttpResponse(200, body(reward("a"), updated=NOW - timedelta(hours=7))))
    await cat.campaigns()
    assert cat.status == ("stale", NOW - timedelta(hours=7))


async def test_no_twitch_headers_sent(tmp_path):
    cat, _ = make(tmp_path, HttpResponse(200, body(reward("a"))))
    await cat.campaigns()
    method, url, headers = cat._t.calls[0]
    assert (method, url) == ("GET", CATALOG_URL)
    assert not {"Client-Id", "Authorization", "X-Device-Id", "Client-Session-Id"} & set(headers)


async def test_cache_written_lf_only(tmp_path):
    cat, _ = make(tmp_path, HttpResponse(200, body(reward("a"))))
    await cat.campaigns()
    raw = (tmp_path / "catalog.json").read_bytes()
    assert b"\r" not in raw and json.loads(raw)["data"]


def test_catalog_url_from_env(monkeypatch):
    from dropwatch.twitch.catalog import catalog_url
    monkeypatch.delenv("DROPWATCH_CATALOG_URL", raising=False)
    assert catalog_url() == CATALOG_URL
    monkeypatch.setenv("DROPWATCH_CATALOG_URL", "off")
    assert catalog_url() is None
    monkeypatch.setenv("DROPWATCH_CATALOG_URL", "https://mirror.lan/drops")
    assert catalog_url() == "https://mirror.lan/drops"


async def test_uses_configured_url(tmp_path):
    cat = Catalog(Net(HttpResponse(200, body(reward("a")))), tmp_path / "c.json", clock=lambda: NOW,
                  url="https://mirror.lan/drops")
    await cat.campaigns()
    assert cat._t.calls[0][1] == "https://mirror.lan/drops"


async def test_third_party_images_links_and_account_state_are_dropped(tmp_path):
    r = reward("a")
    r["accountLinkURL"] = "http://plain.example"
    r["self"] = {"isAccountConnected": True}
    r["timeBasedDrops"] = [{"benefitEdges": [{"benefit": {"imageAssetURL": "https://tracker.example/x.png"}}]},
                           {"benefitEdges": [{"benefit": {"imageAssetURL": "https://static-cdn.jtvnw.net/x.png"}}]}]
    b = json.loads(body(r))
    b["data"][0]["gameBoxArtURL"] = "https://tracker.example/art.jpg"
    cat, _ = make(tmp_path, HttpResponse(200, json.dumps(b)))
    got = (await cat.campaigns())["a"]
    assert got["game"]["boxArtURL"] == ""
    assert got["accountLinkURL"] == ""
    assert "self" not in got
    imgs = [e["benefit"]["imageAssetURL"] for d in got["timeBasedDrops"] for e in d["benefitEdges"]]
    assert imgs == ["", "https://static-cdn.jtvnw.net/x.png"]


async def test_a_sudden_collapse_keeps_the_last_good_list(tmp_path):
    many = body(*[reward(f"c{i}") for i in range(30)])
    cat, clock = make(tmp_path, HttpResponse(200, many), HttpResponse(200, body(reward("only"))))
    assert len(await cat.campaigns()) == 30
    clock[0] = NOW + timedelta(hours=2)
    got = await cat.campaigns()
    assert len(got) == 30
    assert cat.status[0] == "unreachable"


async def test_oversized_response_is_refused(tmp_path, monkeypatch):
    import dropwatch.twitch.catalog as mod
    monkeypatch.setattr(mod, "MAX_BODY", 100)
    cat, _ = make(tmp_path, HttpResponse(200, body(reward("a"))))
    assert await cat.campaigns() == {}
    assert cat.status[0] == "unreachable"
