"""History → Missed (approved in docs/design/next-features-mockup.html, 2026-10-10): campaigns that ended
with rewards left, and why. Dropwatch records what it knows about each campaign as it goes, since a
campaign disappears from Twitch's lists once it ends."""
from dataclasses import replace
from datetime import timedelta

from apihelpers import NOW, logged_in, make_app
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.models import Game, Reward
from dropwatch.runner import Runner
from dropwatch.store import Store

ER = Game(9, "Eternal Return", "er")
RISE = Game(8, "Rise Online", "rise")
ANY_LIVE = (chan("a", 7),)  # streams Palia, the fixtures' default game


def c(cid, name, game=None, *, need=60, cur=0, end_h=4, linked=True, claimed=False):
    base = camp(cur=cur, claimed=claimed)
    ends = NOW + timedelta(hours=end_h)
    reward = Reward("r", f"{name} reward", f"img/{cid}", "DIRECT_ENTITLEMENT")
    d = replace(base.drops[0], id=f"{cid}-d", required_minutes=need, current_minutes=cur, ends_at=ends,
                rewards=(reward,))
    return replace(base, id=cid, name=name, game=game or base.game, ends_at=ends, linked=linked,
                   link_url=f"https://link/{cid}", drops=(d,))


async def seen(st, campaigns, at, live=ANY_LIVE):
    r = Runner(FakeClient(campaigns, list(live)), FakeWatcher(), FakePubSub(), st, user_id=42,
               clock=lambda: at)
    await r.refresh()


def missed(st, until):
    return {m["campaign_id"]: m for m in st.missed_between(NOW - timedelta(days=1), until)}


async def test_ended_campaigns_with_rewards_left_are_missed_with_a_reason(tmp_path):
    st = Store(tmp_path / "d.db")
    st.set_lists(["Palia"], {"Rise Online"}, [])
    camps = [
        c("er", "ER ESPORTS DROPS", ER, cur=60, need=60, linked=False),  # earned, but not linked
        c("late", "October Drops", need=300, end_h=2),  # listed with too little time left
        c("done", "All claimed", claimed=True, cur=60),  # nothing left: not missed
        c("skip", "Mobile Drop 183", RISE),  # in Never
        c("outranked", "Dragonfire", need=60, cur=10),  # started, then outranked
        c("never-started", "Never touched", need=60),  # never started
    ]
    await seen(st, camps, NOW)
    await seen(st, camps, NOW + timedelta(hours=1, minutes=55))  # 5 min before "late" ends
    await seen(st, camps, NOW + timedelta(hours=3, minutes=55))  # 5 min before the rest end
    rows = missed(st, NOW + timedelta(hours=5))
    assert set(rows) == {"er", "late", "skip", "outranked", "never-started"}
    assert rows["er"]["reason"] == "not_linked" and rows["er"]["minutes_watched"] == 60
    assert rows["late"]["reason"] == "ran_out_of_time"
    assert rows["skip"]["reason"] == "never_list"
    assert rows["outranked"]["reason"] == "outranked"
    assert rows["never-started"]["reason"] == "outranked" and rows["never-started"]["started"] is False
    assert rows["outranked"]["started"] is True and rows["outranked"]["priority"] is True  # Palia
    assert (rows["outranked"]["rewards_total"], rows["outranked"]["rewards_claimed"]) == (1, 0)
    assert rows["outranked"]["rewards"][0]["image_url"] == "img/outranked"


async def test_no_live_channels_and_dropwatch_off(tmp_path):
    offline = c("offline", "Nobody streams it", need=5, end_h=3)
    st = Store(tmp_path / "d.db")
    await seen(st, [offline], NOW, live=())  # the last look was 3 h before it ended
    assert missed(st, NOW + timedelta(hours=4))["offline"]["reason"] == "dropwatch_off"
    st2 = Store(tmp_path / "e.db")
    await seen(st2, [offline], NOW + timedelta(hours=2, minutes=50), live=())  # 10 min before
    assert missed(st2, NOW + timedelta(hours=4))["offline"]["reason"] == "no_live_channels"


async def test_history_api_lists_missed_in_the_period(tmp_path):
    app, ctx = make_app(tmp_path)
    er = c("er", "ER ESPORTS DROPS", ER, cur=60, linked=False, end_h=-0.1)
    await seen(ctx.store, [er], NOW - timedelta(hours=1))
    cl = await logged_in(app)
    (m,) = (await cl.get("/api/history")).json()["missed"]
    assert m["name"] == "ER ESPORTS DROPS" and m["reason"] == "not_linked" and m["link_url"]
    assert (await cl.get("/api/history?days=1")).json()["missed"]  # ended within the day
    await cl.aclose()
