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
