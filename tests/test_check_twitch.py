"""How often campaigns are re-read from Twitch is a setting (campaigns_every_minutes, default 60), and the
top bar's "Check Twitch" button re-reads them now (POST /api/refresh). Asked for 2026-10-10."""
from datetime import timedelta

from apihelpers import NOW, logged_in, make_app
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

from dropwatch.runner import Runner
from dropwatch.store import Store


class CountingClient(FakeClient):
    def __init__(self, *a):
        super().__init__(*a)
        self.campaign_reads = 0

    async def campaigns(self):
        self.campaign_reads += 1
        return await super().campaigns()


async def reads_after(tmp_path, minutes, setting=None):
    st = Store(tmp_path / "d.db")
    if setting is not None:
        st.put_settings({"campaigns_every_minutes": setting})
    c = CountingClient([camp()], [chan("a", 7)])
    t = [NOW]
    r = Runner(c, FakeWatcher(), FakePubSub(), st, user_id=42, clock=lambda: t[0])
    await r.refresh()
    t[0] = NOW + timedelta(minutes=minutes)
    await r.refresh()
    return c.campaign_reads


def test_default_is_an_hour(tmp_path):
    assert Store(tmp_path / "d.db").get_settings()["campaigns_every_minutes"] == 60


async def test_default_rereads_after_an_hour_not_before(tmp_path):
    assert await reads_after(tmp_path / "a", 55) == 1
    assert await reads_after(tmp_path / "b", 60) == 2


async def test_a_shorter_setting_rereads_sooner(tmp_path):
    assert await reads_after(tmp_path / "a", 15, setting=15) == 2
    assert await reads_after(tmp_path / "b", 14, setting=15) == 1


async def test_a_longer_setting_waits_longer(tmp_path):
    assert await reads_after(tmp_path / "a", 90, setting=120) == 1


async def test_settings_api_takes_only_the_offered_intervals(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    for ok in (15, 30, 60, 120, 240):
        r = await c.put("/api/settings", json={"campaigns_every_minutes": ok})
        assert r.status_code == 200 and r.json()["campaigns_every_minutes"] == ok
    for bad in (0, 5, 14, 45, 241, "60", True):
        assert (await c.put("/api/settings", json={"campaigns_every_minutes": bad})).status_code == 422, bad
    await c.aclose()


def checked(st):
    return [d for k, _, d in st.recent_events(100) if k == "checked"]


async def test_check_ins_are_logged_for_activity_clicked_or_automatic(tmp_path):
    from dataclasses import replace
    st = Store(tmp_path / "d.db")
    unlinked = replace(camp(), linked=False)
    c = CountingClient([unlinked], [chan("a", 7)])
    t = [NOW]
    r = Runner(c, FakeWatcher(), FakePubSub(), st, user_id=42, clock=lambda: t[0])
    await r.refresh()  # the first look: automatic
    (first,) = checked(st)
    assert first["manual"] is False and first["campaigns"] == 1
    t[0] = NOW + timedelta(minutes=5)
    await r.refresh()  # a 5-minute live-channel check: campaigns not re-read, nothing logged
    assert len(checked(st)) == 1
    c.camps = [camp(), replace(camp(), id="c2", name="Later")]  # linked now, and one new campaign
    await r.refresh(force_campaigns=True, manual=True)  # the Check Twitch button
    last = checked(st)[0]
    assert last["manual"] is True and last["campaigns"] == 2 and last["new"] == 1
    assert last["linked"] == ["Palia"]
    assert isinstance(last["seconds"], (int, float))


async def test_the_button_is_logged_as_clicked(tmp_path):
    app, ctx = make_app(tmp_path, runner=None)
    from apihelpers import runner_with_plan
    ctx.service.runner = await runner_with_plan(ctx.store)
    c = await logged_in(app)
    assert (await c.post("/api/refresh")).status_code == 204
    assert checked(ctx.store)[0]["manual"] is True
    acts = (await c.get("/api/activity")).json()["events"]
    assert acts[0]["kind"] == "checked" and acts[0]["data"]["manual"] is True
    await c.aclose()


async def test_activity_carries_a_fractional_check_time(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.store.log_event("checked", {"manual": True, "campaigns": 143, "new": 0, "linked": [], "seconds": 1.3})
    c = await logged_in(app)
    r = await c.get("/api/activity")
    assert r.status_code == 200 and r.json()["events"][0]["data"]["seconds"] == 1.3
    await c.aclose()
