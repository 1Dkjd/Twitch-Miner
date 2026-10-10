"""Phase 2b Task 8: the catalogue is wired into the service and reported in the state."""
from datetime import UTC, datetime

from test_client_catalog import FakeCatalog, FakeGql, inventory
from test_runner import FakePubSub, FakeStore, FakeWatcher

import dropsminer.twitch.transport as transport_mod
from dropsminer.api.views import state_view
from dropsminer.runner import Runner
from dropsminer.service import build_parts
from dropsminer.store import Store
from dropsminer.twitch.constants import SMARTBOX
from dropsminer.twitch.session import TwitchSession

SINCE = datetime(2026, 10, 10, 14, 5, tzinfo=UTC)


class ViewStore(FakeStore):
    def get_session(self):
        return None


def test_state_includes_catalog_status():
    from dropsminer.twitch.client import TwitchClient
    r = Runner(TwitchClient(FakeGql(inventory(), None), 42, catalog=FakeCatalog({}, ("unreachable", SINCE))),
               FakeWatcher(), FakePubSub(), ViewStore(), user_id=42)
    s = state_view(r, ViewStore(), SINCE)
    assert s.catalog.status == "unreachable" and s.catalog.since == SINCE


def test_state_without_catalog_is_none():
    s = state_view(None, ViewStore(), SINCE)
    assert s.catalog is None


async def test_build_parts_gives_client_a_catalog_and_closes_its_transport(tmp_path, monkeypatch):
    made = []

    class T:
        def __init__(self):
            self.closed = False
            made.append(self)

        async def close(self):
            self.closed = True

    monkeypatch.setattr(transport_mod, "AiohttpTransport", T)
    store = Store(tmp_path / "drops.db")
    s = TwitchSession("tok", 42, "kp", "d", SMARTBOX.client_id, "s")
    parts = build_parts(store, s, lambda k, d: None)
    catalog = parts.runner._client.catalog
    assert catalog is not None and catalog._cache == tmp_path / "catalog.json"
    assert len(made) == 2 and catalog._t is not made[0]  # its own transport, never Twitch's
    await parts.close()
    assert all(t.closed for t in made)


async def test_unused_catalog_is_not_reported(tmp_path):
    from dropsminer.twitch.catalog import Catalog
    from dropsminer.twitch.client import TwitchClient
    cat = Catalog(object(), tmp_path / "catalog.json")
    r = Runner(TwitchClient(FakeGql(inventory(), None), 42, catalog=cat), FakeWatcher(), FakePubSub(),
               ViewStore(), user_id=42)
    assert r.catalog_status is None
