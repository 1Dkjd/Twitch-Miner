"""Up next marks campaigns Dropwatch first saw in the last 24 hours (instead of "coming soon", which no
data source offers the TV sign-in: approved 2026-10-10, docs/design/pre-docker-mockup.html)."""
from dataclasses import replace
from datetime import timedelta

from apihelpers import NOW
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.api.views import state_view
from dropwatch.runner import Runner
from dropwatch.store import Store


async def setup(tmp_path, first):
    store = Store(tmp_path / "d.db")
    t = [NOW]
    client = FakeClient(first, [chan("a", 7)])
    r = Runner(client, FakeWatcher(), FakePubSub(), store, user_id=42, clock=lambda: t[0])
    await r.refresh()
    return store, t, client, r


def newness(view):
    out = {c.id: c.new for c in view.up_next}
    if view.current:
        out[view.current.campaign.id] = view.current.campaign.new
    return out


async def test_campaigns_seen_after_the_first_look_are_new_for_a_day(tmp_path):
    c1 = camp()
    c2 = replace(c1, id="c2", name="Later")
    store, t, client, r = await setup(tmp_path, [c1])
    t[0] = NOW + timedelta(hours=2)
    client.camps = [c1, c2]
    await r.refresh()
    assert newness(state_view(r, store, NOW + timedelta(hours=3))) == {"c1": False, "c2": True}
    assert newness(state_view(r, store, NOW + timedelta(hours=26, minutes=1))) == {"c1": False, "c2": False}


async def test_nothing_is_new_on_the_very_first_look(tmp_path):
    # a fresh install sees every running campaign at once; marking all of them new would mean nothing
    c1 = camp()
    store, t, client, r = await setup(tmp_path, [c1, replace(c1, id="c2", name="Later")])
    assert newness(state_view(r, store, NOW + timedelta(minutes=5))) == {"c1": False, "c2": False}
