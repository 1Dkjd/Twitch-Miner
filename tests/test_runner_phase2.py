from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.runner import Runner


class RecStore:
    def __init__(self):
        self.events, self.claims = [], []

    def get_prefs(self):
        from dropwatch.models import Prefs
        return Prefs()

    def log_event(self, kind, data):
        self.events.append((kind, data))

    def add_claim(self, at, campaign_id, campaign, game, rewards, **detail):
        self.claims.append((campaign_id, campaign, game, rewards))


def make(client, store=None, emitted=None):
    emitted = [] if emitted is None else emitted
    return Runner(client, FakeWatcher(), FakePubSub(), store or RecStore(), user_id=42,
                  clock=lambda: NOW, emit=lambda k, d: emitted.append((k, d))), emitted


async def test_claim_is_recorded_for_history():
    st = RecStore()
    r, _ = make(FakeClient([camp(cur=60, claim_id="inst")], [chan("a", 7)]), st)
    await r.refresh()
    assert st.claims == [("c1", "Frights", "Palia", [("Palcat Glasses", "")])]


async def test_refreshed_event_after_successful_refresh():
    r, emitted = make(FakeClient([camp()], [chan("a", 7)]))
    await r.refresh()
    assert any(k == "refreshed" for k, _ in emitted)


async def test_stale_campaign_override_is_cleared():
    r, _ = make(FakeClient([camp()], [chan("a", 7)]))
    r.mine_now("gone-campaign")
    await r.refresh()
    assert r._override_campaign is None


async def test_honoured_override_is_kept():
    r, _ = make(FakeClient([camp()], [chan("a", 7), chan("b", 8)]))
    r.use_channel("b")
    await r.refresh()
    assert r.watching.login == "b" and r._override_channel == "b"
