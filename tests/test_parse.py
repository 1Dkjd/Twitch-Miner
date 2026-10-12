import json
from pathlib import Path

from dropwatch.models import Game
from dropwatch.twitch.parse import (
    claimed_benefits,
    dashboard_campaigns,
    directory_channels,
    inventory_campaigns,
    merge,
    stream_channel,
    to_campaign,
    ts,
)

FX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_ts_parses_twitch_timestamps():
    assert ts("2026-10-13T13:59:59Z").tzinfo is not None
    assert ts("2026-10-13T13:59:59.123Z").second == 59


def test_merge_primary_wins_and_recurses():
    a = {"x": 1, "d": {"p": 1}, "only_a": True}
    b = {"x": 2, "d": {"p": 2, "q": 3}, "only_b": True}
    assert merge(a, b) == {"x": 1, "d": {"p": 1, "q": 3}, "only_a": True, "only_b": True}


def test_real_inventory_parses_known_campaigns():
    inv = load("inventory.json")
    raw = inventory_campaigns(inv)
    names = {c["name"] for c in raw.values()}
    # campaigns in progress on Nick's account at capture time (spike 2026-10-09)
    assert "Frights & Delights" in names
    claimed = claimed_benefits(inv)
    camps = [c for r in raw.values() if (c := to_campaign(r, claimed))]
    palia = next(c for c in camps if c.name == "Frights & Delights")
    assert palia.game.name == "Palia"
    assert len(palia.drops) == 3
    assert all(d.required_minutes > 0 for d in palia.drops)


def test_real_dashboard_and_details_build_campaigns():
    dash = dashboard_campaigns(load("campaigns.json"))
    assert dash, "dashboard must list campaigns (spec §4 decisive check)"
    details = load("campaign_details.json")
    for item in details:
        dc = item["data"]["user"]["dropCampaign"]
        merged = merge(dash.get(dc["id"], {}), dc)
        camp = to_campaign(merged, {})
        if camp is not None:
            assert camp.ends_at > camp.starts_at
            assert isinstance(camp.allowed_logins, tuple)


def test_game_null_is_dropped():
    assert to_campaign({"id": "x", "game": None}, {}) is None


def test_claimed_inferred_from_benefits_when_no_self_edge():
    raw = {
        "id": "c", "name": "C", "status": "ACTIVE",
        "game": {"id": "1", "displayName": "G", "slug": "g", "boxArtURL": "u-285x380.jpg"},
        "self": {"isAccountConnected": True}, "accountLinkURL": "",
        "startAt": "2026-10-01T00:00:00Z", "endAt": "2026-10-20T00:00:00Z",
        "allow": {"channels": None, "isEnabled": True},
        "timeBasedDrops": [{
            "id": "d", "name": "D", "startAt": "2026-10-01T00:00:00Z",
            "endAt": "2026-10-20T00:00:00Z", "requiredMinutesWatched": 60,
            "preconditionDrops": None,
            "benefitEdges": [{"benefit": {"id": "b1", "name": "B", "distributionType": "BADGE",
                                          "imageAssetURL": "i"}}],
        }],
    }
    c = to_campaign(raw, {"b1": ts("2026-10-05T00:00:00Z")})
    assert c.drops[0].claimed is True
    assert c.has_badge_or_emote


def test_real_directory_channels():
    game = Game(1, "X", "x")
    chans = directory_channels(load("directory.json"), game)
    for ch in chans:
        assert ch.login and ch.broadcast_id and ch.drops_enabled
        assert ch.game_id is not None


def test_real_stream_info():
    ch = stream_channel(load("stream_info.json"))
    assert ch is None or (ch.login and ch.broadcast_id)


def test_campaign_drop_and_reward_names_are_trimmed_game_names_are_not():
    # Twitch sends "DbD: October of Horror " (trailing space); it showed as a double space in notices.
    # Game names stay exactly as Twitch sends them: they are the keys of the saved Priority and Never lists.
    raw = {
        "id": "c", "name": "  DbD: October of Horror ", "status": "ACTIVE",
        "game": {"id": "1", "displayName": "Dead by Daylight ", "slug": "dbd", "boxArtURL": "u-285x380.jpg"},
        "self": {"isAccountConnected": False}, "accountLinkURL": "",
        "startAt": "2026-10-01T00:00:00Z", "endAt": "2026-10-20T00:00:00Z",
        "allow": {"channels": None, "isEnabled": True},
        "timeBasedDrops": [{
            "id": "d", "name": " Week 1 ", "startAt": "2026-10-01T00:00:00Z",
            "endAt": "2026-10-20T00:00:00Z", "requiredMinutesWatched": 60, "preconditionDrops": None,
            "benefitEdges": [{"benefit": {"id": "b1", "name": "Corvidicus Malificus ",
                                          "distributionType": "DIRECT_ENTITLEMENT",
                                          "imageAssetURL": "i"}}],
        }],
    }
    c = to_campaign(raw, {})
    assert c.name == "DbD: October of Horror"
    assert c.drops[0].name == "Week 1"
    assert c.drops[0].rewards[0].name == "Corvidicus Malificus"
    assert c.game.name == "Dead by Daylight "
