from datetime import timedelta

from test_runner import NOW, FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

from dropwatch.api.views import history_view, state_view
from dropwatch.models import Campaign, Drop, Game
from dropwatch.runner import Runner


class ViewStore(FakeStore):
    def __init__(self, signed_in=True):
        super().__init__()
        self.signed_in = signed_in

    def get_session(self):
        from dropwatch.twitch.session import TwitchSession
        return TwitchSession("tok", 42, "kp", "d", "c", "s") if self.signed_in else None


async def test_state_while_signed_out_is_empty_and_valid():
    s = state_view(None, ViewStore(signed_in=False), NOW)
    assert s.state == "signed_out" and s.signed_in is False
    assert s.current is None and s.needs_you == [] and s.up_next == [] and s.done == []


async def test_state_before_first_refresh():
    r = Runner(FakeClient([camp()], []), FakeWatcher(), FakePubSub(), ViewStore(), user_id=42,
               clock=lambda: NOW)
    s = state_view(r, ViewStore(), NOW)
    assert s.state == "idle" and s.current is None and s.login == "kp"


async def test_state_with_current_plan():
    r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), ViewStore(), user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    s = state_view(r, ViewStore(), NOW)
    assert s.state == "mining"
    assert s.current.campaign.name == "Frights" and s.current.channel.login == "a"
    assert s.current.campaign.drops[0].rewards[0].name == "Palcat Glasses"
    assert s.current.campaign.verdict == "plenty"
    assert "access_token" not in s.model_dump_json() and "tok" not in s.model_dump_json()


async def test_drop_without_rewards_does_not_crash():
    g = Game(1, "Palia", "palia")
    d = Drop("d", "d", (), NOW - timedelta(days=1), NOW + timedelta(days=1), 60, 0, False, None)
    c = Campaign("c", "c", g, NOW - timedelta(days=1), NOW + timedelta(days=1), False, "", (), (d,))
    r = Runner(FakeClient([c], []), FakeWatcher(), FakePubSub(), ViewStore(), user_id=42, clock=lambda: NOW)
    await r.refresh()
    state_view(r, ViewStore(), NOW)  # must not raise


def test_history_is_flat_newest_first_with_utc_offsets():
    claims = [
        {"at": NOW, "campaign_id": "c2", "campaign": "Crimson", "game": "Phasmophobia",
         "rewards": [{"name": "T-Shirt", "image_url": "u"}, {"name": "Badge", "image_url": "v"}]},
        {"at": NOW - timedelta(hours=1), "campaign_id": "c1", "campaign": "Frights", "game": "Palia",
         "rewards": [{"name": "Glasses", "image_url": "g"}]},
    ]
    h = history_view(claims)
    assert [c.campaign for c in h.claims] == ["Crimson", "Frights"]
    assert [r.name for r in h.claims[0].rewards] == ["T-Shirt", "Badge"]
    assert h.total_rewards == 3
    # the page localises times itself, so every timestamp must carry its offset
    assert '"at":"2026-10-09T12:00:00Z"' in h.model_dump_json()
