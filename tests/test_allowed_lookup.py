"""Channel-restricted campaigns: look allowed channels up by name only when the game's directory found none
of them (2026-10-10: 2,430 names in 122 requests took 24 s; looking up only the 13 campaigns the directory
missed took 3.5 s and left the same 65 campaigns minable)."""
from datetime import UTC, datetime

from test_planner import PALIA, PHAS, SPECIAL, mk

from dropwatch.models import Prefs
from dropwatch.twitch.client import TwitchClient

NOW = datetime(2026, 10, 10, 22, tzinfo=UTC)


def directory(*streams):
    return {"data": {"game": {"streams": {"edges": [
        {"node": {"id": f"s-{lg}", "viewersCount": v,
                  "broadcaster": {"id": str(abs(hash(lg)) % 10_000), "login": lg}}}
        for lg, v in streams]}}}}


class FakeGql:
    def __init__(self, dirs, live_by_name=()):
        self.dirs, self.live_by_name, self.by_name, self.directories = dirs, set(live_by_name), [], []

    async def run_many(self, payloads):
        out = []
        for p in payloads:
            v = p["variables"]
            if p["operationName"] == "DirectoryPage_Game":
                self.directories.append(v["slug"])
                out.append(self.dirs.get(v["slug"], directory()))
            else:  # GetStreamInfo
                self.by_name.append(v["channel"])
                lg = v["channel"]
                user = {"id": "9", "login": lg, "stream": {"id": f"s-{lg}", "viewersCount": 5},
                        "broadcastSettings": {"game": {"id": str(PHAS.id), "name": "x"}}}
                out.append({"data": {"user": user if lg in self.live_by_name else None}})
        return out

    async def run(self, payload):
        (r,) = await self.run_many([payload])
        return r


async def test_allowed_channels_are_looked_up_only_for_campaigns_the_directory_missed():
    found = mk(NOW, "found", PALIA, allowed=("a", "b", "c"))  # "a" streams Palia: b and c not asked
    missed = mk(NOW, "missed", PHAS, allowed=("x", "y"))  # only "z" (not allowed) listed: ask by name
    g = FakeGql({PALIA.slug: directory(("a", 50)), PHAS.slug: directory(("z", 900))}, live_by_name={"y"})
    live = await TwitchClient(g, 42).live_channels([found, missed], Prefs(favourites=("fav",)), NOW)
    assert sorted(g.by_name) == ["fav", "x", "y"]
    assert {ch.login for ch in live} == {"a", "z", "y"}
    assert set(g.directories) == {PALIA.slug, PHAS.slug}  # restricted-only games get a directory look too


async def test_special_event_campaigns_always_ask_by_name():
    # their allowed channels may stream any game, so no single directory lists them
    special = mk(NOW, "special", SPECIAL, allowed=("s1", "s2"))
    g = FakeGql({SPECIAL.slug: directory(("s1", 10))})
    await TwitchClient(g, 42).live_channels([special], Prefs(), NOW)
    assert sorted(g.by_name) == ["s2"]  # s1 already seen in a directory; s2 still asked
