"""Phase 2b Task 2: an account link can be unknown (catalogue campaigns) and that counts as minable."""
from dataclasses import replace
from datetime import timedelta

from test_review_fixes import G1, NOW, live, mk

from dropwatch.api.views import campaign_out
from dropwatch.models import Prefs, account_eligible
from dropwatch.planner import plan
from dropwatch.twitch import parse

RAW = {
    "id": "c9", "name": "Catalogue camp", "accountLinkURL": "https://link.example",
    "game": {"id": "1", "displayName": "Palia", "slug": "palia"},
    "startAt": "2026-10-01T00:00:00Z", "endAt": "2026-10-20T00:00:00Z", "allow": {"isEnabled": False},
    "timeBasedDrops": [{"id": "d9", "name": "d", "requiredMinutesWatched": 60,
                        "startAt": "2026-10-01T00:00:00Z", "endAt": "2026-10-20T00:00:00Z",
                        "benefitEdges": [{"benefit": {"id": "b", "name": "Hat", "imageAssetURL": "",
                                                      "distributionType": "DIRECT_ENTITLEMENT"}}]}],
}


def test_to_campaign_without_self_is_unknown():
    assert parse.to_campaign(RAW, {}).linked is None


def test_to_campaign_with_self_is_known():
    assert parse.to_campaign({**RAW, "self": {"isAccountConnected": False}}, {}).linked is False
    assert parse.to_campaign({**RAW, "self": {"isAccountConnected": True}}, {}).linked is True


def test_unknown_link_is_account_eligible():
    c = replace(mk("u", G1), linked=None)
    assert account_eligible(c, Prefs())


def test_planner_mines_unknown_link():
    c = replace(mk("u", G1), linked=None)
    p = plan([c], [live("x", G1)], Prefs(), NOW)
    assert p.current is not None and p.current.campaign_id == "u"
    assert "u" not in p.needs_you


def test_planner_needs_you_only_for_false():
    unlinked = replace(mk("f", G1), linked=False)
    unknown = replace(mk("u", G1, end_h=20), linked=None)
    p = plan([unlinked, unknown], [], Prefs(), NOW)
    assert p.needs_you == ("f",)


def test_campaign_out_reports_unknown():
    c = replace(mk("u", G1), linked=None)
    out = campaign_out(c, NOW + timedelta(minutes=1), None)
    assert out.linked is None and out.maybe_unlinked is False
