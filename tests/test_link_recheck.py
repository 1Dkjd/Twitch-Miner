"""Earning minutes doesn't prove an account link (found live 2026-10-10: ER ESPORTS DROPS counted an hour of
watch time, then Twitch's inventory said isAccountConnected false and the reward was never given). When an
unknown-link campaign starts earning, re-read Twitch's campaigns at once (and every 10 min while still
unknown) instead of waiting for the hourly fetch."""
from dataclasses import replace
from datetime import timedelta

from test_link_probe import NoProgressClient, ticks
from test_runner import NOW, FakePubSub, FakeStore, FakeWatcher, camp, chan

from dropwatch.runner import LINK_RECHECK, Runner
from dropwatch.twitch.pubsub import DropProgress


class CountingClient(NoProgressClient):
    def __init__(self, campaigns, live):
        super().__init__(campaigns, live)
        self.fetches = 0

    async def campaigns(self):
        self.fetches += 1
        return await super().campaigns()


def make():
    clock = [NOW]
    client = CountingClient([replace(camp(), linked=None)], [chan("a", 7)])
    r = Runner(client, FakeWatcher(), FakePubSub(), FakeStore(), user_id=42, clock=lambda: clock[0])
    return r, client, clock


async def test_first_minutes_on_an_unknown_link_trigger_a_recheck_that_moves_on_if_unlinked():
    r, client, clock = make()
    await r.refresh()
    assert r.plan.current.campaign_id == "c1" and client.fetches == 1
    await ticks(r, clock, 1)  # playback starts; nothing earned yet
    client.camps = [replace(camp(cur=1), linked=False)]  # Twitch's inventory now lists it: not linked
    await r.handle(DropProgress("d1", 1, 60))
    await ticks(r, clock, 1)
    assert client.fetches == 2  # re-read straight away, not at the hourly fetch
    assert r.plan.current is None and "c1" in r.plan.needs_you


async def test_still_unknown_rechecks_every_10_minutes_not_every_tick():
    r, client, clock = make()
    await r.refresh()
    for i in range(1, 6 * 22):  # a minute earned per minute (6 ticks) for 22 min, under the 60 needed
        if i % 6 == 0:
            await r.handle(DropProgress("d1", i // 6, 60))
        await ticks(r, clock, 1)
    # re-read at the first earning minute (1:00), then 11:00 and 21:00; the 5-minute refreshes don't refetch
    assert client.fetches == 1 + 3
    assert LINK_RECHECK == timedelta(minutes=10)


async def test_a_known_linked_campaign_is_not_rechecked():
    r, client, clock = make()
    client.camps = [camp()]  # linked
    await r.refresh(force_campaigns=True)
    before = client.fetches
    await r.handle(DropProgress("d1", 1, 60))
    await ticks(r, clock, 1)
    assert client.fetches == before
