"""History details (Nick approved docs/design/history-detail-mockup.html, 2026-10-10): each claim keeps the
watch time its drop needed, the channel it was mined on, and the campaign's size and end."""
import sqlite3
from datetime import timedelta

from apihelpers import NOW, logged_in, make_app
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.runner import Runner
from dropwatch.store import Store


def test_store_keeps_claim_details(tmp_path):
    st = Store(tmp_path / "d.db")
    st.add_claim(NOW, "c1", "Frights", "Palia", [("Glasses", "g")], minutes=120, channel="alpha",
                 campaign_rewards=10, campaign_ends=NOW + timedelta(days=1))
    st.add_claim(NOW - timedelta(hours=1), "c1", "Frights", "Palia", [("Hat", "h")])  # details unknown
    new, old = st.claims_since(NOW - timedelta(days=1))
    assert (new["minutes"], new["channel"], new["campaign_rewards"]) == (120, "alpha", 10)
    assert new["campaign_ends"] == NOW + timedelta(days=1)
    assert (old["minutes"], old["channel"], old["campaign_rewards"], old["campaign_ends"]) == (None,) * 4


def test_an_existing_database_gains_the_new_columns(tmp_path):
    p = tmp_path / "d.db"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE claims (at TEXT NOT NULL, campaign_id TEXT NOT NULL, campaign TEXT NOT NULL,"
               " game TEXT NOT NULL, rewards TEXT NOT NULL)")
    db.execute("INSERT INTO claims VALUES (?, 'c1', 'Frights', 'Palia', '[]')", (NOW.isoformat(),))
    db.commit()
    db.close()
    st = Store(p)
    assert st.claims_since(NOW - timedelta(days=1))[0]["channel"] is None  # old row kept, reads as unknown
    st.add_claim(NOW, "c2", "X", "Y", [], channel="beta")
    assert {r["channel"] for r in st.claims_since(NOW - timedelta(days=1))} == {None, "beta"}
    Store(p)  # opening again must not try to add the columns twice


async def test_runner_saves_watch_time_channel_and_campaign_size(tmp_path):
    st = Store(tmp_path / "d.db")
    r = Runner(FakeClient([camp(cur=30)], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st,
               user_id=42, clock=lambda: NOW)
    await r.refresh()  # mining the campaign on "a"
    assert st.claims_since(NOW - timedelta(days=1)) == []
    r._client.camps = [camp(cur=60, claim_id="inst")]  # the drop finished; Twitch issued a claim id
    await r.refresh(force_campaigns=True)
    (row,) = st.claims_since(NOW - timedelta(days=1))
    assert row["minutes"] == 60 and row["campaign_rewards"] == 1
    assert row["campaign_ends"] == NOW + timedelta(days=4)
    assert row["channel"] == "a"


async def test_history_api_returns_the_details(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.store.add_claim(NOW, "c1", "Frights", "Palia", [("Glasses", "g")], minutes=60, channel="alpha",
                        campaign_rewards=3, campaign_ends=NOW + timedelta(days=2))
    c = await logged_in(app)
    (claim,) = (await c.get("/api/history")).json()["claims"]
    assert claim["minutes"] == 60 and claim["channel"] == "alpha" and claim["campaign_rewards"] == 3
    assert claim["campaign_ends"].startswith((NOW + timedelta(days=2)).date().isoformat())
    await c.aclose()


async def test_box_art_is_saved_with_the_claim(tmp_path):
    """History keeps a game's art after its campaigns end or before the miner has loaded any (2026-10-10)."""
    from dataclasses import replace

    from dropwatch.models import Game

    st = Store(tmp_path / "d.db")
    art = "https://static-cdn.jtvnw.net/ttv-boxart/1-{width}x{height}.jpg"
    c0 = replace(camp(cur=60, claim_id="inst"), game=Game(1, "Palia", "palia", art))
    r = Runner(FakeClient([c0], [chan("a", 7)]), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: NOW)
    await r.refresh()
    (row,) = st.claims_since(NOW - timedelta(days=1))
    assert row["box_art_url"] == art
    app, ctx = make_app(tmp_path / "api")
    ctx.store.add_claim(NOW, "c1", "Frights", "Palia", [], box_art_url="https://x/palia-{width}x{height}.jpg")
    c = await logged_in(app)
    got = (await c.get("/api/history")).json()["claims"][0]["box_art_url"]
    assert got == "https://x/palia-{width}x{height}.jpg"
    await c.aclose()
