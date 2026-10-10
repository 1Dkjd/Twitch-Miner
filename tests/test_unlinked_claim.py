"""No claims for a campaign Twitch says isn't linked (found live 2026-10-10).

ER ESPORTS DROPS (isAccountConnected false) had a claim id; Twitch answered every claim with
ELIGIBLE_FOR_ALL but never awarded the reward, so History grew one false row per restart.
"""
from dataclasses import replace
from datetime import timedelta

from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.models import Reward
from dropwatch.runner import Runner
from dropwatch.store import Store
from dropwatch.twitch.pubsub import DropClaimable


def unlinked(**kw):
    return replace(camp(**kw), linked=False)


def make(tmp_path, campaigns):
    st = Store(tmp_path / "d.db")
    emitted = []
    r = Runner(FakeClient(campaigns, [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW, emit=lambda k, d: emitted.append(k))
    return r, st, emitted


async def test_unlinked_campaign_is_not_claimed_or_recorded(tmp_path):
    r, st, emitted = make(tmp_path, [unlinked(cur=60, claim_id="inst")])
    await r.refresh()
    await r.handle(DropClaimable("d1", "inst"))
    assert r._client.claims == []
    assert st.claims_since(NOW - timedelta(days=30)) == []
    assert "claimed" not in emitted


async def test_claimed_once_the_account_is_linked(tmp_path):
    r, st, _ = make(tmp_path, [unlinked(cur=60, claim_id="inst")])
    await r.refresh()
    r._client.camps = [camp(cur=60, claim_id="inst")]  # Nick linked it: Twitch now says linked
    await r.refresh(force_campaigns=True)
    assert r._client.claims == ["inst"]
    assert len(st.claims_since(NOW - timedelta(days=30))) == 1


async def test_unlinked_badge_campaign_is_still_claimed(tmp_path):
    c = unlinked(cur=60, claim_id="inst")
    d = replace(c.drops[0], rewards=(Reward("r", "Pal badge", "", "BADGE"),))
    r, _, _ = make(tmp_path, [replace(c, drops=(d,))])
    await r.refresh()
    assert r._client.claims == ["inst"]
