"""Phase 2b Task 3: the public campaign catalogue (spec §4, 2026-10-10)."""
import json
from datetime import UTC, datetime, timedelta

from dropwatch.twitch.catalog import CATALOG_URL, Catalog
from dropwatch.twitch.transport import HttpResponse

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def reward(cid, end="2026-10-20T00:00:00Z", status="ACTIVE"):
    return {"id": cid, "name": cid, "status": status, "startAt": "2026-10-01T00:00:00Z", "endAt": end,
            "game": {"id": "1", "displayName": "Palia", "slug": "palia"}, "allow": {"isEnabled": False},
            "accountLinkURL": "https://link", "timeBasedDrops": []}


def body(*rewards, updated=NOW):
    game = {"gameId": "1", "gameDisplayName": "Palia", "gameBoxArtURL": "https://art/palia-120x160.jpg",
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
    assert set(got) == {"a"}
    assert cat.status == ("ok", None)


async def test_box_art_copied_into_game(tmp_path):
    cat, _ = make(tmp_path, HttpResponse(200, body(reward("a"))))
    assert (await cat.campaigns())["a"]["game"]["boxArtURL"] == "https://art/palia-120x160.jpg"


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
