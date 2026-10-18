"""Inventory (2026-10-18): every listed campaign by game, with each reward's state."""
from dataclasses import replace
from datetime import timedelta

from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan
from test_upcoming_and_known_games import PrefStore, later

from dropwatch.api.views import inventory_view
from dropwatch.models import Prefs
from dropwatch.runner import Runner


async def test_inventory_groups_by_game_with_status_priority_first():
    store = PrefStore(Prefs(priority=("WARDOGS",)))
    done = replace(camp(claimed=True), id="c2", name="Old Frights")
    camps = [camp(), done, later("w", "WARDOGS", 9)]
    r = Runner(FakeClient(camps, [chan("a", 7)]), FakeWatcher(), FakePubSub(), store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    claims = [{"at": NOW - timedelta(days=40), "campaign_id": "gone", "campaign": "S1", "game": "WARDOGS",
               "rewards": [{"name": "Dog tag", "image_url": ""}], "box_art_url": ""}]
    inv = inventory_view(r, store, NOW, claims)
    assert [g.game for g in inv.games] == ["WARDOGS", "Palia"]
    wardogs, palia = inv.games
    assert wardogs.priority == 1 and wardogs.campaigns[0].status == "upcoming"
    assert [cl.campaign for cl in wardogs.claimed_earlier] == ["S1"]
    assert [(c.id, c.status) for c in palia.campaigns] == [("c1", "mining"), ("c2", "done")]
    assert inv.total_rewards == 3 and inv.claimed_rewards == 1


def test_inventory_signed_out_is_empty():
    inv = inventory_view(None, PrefStore(Prefs()), NOW, [])
    assert inv.games == [] and inv.total_rewards == 0


def test_will_mine_follows_the_miners_rules():
    from dropwatch.api.views import will_mine
    from dropwatch.models import Reward
    c = camp()
    badge = replace(c, drops=(replace(c.drops[0], rewards=(Reward("b", "Badge", "", "BADGE"),)),))
    assert will_mine(c, Prefs(), "active")
    assert not will_mine(c, Prefs(never=frozenset({"Palia"})), "active")
    assert not will_mine(c, Prefs(priority_only=True), "active")
    assert will_mine(c, Prefs(priority=("palia",), priority_only=True), "needs_link")
    assert not will_mine(badge, Prefs(), "active") and will_mine(badge, Prefs(mine_badges=True), "active")
    assert not will_mine(c, Prefs(), "done")


def test_sub_drops_are_never_earnable_and_reported():
    from dropwatch.models import drop_earnable_now
    from dropwatch.twitch.parse import _drop
    raw = {"id": "d", "name": "FrekiFriend",
           "startAt": "2026-10-01T00:00:00Z", "endAt": "2026-10-30T00:00:00Z",
           "requiredMinutesWatched": 60, "requiredSubs": 1,
           "benefitEdges": [{"benefit": {"id": "b", "name": "FrekiFriend", "distributionType": "BADGE"}}]}
    d = _drop(raw, {})
    assert d.required_subs == 1
    c = replace(camp(), drops=(d,))
    assert not drop_earnable_now(c, d, NOW)
