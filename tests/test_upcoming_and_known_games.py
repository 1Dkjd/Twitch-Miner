"""Coming up (announced campaigns) and remembered games for Priorities (2026-10-18)."""
from dataclasses import replace
from datetime import timedelta

from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan
from test_views import ViewStore

from dropwatch.api.views import state_view
from dropwatch.models import Game, Prefs
from dropwatch.runner import Runner
from dropwatch.store import Store


def later(cid, game, days):
    c = camp()
    return replace(c, id=cid, name=f"{game} S2", game=Game(int(days) + 10, game, game.lower()),
                   starts_at=NOW + timedelta(days=days), ends_at=NOW + timedelta(days=days + 14), linked=None)


class PrefStore(ViewStore):
    def __init__(self, prefs):
        super().__init__()
        self.prefs = prefs

    def get_prefs(self):
        return self.prefs


async def test_upcoming_lists_announced_campaigns_priority_first_and_never_skipped():
    store = PrefStore(Prefs(priority=("WARDOGS",), never=frozenset({"Rust"})))
    camps = [camp(), later("w", "WARDOGS", 9), later("a", "Apex Legends", 2), later("r", "Rust", 1)]
    r = Runner(FakeClient(camps, [chan("a", 7)]), FakeWatcher(), FakePubSub(), store, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    s = state_view(r, store, NOW)
    assert [c.id for c in s.upcoming] == ["w", "a"]
    assert s.upcoming[0].priority is True and s.upcoming[1].priority is False
    assert s.upcoming[0].starts_at == NOW + timedelta(days=9)
    assert s.current.campaign.id == "c1"  # an announced campaign is never mined early


def test_known_games_remember_art_and_latest_end(tmp_path):
    st = Store(tmp_path / "d.db")
    st.record_games(NOW, [("WARDOGS", "https://static-cdn.jtvnw.net/w.jpg", NOW + timedelta(days=3))])
    st.record_games(NOW + timedelta(days=1), [("WARDOGS", "", NOW + timedelta(days=1))])
    (g,) = st.known_games()
    assert g["game"] == "WARDOGS"
    assert g["box_art_url"] == "https://static-cdn.jtvnw.net/w.jpg"  # kept when Twitch sends none
    assert g["last_ends_at"] == (NOW + timedelta(days=3)).isoformat()  # never moves back


async def test_runner_records_every_listed_game_including_upcoming(tmp_path):
    st = Store(tmp_path / "d.db")
    r = Runner(FakeClient([camp(), later("w", "WARDOGS", 9)], []), FakeWatcher(), FakePubSub(), st,
               user_id=42, clock=lambda: NOW)
    await r.refresh()
    assert {g["game"] for g in st.known_games()} == {"Palia", "WARDOGS"}
