"""Regression tests for the phase-2b final review: C1, I1, M1 (re-graded), M2 (re-graded)."""
import json
from dataclasses import replace

from test_link_probe import NoProgressClient, ticks, unknown
from test_review_fixes import G1, G2, NOW, live, mk
from test_runner import FakePubSub, FakeStore, FakeWatcher, chan

from dropwatch.models import Game, Prefs
from dropwatch.planner import plan
from dropwatch.runner import LINK_PROBE_TICKS, Runner
from dropwatch.twitch.catalog import flatten

G3 = Game(3, "Other", "other")


# C1: known-linked campaigns are mined before campaigns whose link is unknown
def test_known_linked_beats_more_urgent_unknown():
    known = mk("known", G1, need=60, end_h=48)             # linked=True, lots of spare time
    new = replace(mk("new", G2, need=600, end_h=12), linked=None)  # far more urgent, link unknown
    p = plan([known, new], [live("x", G1), live("y", G2)], Prefs(), NOW)
    assert p.current.campaign_id == "known"
    assert p.queue == ("new",)


def test_unknown_with_a_linked_campaign_of_the_same_game_ranks_as_known():
    sibling = mk("sib", G2, need=60, end_h=48)              # linked, game G2
    new_same_game = replace(mk("new", G2, need=600, end_h=12), linked=None)
    known_other = mk("k", G1, need=60, end_h=40)
    p = plan([sibling, new_same_game, known_other], [live("x", G1), live("y", G2)], Prefs(), NOW)
    assert p.current.campaign_id == "new"                   # most urgent among probably-linked


def test_unknown_mined_when_nothing_known_is_live():
    known = mk("known", G1)
    new = replace(mk("new", G3), linked=None)
    p = plan([known, new], [live("z", G3)], Prefs(), NOW)
    assert p.current.campaign_id == "new"


def test_hysteresis_does_not_keep_an_unknown_over_a_known():
    known = mk("known", G1, need=60, end_h=48)
    new = replace(mk("new", G2, need=600, end_h=12), linked=None)
    p = plan([known, new], [live("x", G1), live("y", G2)], Prefs(), NOW, current_campaign="new")
    assert p.current.campaign_id == "known"


def test_priority_still_wins_over_link_rank():
    known = mk("known", G1)
    new = replace(mk("new", G2), linked=None)
    p = plan([known, new], [live("x", G1), live("y", G2)], Prefs(priority=("Phasmophobia",)), NOW)
    assert p.current.campaign_id == "new"


# I1: "Mine now" after linking clears the mark so the campaign can be tried again
def make_runner():
    clock = [NOW]
    r = Runner(NoProgressClient([unknown()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), FakeStore(),
               user_id=42, clock=lambda: clock[0])
    return r, clock


async def test_mine_now_clears_maybe_unlinked():
    r, clock = make_runner()
    await r.refresh()
    await ticks(r, clock, LINK_PROBE_TICKS)
    assert "c1" in r.maybe_unlinked and r.plan.current is None
    r.mine_now("c1")
    await r.refresh()
    assert "c1" not in r.maybe_unlinked and r.plan.current.campaign_id == "c1"


# M1 (re-graded Important: a stale counter wrongly sends a campaign to Needs you)
async def test_probe_counter_dropped_when_campaign_stops_being_current():
    r, clock = make_runner()
    await r.refresh()
    await ticks(r, clock, LINK_PROBE_TICKS - 5)
    r._client.live = []                        # channel gone: nothing is current
    await r.refresh()
    assert r._link_probe == {}
    r._client.live = [chan("a", 7)]
    await r.refresh()
    await ticks(r, clock, 10)                  # well under 10 minutes since it came back
    assert "c1" not in r.maybe_unlinked


# M2 (re-graded Important: one odd record must not hide the whole catalogue)
def test_record_with_null_end_is_skipped_not_fatal():
    game = {"id": "1", "displayName": "P"}
    good = {"id": "a", "status": "ACTIVE", "endAt": "2026-10-20T00:00:00Z", "game": game}
    bad = {"id": "b", "status": "ACTIVE", "endAt": None, "game": game}
    data, _ = flatten(json.loads(json.dumps({"data": [{"rewards": [good, bad]}]})))
    assert set(data) == {"a"}
