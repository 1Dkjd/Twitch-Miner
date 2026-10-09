# Drops Miner Phase 1 (Headless Miner) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command-line Drops Miner that:
- signs in to Twitch through a browser;
- finds drop campaigns;
- decides what to mine;
- sends the minute-watched heartbeat;
- claims rewards;
- has been proven on Nick's account.

**Architecture:**
- Python 3.12, asyncio.
- Twitch I/O sits behind small classes: `Gql`, `TwitchClient`, `Watcher`, `PubSub`, `BrowserSignIn`. Each takes an injected transport, so tests never touch the network.
- A pure `planner.plan()` decides everything from data plus `now`.
- `Runner` orchestrates and emits events.
- `Store` is SQLite.
- Phase 1 has no API or UI; `cli.py` drives it.

**Tech Stack:** Python 3.12, uv, aiohttp, zendriver, pytest, pytest-asyncio, ruff.

**Spec:** `docs/superpowers/specs/2026-10-09-drops-miner-design.md` (approved 2026-10-09; threshold erratum `6cc4886`).

**Scope of this plan:** spec section 14, phase 1 only. Phases 2–5 each get their own plan after the previous phase passes its gate:
- Phase 2's API shapes come from Phase 1's real models.
- Phase 3 needs a mockup round first.

**Declared deviations from the spec** (Nick to confirm when reviewing):
1. **Live acceptance runs on Nick's Windows PC via the CLI**, not on Unraid. Spec §13 says "Live acceptance on Unraid, phase 1 and phase 5", but there is no container until phase 5. It is the same code. Phase 5 repeats the run on Unraid.
2. **PubSub uses one websocket**, subscribed only to the user topics plus the watched channel's two stream topics (≤5 topics). Spec §3 describes the reference's 8×50 pool. Other channels' online status comes from a GQL refresh every 5 minutes. That's simpler, and a pool can be added later if switching proves slow.
3. **Badge/emote campaigns follow the reference's default** (`enable_badges_emotes: False`):
   - they are mined only when `Prefs.mine_badges` is true (off by default);
   - they never appear in "Needs you", because they don't need account linking.

   The spec is silent on these campaigns. Exposing the setting is phase 3 UI.

## Global Constraints

- Python `>=3.12`, managed with `uv`. Pin `.python-version` to `3.12`.
- All Twitch constants (client IDs, user agents, GQL operation names and sha256 hashes, pubsub topics) are ported from `reference/fireph-webui/` at fireph/TwitchDropsMiner commit `10706072459ce1125b6747e685bf5c5b3d1a69c6`. They live in **one** module, `src/dropsminer/twitch/constants.py`.
- MIT attribution: `NOTICE` names DevilXD/TwitchDropsMiner and fireph/TwitchDropsMiner with their copyright lines.
- Never log or print an access token. Never commit one. Captured fixtures are scrubbed before they are written into `tests/`.
- Datetimes are timezone-aware UTC everywhere. Pure functions take `now` as a parameter and never call `datetime.now()`.
- One channel is watched at a time. Heartbeat interval: 59 s (`WATCH_INTERVAL`, as in the reference).
- Commits are authored as `Nick <37944729+weltern@users.noreply.github.com>` (repo-local config, already set). Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage explicit paths only, never `git add -A`.
- Line endings LF (`.gitattributes` is already in place).
- **Live safety:** before any step that sends heartbeats from this app, Nick stops the `dungfu/twitch-drops-miner` container on Unraid. Two miners on one account corrupt progress (reference README).

## Review Focus

The inputs most likely to bite a real user that the spec never spelled out. Each one is pinned by a test in the task named.

1. **A drop that requires an earlier drop** (`preconditionDrops`). It isn't earnable until the earlier drop is claimed, and it adds that drop's remaining minutes to its own. Pinned in Task 2 (`test_precondition_chain_*`).
2. **A campaign restricted to specific channels where none of them is live, while other channels stream the game.** It must not be mined on a non-allowed channel. Pinned in Task 3 (`test_allowed_channels_only`).
3. **A badge or emote campaign with `isAccountConnected: false`.** It must not show in "Needs you", and is mined only with `mine_badges`. Pinned in Task 3 (`test_badge_campaign_*`).
4. **Drops with their own time windows, and campaigns ending mid-run.** Drop windows count, not just the campaign's. An earned reward stays claimable for 24 h after the campaign ends. Pinned in Task 2 (`test_drop_window_*`, `test_claimable_within_grace`).
5. **Zero or overshooting minutes:** `requiredMinutesWatched: 0`, or `current > required`. These must not divide by zero or produce negative remaining time. Pinned in Task 2 (`test_zero_required_minutes`, `test_overshoot_clamped`).

---

## File structure

```
drops-miner/
  pyproject.toml            uv project, deps, ruff + pytest config
  .python-version           3.12
  .gitignore
  NOTICE                    MIT attribution for ported code
  README.md                 how to run phase 1
  reference/                vendored MIT reference source (read-only, not imported)
  src/dropsminer/
    __init__.py
    models.py               dataclasses + pure progress/deadline functions
    planner.py              pure plan()
    store.py                SQLite: session, lists, events
    redact.py               logging filter that hides secrets
    runner.py               orchestration loop
    cli.py                  `python -m dropsminer ...`
    __main__.py
    twitch/
      __init__.py
      constants.py          client infos, GQL ops, topics, intervals (ported)
      session.py            TwitchSession + header builders
      transport.py          HttpTransport protocol + aiohttp implementation
      gql.py                Gql: batching, retry, typed errors
      parse.py              raw GQL JSON -> models
      client.py             TwitchClient: campaigns, live channels, claim, current drop
      watch.py              spade URL discovery + heartbeat
      pubsub.py             websocket, topics, typed events
      auth_browser.py       browser sign-in with Android delegation
      capture.py            record + scrub fixtures from a live account
  tests/
    conftest.py
    fixtures/               scrubbed captured responses (Task 7)
    test_models.py test_planner.py test_store.py test_gql.py test_auth_browser.py
    test_capture.py test_parse.py test_client.py test_watch.py test_pubsub.py test_runner.py
```

---

### Task 1: Project scaffold, reference source, attribution

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `NOTICE`, `README.md`, `src/dropsminer/__init__.py`, `src/dropsminer/twitch/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`
- Commit (already downloaded, untracked): `reference/fireph-webui/**`, `reference/fireph-docker/**`

**Interfaces:**
- Produces: importable package `dropsminer`, test runner `uv run pytest`, lint `uv run ruff check`.

- [ ] **Step 1: Write the files**

`pyproject.toml`:
```toml
[project]
name = "dropsminer"
version = "0.1.0"
description = "Headless Twitch drops miner (private)"
requires-python = ">=3.12"
dependencies = [
  "aiohttp>=3.10",
  "zendriver==0.17.0",
]

[project.scripts]
dropsminer = "dropsminer.cli:main"

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dropsminer"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 110
target-version = "py312"
extend-exclude = ["reference"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "ASYNC"]
# capture.py is a dev tool that writes fixture files synchronously by design
per-file-ignores = { "src/dropsminer/twitch/capture.py" = ["ASYNC240"] }
```

`.python-version`:
```
3.12
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
data/
captures/
.pytest_cache/
.ruff_cache/
```

`NOTICE`:
```
Drops Miner ports Twitch protocol logic (client identifiers, GraphQL operation
names and hashes, the minute-watched heartbeat, PubSub topics, and the browser
sign-in delegation) from the following MIT-licensed projects:

  TwitchDropsMiner — Copyright (c) 2024 DevilXD
  https://github.com/DevilXD/TwitchDropsMiner

  TwitchDropsMiner (webui fork) — fireph
  https://github.com/fireph/TwitchDropsMiner (commit 10706072459ce1125b6747e685bf5c5b3d1a69c6)

The original sources are kept unmodified under reference/ with their LICENSE
files. They are read for porting only and are not imported at runtime.
```

`README.md`:
```markdown
# Drops Miner (private)

Phase 1: headless miner. See `docs/superpowers/specs/` for the design.

    uv sync
    uv run dropsminer signin      # opens a browser; sign in to Twitch
    uv run dropsminer lists --priority "Palia,Phasmophobia"
    uv run dropsminer run

Data (SQLite + session) lives in `./data` unless `DROPSMINER_DATA` is set.
Stop any other miner on the same Twitch account first.
```

`src/dropsminer/__init__.py` and `src/dropsminer/twitch/__init__.py`:
```python
```

`tests/conftest.py`:
```python
from datetime import UTC, datetime

import pytest


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
```

`tests/test_smoke.py`:
```python
import dropsminer


def test_package_imports():
    assert dropsminer.__name__ == "dropsminer"
```

- [ ] **Step 2: Install and run**

Run: `uv sync && uv run pytest -q && uv run ruff check`
Expected: `1 passed`, ruff `All checks passed!`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore NOTICE README.md src/dropsminer/__init__.py src/dropsminer/twitch/__init__.py tests/conftest.py tests/test_smoke.py reference
git status --porcelain   # nothing unexpected left unstaged
git commit -m "Scaffold project, vendor MIT reference source, add NOTICE"
```

---

### Task 2: Models and progress arithmetic

**Files:**
- Create: `src/dropsminer/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces (used by planner, parse, runner):
  - `Game(id: int, name: str, slug: str, box_art_url: str = "")`, with property `special -> bool`
  - `Reward(id: str, name: str, image_url: str, kind: str)`
  - `Drop(id, name, rewards: tuple[Reward, ...], starts_at, ends_at, required_minutes: int, current_minutes: int, claimed: bool, claim_id: str | None, preconditions: tuple[str, ...] = ())`
  - `Campaign(id, name, game: Game, starts_at, ends_at, linked: bool, link_url: str, allowed_logins: tuple[str, ...], drops: tuple[Drop, ...])`, with methods `drop(id)`, `has_badge_or_emote`, `in_chain(drop_id)`
  - `LiveChannel(id: int, login: str, game_id: int | None, viewers: int, drops_enabled: bool, broadcast_id: str, game_name: str = "")`
  - `Prefs(priority: tuple[str, ...] = (), never: frozenset[str] = frozenset(), favourites: tuple[str, ...] = (), mine_badges: bool = False)`
  - Functions:
    - `preconditions_met(c, d) -> bool`
    - `drop_open(c, d, now) -> bool`
    - `drop_earnable_now(c, d, now) -> bool`
    - `total_remaining(c, d) -> int`
    - `campaign_active(c, now) -> bool`
    - `campaign_minutes_needed(c, now) -> int`
    - `campaign_ratio(c, now) -> float`
    - `deadline_verdict(ratio: float) -> str` ("plenty" | "tight" | "wont_finish")
    - `claimable(c, d, now) -> bool`
    - `with_drop(c, drop) -> Campaign`
  - Constants: `SPECIAL_GAME_IDS`, `CLAIM_GRACE`

- [ ] **Step 1: Write the failing tests**

`tests/test_models.py`:
```python
import math
from datetime import timedelta

from dropsminer.models import (
    Campaign,
    Drop,
    Game,
    Reward,
    campaign_active,
    campaign_minutes_needed,
    campaign_ratio,
    claimable,
    deadline_verdict,
    drop_earnable_now,
    drop_open,
    preconditions_met,
    total_remaining,
    with_drop,
)

G = Game(id=1, name="Palia", slug="palia")
R = Reward(id="r1", name="10x Ectoplasm", image_url="", kind="DIRECT_ENTITLEMENT")


def drop(id, now, *, req=60, cur=0, claimed=False, pre=(), start=-1, end=96, rewards=(R,), claim_id=None):
    return Drop(id=id, name=id, rewards=rewards, starts_at=now + timedelta(hours=start),
                ends_at=now + timedelta(hours=end), required_minutes=req, current_minutes=cur,
                claimed=claimed, claim_id=claim_id, preconditions=pre)


def camp(now, *drops, start=-24, end=96, linked=True):
    return Campaign(id="c1", name="Frights", game=G, starts_at=now + timedelta(hours=start),
                    ends_at=now + timedelta(hours=end), linked=linked, link_url="",
                    allowed_logins=(), drops=tuple(drops))


def test_simple_remaining_and_ratio(now):
    c = camp(now, drop("a", now, req=60, cur=22, end=4))
    assert campaign_minutes_needed(c, now) == 38
    assert campaign_ratio(c, now) == (4 * 60) / 38


def test_precondition_chain_blocks_until_claimed(now):
    a = drop("a", now, req=60, cur=10)
    b = drop("b", now, req=120, pre=("a",))
    c = camp(now, a, b)
    assert not preconditions_met(c, b)
    assert not drop_earnable_now(c, b, now)
    assert drop_earnable_now(c, a, now)


def test_precondition_chain_adds_remaining_minutes(now):
    a = drop("a", now, req=60, cur=10)
    b = drop("b", now, req=120, pre=("a",))
    c = camp(now, a, b)
    assert total_remaining(c, b) == 120 + 50
    assert campaign_minutes_needed(c, now) == 170


def test_drop_window_not_started_is_open_but_not_earnable_now(now):
    later = drop("a", now, start=2, end=50)
    c = camp(now, later)
    assert drop_open(c, later, now)
    assert not drop_earnable_now(c, later, now)


def test_drop_window_ended_is_closed(now):
    gone = drop("a", now, start=-48, end=-1)
    c = camp(now, gone)
    assert not drop_open(c, gone, now)
    assert campaign_minutes_needed(c, now) == 0
    assert math.isinf(campaign_ratio(c, now))


def test_zero_required_minutes(now):
    z = drop("a", now, req=0)
    c = camp(now, z)
    assert not drop_open(c, z, now)
    assert campaign_minutes_needed(c, now) == 0
    assert math.isinf(campaign_ratio(c, now))


def test_overshoot_clamped(now):
    o = drop("a", now, req=60, cur=75)
    c = camp(now, o)
    assert total_remaining(c, o) == 0


def test_claimed_drop_is_not_open(now):
    d = drop("a", now, claimed=True)
    assert not drop_open(camp(now, d), d, now)


def test_drop_without_rewards_only_counts_inside_a_chain(now):
    bare = drop("a", now, rewards=())
    assert not drop_open(camp(now, bare), bare, now)
    child = drop("b", now, pre=("a",))
    assert drop_open(camp(now, bare, child), bare, now)


def test_campaign_active(now):
    assert campaign_active(camp(now, drop("a", now)), now)
    assert not campaign_active(camp(now, drop("a", now), start=1), now)
    assert not campaign_active(camp(now, drop("a", now), end=-1), now)


def test_claimable_within_grace(now):
    d = drop("a", now, cur=60, claim_id="inst-1")
    ended = camp(now, d, end=-23)
    assert claimable(ended, d, now)
    expired = camp(now, d, end=-25)
    assert not claimable(expired, d, now)
    assert not claimable(ended, drop("b", now, claim_id=None), now)


def test_deadline_verdict_thresholds():
    assert deadline_verdict(0.9) == "wont_finish"
    assert deadline_verdict(1.0) == "tight"
    assert deadline_verdict(1.99) == "tight"
    assert deadline_verdict(2.0) == "plenty"
    assert deadline_verdict(math.inf) == "plenty"


def test_with_drop_replaces_by_id(now):
    c = camp(now, drop("a", now, cur=1), drop("b", now))
    c2 = with_drop(c, drop("a", now, cur=5))
    assert c2.drop("a").current_minutes == 5
    assert c2.drop("b") == c.drop("b")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.models'`

- [ ] **Step 3: Implement**

`src/dropsminer/models.py`:
```python
"""Plain data and pure progress arithmetic.

Semantics are ported from reference/fireph-webui/inventory.py (TimedDrop, DropsCampaign):
drop-level time windows, precondition chains, and the 24 h claim grace period.
Nothing here reads the clock; callers pass `now`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

SPECIAL_GAME_IDS = frozenset({509663, 509672})  # earnable on any channel (reference utils.Game)
BADGE_KINDS = frozenset({"BADGE", "EMOTE"})
CLAIM_GRACE = timedelta(hours=24)  # Twitch help: claimable until 24 h after the campaign ends


@dataclass(frozen=True)
class Game:
    id: int
    name: str
    slug: str
    box_art_url: str = ""

    @property
    def special(self) -> bool:
        return self.id in SPECIAL_GAME_IDS


@dataclass(frozen=True)
class Reward:
    id: str
    name: str
    image_url: str
    kind: str


@dataclass(frozen=True)
class Drop:
    id: str
    name: str
    rewards: tuple[Reward, ...]
    starts_at: datetime
    ends_at: datetime
    required_minutes: int
    current_minutes: int
    claimed: bool
    claim_id: str | None
    preconditions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Campaign:
    id: str
    name: str
    game: Game
    starts_at: datetime
    ends_at: datetime
    linked: bool
    link_url: str
    allowed_logins: tuple[str, ...]
    drops: tuple[Drop, ...]

    def drop(self, drop_id: str) -> Drop | None:
        return next((d for d in self.drops if d.id == drop_id), None)

    @property
    def has_badge_or_emote(self) -> bool:
        return any(r.kind in BADGE_KINDS for d in self.drops for r in d.rewards)

    def in_chain(self, drop_id: str) -> bool:
        return any(drop_id in d.preconditions for d in self.drops if not d.claimed)


@dataclass(frozen=True)
class LiveChannel:
    id: int
    login: str
    game_id: int | None
    viewers: int
    drops_enabled: bool
    broadcast_id: str
    game_name: str = ""


@dataclass(frozen=True)
class Prefs:
    priority: tuple[str, ...] = ()
    never: frozenset[str] = frozenset()
    favourites: tuple[str, ...] = ()
    mine_badges: bool = False


def preconditions_met(c: Campaign, d: Drop) -> bool:
    for pid in d.preconditions:
        pre = c.drop(pid)
        if pre is None or not pre.claimed:
            return False
    return True


def _earn_conditions(c: Campaign, d: Drop) -> bool:
    return (
        not d.claimed
        and d.required_minutes > 0
        and (bool(d.rewards) or c.in_chain(d.id))
    )


def drop_open(c: Campaign, d: Drop, now: datetime) -> bool:
    """Can still be earned at some point (window not over), ignoring preconditions."""
    return _earn_conditions(c, d) and now < d.ends_at


def drop_earnable_now(c: Campaign, d: Drop, now: datetime) -> bool:
    return _earn_conditions(c, d) and preconditions_met(c, d) and d.starts_at <= now < d.ends_at


def total_remaining(c: Campaign, d: Drop) -> int:
    own = max(0, d.required_minutes - d.current_minutes)
    pre = [total_remaining(c, p) for pid in d.preconditions if (p := c.drop(pid)) is not None]
    return own + max(pre, default=0)


def campaign_active(c: Campaign, now: datetime) -> bool:
    return c.starts_at <= now < c.ends_at


def campaign_minutes_needed(c: Campaign, now: datetime) -> int:
    return max((total_remaining(c, d) for d in c.drops if drop_open(c, d, now)), default=0)


def campaign_ratio(c: Campaign, now: datetime) -> float:
    """Spare-time ratio: minutes until the drop ends / minutes still needed (min over open drops).

    Lower is more urgent. inf when nothing is left to earn.
    """
    ratios = []
    for d in c.drops:
        if not drop_open(c, d, now):
            continue
        need = total_remaining(c, d)
        if need <= 0:
            continue
        ratios.append(((d.ends_at - now).total_seconds() / 60) / need)
    return min(ratios, default=math.inf)


def deadline_verdict(ratio: float) -> str:
    if ratio < 1:
        return "wont_finish"
    if ratio < 2:
        return "tight"
    return "plenty"


def claimable(c: Campaign, d: Drop, now: datetime) -> bool:
    return d.claim_id is not None and not d.claimed and now < c.ends_at + CLAIM_GRACE


def with_drop(c: Campaign, drop: Drop) -> Campaign:
    return replace(c, drops=tuple(drop if d.id == drop.id else d for d in c.drops))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_models.py -q && uv run ruff check src tests`
Expected: `13 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/models.py tests/test_models.py
git commit -m "Add campaign/drop models with pure progress and deadline arithmetic"
```

---

### Task 3: Planner

**Files:**
- Create: `src/dropsminer/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: everything in `models` from Task 2.
- Produces:
  - `Choice(campaign_id: str, channel_login: str, reason: str, channel_reason: str)`.
    - `reason` is one of `"priority 1"`, `"priority 2"`, …, `"most urgent"`, `"you picked it"`.
    - `channel_reason` is one of `"favourite"`, `"allowed channel"`, `"any channel"`, `"you picked it"`, `"already watching"`.
  - `Plan(current: Choice | None, queue: tuple[str, ...], needs_you: tuple[str, ...], done: tuple[str, ...], verdicts: dict[str, str], also_credited: tuple[str, ...])`
  - `plan(campaigns, live, prefs, now, *, watching: str | None = None, override_campaign: str | None = None, override_channel: str | None = None) -> Plan`

Rules (spec §6). A campaign is **considered** when it is active and its game is not on Never.
- **needs_you:** considered, not linked, not badge/emote, and it still has an open drop.
- **done:** considered, has drops, and every drop is claimed.
- **eligible:** considered, account-eligible, has a drop earnable now, and has at least one qualifying channel.
  - Account-eligible means `prefs.mine_badges` for badge/emote campaigns, `linked` otherwise.
  - A **qualifying channel** is live with drops enabled, in the allowed list if the campaign has one, and streaming the campaign's game (unless the game is special).
- **Order:** Priority index first. Then `(ratio, ends_at, id)` ascending.
- **Channel tiers:** favourite (by list index), then allowed, then any. Within a tier, viewers descending, then login.
- **Stickiness:** keep `watching` if it qualifies for the chosen campaign, unless the best channel is a favourite that ranks above it.

- [ ] **Step 1: Write the failing tests**

`tests/test_planner.py`:
```python
from datetime import timedelta

from dropsminer.models import Campaign, Drop, Game, LiveChannel, Prefs, Reward
from dropsminer.planner import plan

PALIA = Game(1, "Palia", "palia")
PHAS = Game(2, "Phasmophobia", "phasmophobia")
SPECIAL = Game(509663, "Special Events", "special-events")
R = Reward("r", "Reward", "", "DIRECT_ENTITLEMENT")
BADGE = Reward("b", "Badge", "", "BADGE")


def mk(now, cid, game, *, need=60, cur=0, end_h=96, linked=True, allowed=(), rewards=(R,), claimed=False):
    d = Drop(f"{cid}-d", "d", rewards, now - timedelta(days=1), now + timedelta(hours=end_h),
             need, cur, claimed, None)
    return Campaign(cid, cid, game, now - timedelta(days=1), now + timedelta(hours=end_h),
                    linked, "https://link", tuple(allowed), (d,))


def ch(login, game, viewers=100, drops=True, cid=None):
    return LiveChannel(id=hash(login) % 10_000, login=login, game_id=game.id if game else None,
                       viewers=viewers, drops_enabled=drops, broadcast_id="b-" + login)


def test_priority_beats_urgency(now):
    urgent = mk(now, "phas", PHAS, end_h=2)
    relaxed = mk(now, "palia", PALIA, end_h=200)
    p = plan([urgent, relaxed], [ch("a", PALIA), ch("b", PHAS)], Prefs(priority=("Palia",)), now)
    assert p.current.campaign_id == "palia"
    assert p.current.reason == "priority 1"
    assert p.queue == ("phas",)


def test_unlisted_games_ordered_by_spare_time(now):
    tight = mk(now, "tight", PHAS, need=100, end_h=3)       # 180/100 = 1.8
    loose = mk(now, "loose", PALIA, need=30, end_h=3)       # 180/30 = 6
    p = plan([loose, tight], [ch("a", PALIA), ch("b", PHAS)], Prefs(), now)
    assert p.current.campaign_id == "tight"
    assert p.current.reason == "most urgent"


def test_never_beats_priority(now):
    c = mk(now, "palia", PALIA)
    p = plan([c], [ch("a", PALIA)], Prefs(priority=("Palia",), never=frozenset({"Palia"})), now)
    assert p.current is None
    assert "palia" not in p.needs_you and "palia" not in p.done


def test_unlinked_goes_to_needs_you(now):
    c = mk(now, "bond", PALIA, linked=False)
    p = plan([c], [ch("a", PALIA)], Prefs(), now)
    assert p.current is None
    assert p.needs_you == ("bond",)


def test_badge_campaign_not_in_needs_you_and_skipped_by_default(now):
    c = mk(now, "badge", PALIA, linked=False, rewards=(BADGE,))
    p = plan([c], [ch("a", PALIA)], Prefs(), now)
    assert p.current is None
    assert p.needs_you == ()


def test_badge_campaign_mined_when_enabled(now):
    c = mk(now, "badge", PALIA, linked=False, rewards=(BADGE,))
    p = plan([c], [ch("a", PALIA)], Prefs(mine_badges=True), now)
    assert p.current.campaign_id == "badge"


def test_allowed_channels_only(now):
    c = mk(now, "dnd", PALIA, allowed=("dnd",))
    p = plan([c], [ch("random", PALIA, viewers=9999)], Prefs(), now)
    assert p.current is None
    p2 = plan([c], [ch("random", PALIA, viewers=9999), ch("dnd", PALIA, viewers=1)], Prefs(), now)
    assert p2.current.channel_login == "dnd"
    assert p2.current.channel_reason == "allowed channel"


def test_allowed_channel_must_stream_the_game(now):
    c = mk(now, "dnd", PALIA, allowed=("dnd",))
    p = plan([c], [ch("dnd", PHAS)], Prefs(), now)
    assert p.current is None


def test_special_game_any_channel(now):
    c = mk(now, "sp", SPECIAL)
    p = plan([c], [ch("x", PHAS)], Prefs(), now)
    assert p.current.campaign_id == "sp"


def test_drops_disabled_channel_does_not_qualify(now):
    c = mk(now, "palia", PALIA)
    p = plan([c], [ch("a", PALIA, drops=False)], Prefs(), now)
    assert p.current is None


def test_channel_tiers_favourite_then_allowed_then_viewers(now):
    c = mk(now, "palia", PALIA, allowed=("allowed1", "fav2"))
    live = [ch("big", PALIA, 5000), ch("allowed1", PALIA, 10), ch("fav2", PALIA, 1)]
    # with an allowed list, only allowed channels qualify; favourite wins among them
    p = plan([c], live, Prefs(favourites=("fav1", "fav2")), now)
    assert (p.current.channel_login, p.current.channel_reason) == ("fav2", "favourite")
    open_c = mk(now, "open", PALIA)
    p2 = plan([open_c], live, Prefs(), now)
    assert (p2.current.channel_login, p2.current.channel_reason) == ("big", "any channel")


def test_stickiness_keeps_current_channel(now):
    c = mk(now, "palia", PALIA)
    live = [ch("bigger", PALIA, 900), ch("current", PALIA, 100)]
    p = plan([c], live, Prefs(), now, watching="current")
    assert (p.current.channel_login, p.current.channel_reason) == ("current", "already watching")


def test_favourite_coming_online_breaks_stickiness(now):
    c = mk(now, "palia", PALIA)
    live = [ch("current", PALIA, 900), ch("fav", PALIA, 5)]
    p = plan([c], live, Prefs(favourites=("fav",)), now, watching="current")
    assert p.current.channel_login == "fav"


def test_overrides(now):
    a = mk(now, "a", PALIA)
    b = mk(now, "b", PHAS)
    live = [ch("pa", PALIA), ch("ph1", PHAS, 50), ch("ph2", PHAS, 10)]
    p = plan([a, b], live, Prefs(priority=("Palia",)), now, override_campaign="b",
             override_channel="ph2")
    assert (p.current.campaign_id, p.current.channel_login) == ("b", "ph2")
    assert p.current.reason == "you picked it"
    # an override that is no longer eligible is ignored
    p2 = plan([a, b], live, Prefs(priority=("Palia",)), now, override_campaign="gone")
    assert p2.current.campaign_id == "a"


def test_done_and_verdicts(now):
    finished = mk(now, "fin", PALIA, claimed=True)
    tight = mk(now, "tight", PHAS, need=100, end_h=3)
    p = plan([finished, tight], [ch("b", PHAS)], Prefs(), now)
    assert p.done == ("fin",)
    assert p.verdicts["tight"] == "tight"
    assert "fin" not in p.verdicts


def test_also_credited_same_game_same_channel(now):
    a = mk(now, "a", PALIA, end_h=5)
    b = mk(now, "b", PALIA, end_h=50)
    p = plan([a, b], [ch("x", PALIA)], Prefs(), now)
    assert p.current.campaign_id == "a"
    assert p.also_credited == ("b",)


def test_ties_are_deterministic(now):
    a = mk(now, "a", PALIA)
    b = mk(now, "b", PHAS)
    live = [ch("x", PALIA), ch("y", PHAS)]
    assert plan([b, a], live, Prefs(), now).current.campaign_id == "a"
    assert plan([a, b], live, Prefs(), now).current.campaign_id == "a"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_planner.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.planner'`

- [ ] **Step 3: Implement**

`src/dropsminer/planner.py`:
```python
"""Decide what to mine and where. Pure: no I/O and no clock reads (spec §6)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .models import (
    Campaign,
    LiveChannel,
    Prefs,
    campaign_active,
    campaign_minutes_needed,
    campaign_ratio,
    deadline_verdict,
    drop_earnable_now,
)


@dataclass(frozen=True)
class Choice:
    campaign_id: str
    channel_login: str
    reason: str
    channel_reason: str


@dataclass(frozen=True)
class Plan:
    current: Choice | None
    queue: tuple[str, ...] = ()
    needs_you: tuple[str, ...] = ()
    done: tuple[str, ...] = ()
    verdicts: dict[str, str] = field(default_factory=dict)
    also_credited: tuple[str, ...] = ()


def _qualifies(c: Campaign, ch: LiveChannel) -> bool:
    if not ch.drops_enabled:
        return False
    if c.allowed_logins and ch.login not in c.allowed_logins:
        return False
    return c.game.special or ch.game_id == c.game.id


def _account_ok(c: Campaign, prefs: Prefs) -> bool:
    return prefs.mine_badges if c.has_badge_or_emote else c.linked


def _channel_rank(c: Campaign, ch: LiveChannel, prefs: Prefs) -> tuple:
    if ch.login in prefs.favourites:
        return (0, prefs.favourites.index(ch.login), -ch.viewers, ch.login)
    if ch.login in c.allowed_logins:
        return (1, 0, -ch.viewers, ch.login)
    return (2, 0, -ch.viewers, ch.login)


_TIER = {0: "favourite", 1: "allowed channel", 2: "any channel"}


def plan(
    campaigns: Sequence[Campaign],
    live: Sequence[LiveChannel],
    prefs: Prefs,
    now: datetime,
    *,
    watching: str | None = None,
    override_campaign: str | None = None,
    override_channel: str | None = None,
) -> Plan:
    considered = [c for c in campaigns if campaign_active(c, now) and c.game.name not in prefs.never]
    needs_you = tuple(
        c.id for c in sorted(considered, key=lambda c: (c.ends_at, c.id))
        if not c.linked and not c.has_badge_or_emote and campaign_minutes_needed(c, now) > 0
    )
    done = tuple(
        c.id for c in sorted(considered, key=lambda c: (c.ends_at, c.id))
        if c.drops and all(d.claimed for d in c.drops)
    )
    verdicts = {
        c.id: deadline_verdict(campaign_ratio(c, now))
        for c in considered if campaign_minutes_needed(c, now) > 0
    }

    qualifying: dict[str, list[LiveChannel]] = {}
    for c in considered:
        if not _account_ok(c, prefs):
            continue
        if not any(drop_earnable_now(c, d, now) for d in c.drops):
            continue
        chans = [ch for ch in live if _qualifies(c, ch)]
        if chans:
            qualifying[c.id] = sorted(chans, key=lambda ch: _channel_rank(c, ch, prefs))

    eligible = [c for c in considered if c.id in qualifying]

    def order(c: Campaign) -> tuple:
        if c.game.name in prefs.priority:
            return (0, prefs.priority.index(c.game.name), 0.0, c.ends_at, c.id)
        return (1, 0, campaign_ratio(c, now), c.ends_at, c.id)

    eligible.sort(key=order)
    if not eligible:
        return Plan(None, (), needs_you, done, verdicts, ())

    chosen = next((c for c in eligible if c.id == override_campaign), eligible[0])
    if chosen.id == override_campaign:
        reason = "you picked it"
    elif chosen.game.name in prefs.priority:
        reason = f"priority {prefs.priority.index(chosen.game.name) + 1}"
    else:
        reason = "most urgent"

    chans = qualifying[chosen.id]
    best = chans[0]
    by_login = {ch.login: ch for ch in chans}
    if override_channel in by_login:
        channel, channel_reason = by_login[override_channel], "you picked it"
    elif watching in by_login and not _favourite_outranks(chosen, best, by_login[watching], prefs):
        channel, channel_reason = by_login[watching], "already watching"
    else:
        channel, channel_reason = best, _TIER[_channel_rank(chosen, best, prefs)[0]]

    also = tuple(
        c.id for c in eligible
        if c.id != chosen.id and c.game.id == chosen.game.id and _qualifies(c, channel)
    )
    queue = tuple(c.id for c in eligible if c.id != chosen.id)
    return Plan(
        Choice(chosen.id, channel.login, reason, channel_reason),
        queue, needs_you, done, verdicts, also,
    )


def _favourite_outranks(c: Campaign, best: LiveChannel, current: LiveChannel, prefs: Prefs) -> bool:
    if best.login not in prefs.favourites or best.login == current.login:
        return False
    return _channel_rank(c, best, prefs) < _channel_rank(c, current, prefs)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_planner.py -q && uv run ruff check src tests`
Expected: `17 passed`, ruff clean.

- [ ] **Step 5: Revert-check the Review Focus tests**

Each check below must make its named test fail, for the reason stated. Restore the code after each one (`git stash push -- src/dropsminer/planner.py` / `git stash pop`, or re-apply by hand). Never use `git checkout --` over uncommitted work.

1. In `_qualifies`, delete the `allowed_logins` check. `test_allowed_channels_only` must FAIL because `random` gets chosen.
2. In the `needs_you` comprehension, delete `and not c.has_badge_or_emote`. `test_badge_campaign_not_in_needs_you_and_skipped_by_default` must FAIL.

- [ ] **Step 6: Commit**

```bash
git add src/dropsminer/planner.py tests/test_planner.py
git commit -m "Add pure planner: priority, spare-time order, channel tiers, stickiness, overrides"
```

---

### Task 4: Store (SQLite) and secret redaction

**Files:**
- Create: `src/dropsminer/store.py`, `src/dropsminer/redact.py`, `src/dropsminer/twitch/session.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `TwitchSession(access_token: str, user_id: int, login: str, device_id: str, client_id: str, session_id: str)` (frozen dataclass), with `__repr__` that hides the token.
  - `Store(path: Path)` with methods:
    - `get_session() -> TwitchSession | None`
    - `set_session(s)`
    - `clear_session()`
    - `get_prefs() -> Prefs`
    - `set_lists(priority: Sequence[str], never: Iterable[str], favourites: Sequence[str])`
    - `set_setting(key, value: str)` / `get_setting(key, default=None) -> str | None`
    - `log_event(kind: str, data: dict)`
    - `recent_events(limit=100) -> list[tuple[str, str, dict]]`
    - `close()`
  - `RedactFilter(secrets: Callable[[], Iterable[str]])`, a `logging.Filter` that replaces each secret in the record's message with `***`.

- [ ] **Step 1: Write the failing tests**

`tests/test_store.py`:
```python
import logging
import os
import stat

from dropsminer.models import Prefs
from dropsminer.redact import RedactFilter
from dropsminer.store import Store
from dropsminer.twitch.session import TwitchSession

S = TwitchSession("tok123", 42, "someone", "dev1", "kd1unb4b3q4t58fwlpcbzcbnm76a8fp", "abcd")


def test_session_round_trip_and_clear(tmp_path):
    st = Store(tmp_path / "drops.db")
    assert st.get_session() is None
    st.set_session(S)
    assert Store(tmp_path / "drops.db").get_session() == S
    st.clear_session()
    assert st.get_session() is None


def test_session_repr_hides_token():
    assert "tok123" not in repr(S)


def test_lists_round_trip_and_order(tmp_path):
    st = Store(tmp_path / "drops.db")
    assert st.get_prefs() == Prefs()
    st.set_lists(["Palia", "Phasmophobia"], {"AION 2"}, ["fav_b", "fav_a"])
    p = st.get_prefs()
    assert p.priority == ("Palia", "Phasmophobia")
    assert p.never == frozenset({"AION 2"})
    assert p.favourites == ("fav_b", "fav_a")
    st.set_lists(["Phasmophobia"], set(), [])
    assert st.get_prefs().priority == ("Phasmophobia",)


def test_mine_badges_setting(tmp_path):
    st = Store(tmp_path / "drops.db")
    st.set_setting("mine_badges", "1")
    assert st.get_prefs().mine_badges is True


def test_events(tmp_path):
    st = Store(tmp_path / "drops.db")
    st.log_event("claimed", {"reward": "Palcat Glasses"})
    kind, _, data = st.recent_events()[0]
    assert (kind, data) == ("claimed", {"reward": "Palcat Glasses"})


def test_db_file_not_world_readable(tmp_path):
    Store(tmp_path / "drops.db")
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(tmp_path / "drops.db").st_mode) == 0o600


def test_redact_filter_hides_token():
    rec = logging.LogRecord("x", logging.INFO, "", 0, "sent OAuth %s", ("tok123",), None)
    assert RedactFilter(lambda: ["tok123"]).filter(rec)
    assert "tok123" not in rec.getMessage()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/dropsminer/twitch/session.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TwitchSession:
    access_token: str = field(repr=False)
    user_id: int
    login: str
    device_id: str
    client_id: str
    session_id: str
```

`src/dropsminer/redact.py`:
```python
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable


class RedactFilter(logging.Filter):
    """Replace secrets in log messages. Attach to every handler."""

    def __init__(self, secrets: Callable[[], Iterable[str]]):
        super().__init__()
        self._secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for s in self._secrets():
            if s:
                msg = msg.replace(s, "***")
        record.msg, record.args = msg, None
        return True
```

`src/dropsminer/store.py`:
```python
"""SQLite persistence (spec §7, phase-1 subset: session, lists, settings, events).

Synchronous sqlite3. Every call is a few milliseconds, so the runner calls it directly.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Prefs
from .twitch.session import TwitchSession

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS session (
  id INTEGER PRIMARY KEY CHECK (id = 1), access_token TEXT NOT NULL, user_id INTEGER NOT NULL,
  login TEXT NOT NULL, device_id TEXT NOT NULL, client_id TEXT NOT NULL, session_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS priority (position INTEGER PRIMARY KEY, game_name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS never (game_name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS favourites (position INTEGER PRIMARY KEY, channel_login TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS events (at TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
"""
EVENT_RETENTION = timedelta(days=7)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        self._db = sqlite3.connect(path)
        if new and os.name == "posix":
            os.chmod(path, 0o600)
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- session
    def get_session(self) -> TwitchSession | None:
        row = self._db.execute(
            "SELECT access_token, user_id, login, device_id, client_id, session_id FROM session"
        ).fetchone()
        return TwitchSession(*row) if row else None

    def set_session(self, s: TwitchSession) -> None:
        with self._db:
            self._db.execute("DELETE FROM session")
            self._db.execute(
                "INSERT INTO session VALUES (1, ?, ?, ?, ?, ?, ?)",
                (s.access_token, s.user_id, s.login, s.device_id, s.client_id, s.session_id),
            )

    def clear_session(self) -> None:
        with self._db:
            self._db.execute("DELETE FROM session")

    # --- lists and settings
    def get_prefs(self) -> Prefs:
        pr = tuple(r[0] for r in self._db.execute("SELECT game_name FROM priority ORDER BY position"))
        nv = frozenset(r[0] for r in self._db.execute("SELECT game_name FROM never"))
        fv = tuple(
            r[0] for r in self._db.execute("SELECT channel_login FROM favourites ORDER BY position")
        )
        return Prefs(pr, nv, fv, self.get_setting("mine_badges") == "1")

    def set_lists(
        self, priority: Sequence[str], never: Iterable[str], favourites: Sequence[str]
    ) -> None:
        with self._db:
            self._db.execute("DELETE FROM priority")
            self._db.execute("DELETE FROM never")
            self._db.execute("DELETE FROM favourites")
            self._db.executemany("INSERT INTO priority VALUES (?, ?)", enumerate(priority))
            self._db.executemany("INSERT INTO never VALUES (?)", [(g,) for g in never])
            self._db.executemany("INSERT INTO favourites VALUES (?, ?)", enumerate(favourites))

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # --- events
    def log_event(self, kind: str, data: dict) -> None:
        now = datetime.now(UTC)
        with self._db:
            self._db.execute(
                "INSERT INTO events VALUES (?, ?, ?)", (now.isoformat(), kind, json.dumps(data))
            )
            self._db.execute(
                "DELETE FROM events WHERE at < ?", ((now - EVENT_RETENTION).isoformat(),)
            )

    def recent_events(self, limit: int = 100) -> list[tuple[str, str, dict]]:
        rows = self._db.execute(
            "SELECT at, kind, data FROM events ORDER BY at DESC LIMIT ?", (limit,)
        )
        return [(kind, at, json.loads(data)) for at, kind, data in rows]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_store.py -q && uv run ruff check src tests`
Expected: `7 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/store.py src/dropsminer/redact.py src/dropsminer/twitch/session.py tests/test_store.py
git commit -m "Add SQLite store for session, lists, settings, events; add log redaction"
```

---

### Task 5: Twitch constants, transport, and the GQL client

**Files:**
- Create: `src/dropsminer/twitch/constants.py`, `src/dropsminer/twitch/transport.py`, `src/dropsminer/twitch/gql.py`
- Modify: `src/dropsminer/twitch/session.py` (add header builders)
- Test: `tests/test_gql.py`

**Interfaces:**
- Consumes: `TwitchSession` (Task 4).
- Produces:
  - `constants`:
    - `ClientInfo(client_url, client_id, user_agent)`, `ANDROID_APP`, `WEB`
    - `GQL_OPS: dict[str, tuple[str, str, dict]]`, mapping key to (operationName, sha256, default variables)
    - `TOPICS`
    - `WATCH_INTERVAL = 59`
    - `PUBSUB_URL = "wss://pubsub-edge.twitch.tv/v1"`
    - `PING_INTERVAL = 180`, `PONG_TIMEOUT = 10`
    - `GQL_URL = "https://gql.twitch.tv/gql"`
  - `session`:
    - `base_headers(s: TwitchSession | None, client: ClientInfo) -> dict`
    - `gql_headers(s, client) -> dict` (adds Authorization, Origin, Referer)
  - `transport`:
    - `HttpResponse(status: int, text: str)`, with `.json()`
    - `HttpTransport` Protocol: `async request(method, url, *, headers, json=None, data=None) -> HttpResponse`
    - `AiohttpTransport(timeout=30)`, with `.close()`
  - `gql`:
    - `op(key: str, **variables) -> dict` (deep-merges variables into the defaults)
    - `Gql(transport, session: Callable[[], TwitchSession], client=ANDROID_APP, sleep=asyncio.sleep)`, with `async run(payload) -> dict` and `async run_many(payloads) -> list[dict]`
    - Exceptions: `GqlError(message)`, `AuthExpired(GqlError)`, `TwitchUnreachable(GqlError)`

- [ ] **Step 1: Write `constants.py` (data only, ported)**

Copy the values exactly from `reference/fireph-webui/constants.py`:
- `ClientType.ANDROID_APP` and `ClientType.WEB` (lines 164–240). Take the first user-agent string of each list.
- `GQL_QUERIES` (lines 308–422).
- `WEBSOCKET_TOPICS` (lines 499–512).

`src/dropsminer/twitch/constants.py`:
```python
"""Twitch protocol constants. Ported verbatim from reference/fireph-webui/constants.py
(fireph/TwitchDropsMiner @ 10706072, MIT). Update hashes here only."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClientInfo:
    client_url: str
    client_id: str
    user_agent: str


ANDROID_APP = ClientInfo(
    "https://www.twitch.tv",
    "kd1unb4b3q4t58fwlpcbzcbnm76a8fp",
    "Dalvik/2.1.0 (Linux; U; Android 16; SM-S911B Build/TP1A.220624.014) "
    "tv.twitch.android.app/25.3.0/2503006",
)
WEB = ClientInfo(
    "https://www.twitch.tv",
    "kimne78kx3ncx6brgo4mv6wki5h1ko",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
)

GQL_URL = "https://gql.twitch.tv/gql"
PUBSUB_URL = "wss://pubsub-edge.twitch.tv/v1"
WATCH_INTERVAL = 59
PING_INTERVAL = 180
PONG_TIMEOUT = 10
GQL_BATCH = 20

GQL_OPS: dict[str, tuple[str, str, dict]] = {
    "GetStreamInfo": ("VideoPlayerStreamInfoOverlayChannel",
                      "198492e0857f6aedead9665c81c5a06d67b25b58034649687124083ff288597d",
                      {"channel": None}),
    "ClaimCommunityPoints": ("ClaimCommunityPoints",
                             "46aaeebe02c99afdf4fc97c7c0cba964124bf6b0af229395f1f6d1feed05b3d0",
                             {"input": {"claimID": None, "channelID": None}}),
    "ClaimDrop": ("DropsPage_ClaimDropRewards",
                  "a455deea71bdc9015b78eb49f4acfbce8baa7ccbedd28e549bb025bd0f751930",
                  {"input": {"dropInstanceID": None}}),
    "Inventory": ("Inventory",
                  "8337eb8541b314040b0edde0c09c5c7a2783ba1960aa9edfbf3bac16d0fec404",
                  {"fetchRewardCampaigns": False}),
    "CurrentDrop": ("DropCurrentSessionContext",
                    "4d06b702d25d652afb9ef835d2a550031f1cf762b193523a92166f40ea3d142b",
                    {"channelID": None, "channelLogin": ""}),
    "Campaigns": ("ViewerDropsDashboard",
                  "c16bb890cc8ce7647a96ee69cd313d423a378a3dedadf630a1017cde18975feb",
                  {"fetchRewardCampaigns": False}),
    "CampaignDetails": ("DropCampaignDetails",
                        "039277bf98f3130929262cc7c6efd9c141ca3749cb6dca442fc8ead9a53f77c1",
                        {"channelLogin": None, "dropID": None}),
    "GameDirectory": ("DirectoryPage_Game",
                      "86bcceb4e8b1a51256ff8eed8bd8aae4acacf80d737efe904f84f3aeadf8cafd",
                      {"limit": 30, "slug": None, "imageWidth": 50, "includeCostreaming": False,
                       "options": {"broadcasterLanguages": [], "freeformTags": None,
                                   "includeRestricted": ["SUB_ONLY_LIVE"],
                                   "recommendationsContext": {"platform": "web"},
                                   "sort": "RELEVANCE", "systemFilters": [], "tags": [],
                                   "requestID": "JIRA-VXP-2397"},
                       "sortTypeIsRecency": False}),
}

TOPICS = {
    "user_drops": "user-drop-events",
    "user_notifications": "onsite-notifications",
    "user_points": "community-points-user-v1",
    "stream_state": "video-playback-by-id",
    "stream_update": "broadcast-settings-update",
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_gql.py`:
```python
import json

import pytest

from dropsminer.twitch.constants import ANDROID_APP
from dropsminer.twitch.gql import AuthExpired, Gql, GqlError, TwitchUnreachable, op
from dropsminer.twitch.session import TwitchSession, gql_headers
from dropsminer.twitch.transport import HttpResponse

S = TwitchSession("tok", 42, "me", "dev", ANDROID_APP.client_id, "sess")


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append((method, url, headers, json))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


async def nosleep(_):
    return None


def ok(payload):
    return HttpResponse(200, json.dumps(payload))


def test_op_merges_variables():
    p = op("CampaignDetails", channelLogin="42", dropID="c1")
    assert p["operationName"] == "DropCampaignDetails"
    assert p["variables"] == {"channelLogin": "42", "dropID": "c1"}
    assert p["extensions"]["persistedQuery"]["version"] == 1
    nested = op("GameDirectory", slug="palia", options={"systemFilters": ["DROPS_ENABLED"]})
    assert nested["variables"]["options"]["systemFilters"] == ["DROPS_ENABLED"]
    assert nested["variables"]["options"]["sort"] == "RELEVANCE"


def test_gql_headers_carry_auth_and_client():
    h = gql_headers(S, ANDROID_APP)
    assert h["Authorization"] == "OAuth tok"
    assert h["Client-Id"] == ANDROID_APP.client_id
    assert h["X-Device-Id"] == "dev"
    assert h["Client-Session-Id"] == "sess"


async def test_run_returns_data():
    t = FakeTransport([ok({"data": {"x": 1}})])
    assert await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory")) == {"data": {"x": 1}}


async def test_run_many_batches_by_20():
    t = FakeTransport([ok([{"data": {}}] * 20), ok([{"data": {}}] * 5)])
    out = await Gql(t, lambda: S, sleep=nosleep).run_many([op("Inventory")] * 25)
    assert len(out) == 25
    assert [len(c[3]) for c in t.calls] == [20, 5]


async def test_retries_once_on_service_error():
    err = ok({"errors": [{"message": "service error"}], "extensions": {"operationName": "Inventory"}})
    t = FakeTransport([err, ok({"data": {"y": 2}})])
    assert (await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory")))["data"] == {"y": 2}


async def test_other_gql_error_raises():
    t = FakeTransport([ok({"errors": [{"message": "boom"}]})])
    with pytest.raises(GqlError, match="boom"):
        await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory"))


async def test_401_raises_auth_expired():
    t = FakeTransport([HttpResponse(401, '{"error":"Unauthorized"}')])
    with pytest.raises(AuthExpired):
        await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory"))


async def test_network_errors_become_unreachable_after_3_tries():
    t = FakeTransport([OSError("down")] * 3)
    with pytest.raises(TwitchUnreachable):
        await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory"))
    assert len(t.calls) == 3


async def test_5xx_retried_then_succeeds():
    t = FakeTransport([HttpResponse(503, "busy"), ok({"data": {}})])
    assert await Gql(t, lambda: S, sleep=nosleep).run(op("Inventory")) == {"data": {}}
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_gql.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.twitch.gql'`

- [ ] **Step 4: Implement**

Append to `src/dropsminer/twitch/session.py`:
```python
from .constants import ClientInfo  # noqa: E402


def base_headers(s: TwitchSession | None, client: ClientInfo) -> dict[str, str]:
    h = {
        "Accept": "*/*",
        "Accept-Language": "en-US",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Client-Id": client.client_id,
        "User-Agent": client.user_agent,
    }
    if s is not None:
        h["Client-Session-Id"] = s.session_id
        h["X-Device-Id"] = s.device_id
    return h


def gql_headers(s: TwitchSession, client: ClientInfo) -> dict[str, str]:
    h = base_headers(s, client)
    h.update(Origin=client.client_url, Referer=client.client_url, Authorization=f"OAuth {s.access_token}")
    return h
```

`src/dropsminer/twitch/transport.py`:
```python
from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp


@dataclass(frozen=True)
class HttpResponse:
    status: int
    text: str

    def json(self) -> Any:
        return _json.loads(self.text)


class HttpTransport(Protocol):
    async def request(
        self, method: str, url: str, *, headers: dict[str, str], json: Any = None, data: Any = None
    ) -> HttpResponse: ...


class AiohttpTransport:
    """The real transport. Owns one aiohttp session with its own cookie jar."""

    def __init__(self, timeout: float = 30):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def request(self, method, url, *, headers, json=None, data=None) -> HttpResponse:
        async with self.session.request(method, url, headers=headers, json=json, data=data) as r:
            return HttpResponse(r.status, await r.text(encoding="utf-8"))

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
```

`src/dropsminer/twitch/gql.py`:
```python
"""GQL persisted-query client. Retry rules ported from reference twitch.py gql_request."""
from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .constants import ANDROID_APP, GQL_BATCH, GQL_OPS, GQL_URL, ClientInfo
from .session import TwitchSession, gql_headers
from .transport import HttpTransport

log = logging.getLogger("dropsminer.gql")
RETRY_ONCE = {"service error", "PersistedQueryNotFound"}
NETWORK_TRIES = 3


class GqlError(Exception):
    pass


class AuthExpired(GqlError):
    pass


class TwitchUnreachable(GqlError):
    pass


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def op(key: str, **variables: Any) -> dict:
    name, sha, defaults = GQL_OPS[key]
    return {
        "operationName": name,
        "variables": _merge(defaults, variables),
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}},
    }


class Gql:
    def __init__(
        self,
        transport: HttpTransport,
        session: Callable[[], TwitchSession],
        client: ClientInfo = ANDROID_APP,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._t, self._session, self._client, self._sleep = transport, session, client, sleep

    async def run(self, payload: dict) -> dict:
        return (await self._post(payload))

    async def run_many(self, payloads: list[dict]) -> list[dict]:
        chunks = [payloads[i:i + GQL_BATCH] for i in range(0, len(payloads), GQL_BATCH)]
        results = await asyncio.gather(*(self._post(c) for c in chunks))
        return [item for chunk in results for item in chunk]

    async def _post(self, body: dict | list) -> Any:
        retried = False
        delay = 1.0
        failures = 0
        while True:
            try:
                r = await self._t.request(
                    "POST", GQL_URL, headers=gql_headers(self._session(), self._client), json=body
                )
            except (OSError, TimeoutError, aiohttp.ClientError) as exc:
                failures += 1
                log.warning("GQL network error (%s), try %d", type(exc).__name__, failures)
                if failures >= NETWORK_TRIES:
                    raise TwitchUnreachable(type(exc).__name__) from None
                await self._sleep(delay)
                delay = min(delay * 2, 60)
                continue
            if r.status == 401:
                raise AuthExpired("Twitch rejected the session (401)")
            if r.status >= 500:
                failures += 1
                if failures >= NETWORK_TRIES:
                    raise TwitchUnreachable(f"HTTP {r.status}")
                await self._sleep(delay)
                delay = min(delay * 2, 60)
                continue
            data = r.json()
            items = data if isinstance(data, list) else [data]
            messages = [e.get("message", "") for i in items for e in (i.get("errors") or [])]
            if messages:
                if not retried and RETRY_ONCE.intersection(messages):
                    retried = True
                    await self._sleep(5)
                    continue
                raise GqlError("; ".join(messages))
            return data
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_gql.py -q && uv run ruff check src tests`
Expected: `9 passed`, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/dropsminer/twitch/constants.py src/dropsminer/twitch/transport.py src/dropsminer/twitch/gql.py src/dropsminer/twitch/session.py tests/test_gql.py
git commit -m "Add ported Twitch constants, HTTP transport, and GQL client with retry rules"
```

---

### Task 6: Browser sign-in (Android delegation)

**Files:**
- Create: `src/dropsminer/twitch/auth_browser.py`
- Test: `tests/test_auth_browser.py`

**Interfaces:**
- Consumes:
  - `constants.ANDROID_APP`, `constants.WEB`, `TwitchSession`
  - `transport.HttpTransport` (for validate and device id)
- Produces:
  - `delegated_payload(url: str, method: str, body: str | None) -> str | None`
  - `validate_token(transport, token) -> tuple[int, str]` returns `(user_id, login)`; raises `SignInError` unless the client ID is the Android app's
  - `async device_id(transport) -> str`
  - `class BrowserSignIn(transport, *, display: str | None = None, executable: str | None = None, report: Callable[[str], None] = print)`, with `async sign_in(cancel: asyncio.Event) -> TwitchSession`
  - `SignInError(Exception)`

Port from `reference/fireph-webui/webui/browser_login.py`:
- `delegated_payload` is lines 47–75, unchanged in logic.
- The browser flow is lines 117–325. Keep the CDP interception and the cleanup block verbatim.

Changes from the reference:
- Accept `display=None` (on Windows, a normal visible window, no `--display` args).
- Use `executable` or auto-detect Chrome/Edge on Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`, then `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`.
- **No overall timeout** (spec §4). Remove `LOGIN_TIMEOUT`, and wait on `{login_task, cancel_task}` with no timeout.
- Return a full `TwitchSession`.

- [ ] **Step 1: Write the failing tests (the pure parts)**

`tests/test_auth_browser.py`:
```python
import json

import pytest

from dropsminer.twitch.auth_browser import SignInError, delegated_payload, validate_token
from dropsminer.twitch.constants import ANDROID_APP, WEB
from dropsminer.twitch.transport import HttpResponse

LOGIN = "https://passport.twitch.tv/protected_login"


def test_rewrites_only_protected_login_posts():
    body = json.dumps({"username": "u", "password": "p", "client_id": WEB.client_id})
    out = json.loads(delegated_payload(LOGIN, "POST", body))
    assert out["client_id"] == WEB.client_id
    assert out["delegate_client_id"] == ANDROID_APP.client_id
    assert out["username"] == "u"
    assert delegated_payload(LOGIN + "/shim", "POST", body) is not None
    assert delegated_payload(LOGIN, "GET", body) is None
    assert delegated_payload("https://passport.twitch.tv/other", "POST", body) is None
    assert delegated_payload("http://passport.twitch.tv/protected_login", "POST", body) is None


def test_rejects_unexpected_login_body():
    with pytest.raises(SignInError):
        delegated_payload(LOGIN, "POST", "not json")
    with pytest.raises(SignInError):
        delegated_payload(LOGIN, "POST", json.dumps({"user": "x"}))


class T:
    def __init__(self, resp):
        self.resp = resp

    async def request(self, method, url, *, headers, json=None, data=None):
        assert headers["Authorization"] == "OAuth tok"
        return self.resp


async def test_validate_accepts_android_token():
    body = json.dumps({"client_id": ANDROID_APP.client_id, "user_id": "42", "login": "me"})
    assert await validate_token(T(HttpResponse(200, body)), "tok") == (42, "me")


async def test_validate_rejects_web_token():
    body = json.dumps({"client_id": WEB.client_id, "user_id": "42", "login": "me"})
    with pytest.raises(SignInError, match="WEB"):
        await validate_token(T(HttpResponse(200, body)), "tok")


async def test_validate_rejects_http_error():
    with pytest.raises(SignInError, match="401"):
        await validate_token(T(HttpResponse(401, "{}")), "tok")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_auth_browser.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/dropsminer/twitch/auth_browser.py`:
```python
"""Browser sign-in that yields an Android-app token (spec §4).

Ported from reference/fireph-webui/webui/browser_login.py (MIT). The owner signs in on the real
Twitch page. The protected_login POST is rewritten to carry delegate_client_id=ANDROID_APP, so
Twitch issues an Android token, which can list campaigns (the TV client cannot).
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import secrets
import shutil
from collections.abc import Callable
from urllib.parse import urlsplit

from .constants import ANDROID_APP, WEB
from .session import TwitchSession, base_headers
from .transport import HttpTransport

LOGIN_URL = "https://www.twitch.tv/login"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
WINDOWS_BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


class SignInError(Exception):
    pass


def delegated_payload(url: str, method: str, body: str | None) -> str | None:
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or target.netloc != "passport.twitch.tv"
        or target.path not in ("/protected_login", "/protected_login/shim")
        or method != "POST"
    ):
        return None
    try:
        payload = json.loads(body or "")
    except (ValueError, TypeError):
        raise SignInError("Twitch's login request was not JSON; sign-in stopped.") from None
    if not isinstance(payload, dict) or "username" not in payload or "password" not in payload:
        raise SignInError("Twitch's login request format changed; sign-in stopped.")
    payload["client_id"] = WEB.client_id
    payload["delegate_client_id"] = ANDROID_APP.client_id
    return json.dumps(payload, separators=(",", ":"))


async def validate_token(transport: HttpTransport, token: str) -> tuple[int, str]:
    r = await transport.request("GET", VALIDATE_URL, headers={"Authorization": f"OAuth {token}"})
    if r.status != 200:
        raise SignInError(f"Twitch rejected token validation (HTTP {r.status}).")
    data = r.json()
    cid = data.get("client_id")
    if cid != ANDROID_APP.client_id:
        kind = "WEB" if cid == WEB.client_id else "a different client"
        raise SignInError(f"Twitch issued a token for {kind}, not Android. It was not saved.")
    if not str(data.get("user_id", "")).isdigit():
        raise SignInError("Twitch returned a token without a valid user ID.")
    return int(data["user_id"]), str(data.get("login", ""))


async def device_id(transport: HttpTransport) -> str:
    """The reference reads twitch.tv's unique_id cookie. aiohttp keeps it in the jar; fall back to random."""
    await transport.request("GET", ANDROID_APP.client_url, headers=base_headers(None, ANDROID_APP))
    jar = getattr(getattr(transport, "session", None), "cookie_jar", None)
    if jar is not None:
        for cookie in jar:
            if cookie.key == "unique_id":
                return cookie.value
    return secrets.token_hex(16)


def _find_browser(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if env := os.environ.get("DROPSMINER_BROWSER"):
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    return next((p for p in WINDOWS_BROWSERS if os.path.exists(p)), None)


class BrowserSignIn:
    def __init__(
        self,
        transport: HttpTransport,
        *,
        display: str | None = None,
        executable: str | None = None,
        report: Callable[[str], None] = print,
    ):
        self._t, self._display, self._exe, self._report = transport, display, executable, report

    async def sign_in(self, cancel: asyncio.Event) -> TwitchSession:
        token = await self._browser_token(cancel)
        user_id, login = await validate_token(self._t, token)
        dev = await device_id(self._t)
        self._report(f"Signed in as {login}.")
        return TwitchSession(token, user_id, login, dev, ANDROID_APP.client_id, secrets.token_hex(8))

    async def _browser_token(self, cancel: asyncio.Event) -> str:
        try:
            import zendriver as zd
        except ImportError:
            raise SignInError("zendriver is not installed.") from None
        logging.getLogger("zendriver").setLevel(logging.WARNING)  # CDP logs contain credentials
        browser = None
        tasks: list[asyncio.Task] = []
        outcome: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        intercepted: set[str] = set()
        report = self._report

        def fail(message: str) -> None:
            if not outcome.done():
                outcome.set_exception(SignInError(message))

        async def login_in_browser() -> str:
            nonlocal browser
            report("Starting a browser for Twitch sign-in...")
            args = ["--window-size=1280,900"]
            if self._display:
                args += [f"--display={self._display}", "--ozone-platform=x11"]
            config = zd.Config(
                browser_executable_path=_find_browser(self._exe),
                headless=False,
                browser_connection_timeout=0.25,
                browser_connection_max_tries=60,
                browser_args=args,
            )
            browser = zd.Browser(config)
            await browser.start()
            tab = await browser.get("about:blank")

            async def paused(event) -> None:
                # Port of reference browser_login.py lines 163-240, logic unchanged:
                # rewrite the login POST, capture access_token from the intercepted response.
                request_id = event.request_id
                try:
                    if event.response_status_code is None and event.response_error_reason is None:
                        body = delegated_payload(
                            event.request.url, event.request.method, event.request.post_data
                        )
                        if body is None:
                            await tab.send(zd.cdp.fetch.continue_request(request_id))
                            return
                        intercepted.add(str(request_id))
                        await tab.send(zd.cdp.fetch.continue_request(
                            request_id,
                            post_data=base64.b64encode(body.encode()).decode(),
                            intercept_response=True,
                        ))
                        return
                    candidate = None
                    if str(request_id) in intercepted:
                        intercepted.discard(str(request_id))
                        if event.response_error_reason is not None:
                            report("The login request failed to reach Twitch. Retry in the browser.")
                        elif event.response_status_code not in (301, 302, 303, 307, 308):
                            body, encoded = await tab.send(zd.cdp.fetch.get_response_body(request_id))
                            if encoded:
                                body = base64.b64decode(body).decode()
                            try:
                                result = json.loads(body)
                            except ValueError:
                                result = {}
                            if isinstance(result, dict):
                                tok = result.get("access_token")
                                if event.response_status_code == 200 and isinstance(tok, str) and tok:
                                    candidate = tok
                                else:
                                    code = result.get("error_code")
                                    suffix = f", Twitch error {code}" if isinstance(code, int) else ""
                                    report(f"Login response: HTTP {event.response_status_code}{suffix}. "
                                           "Continue in the browser.")
                    await tab.send(zd.cdp.fetch.continue_request(request_id))
                    if candidate and not outcome.done():
                        outcome.set_result(candidate)
                except SignInError as exc:
                    with contextlib.suppress(Exception):
                        await tab.send(zd.cdp.fetch.fail_request(
                            request_id, zd.cdp.network.ErrorReason.ABORTED))
                    fail(str(exc))
                except Exception as exc:  # noqa: BLE001  CDP errors may contain credentials
                    with contextlib.suppress(Exception):
                        await tab.send(zd.cdp.fetch.continue_request(request_id))
                    fail(f"Could not inspect the login response ({type(exc).__name__}).")

            tab.add_handler(zd.cdp.fetch.RequestPaused, paused)
            await tab.send(zd.cdp.fetch.enable(patterns=[
                zd.cdp.fetch.RequestPattern(url_pattern="https://passport.twitch.tv/protected_login*"),
            ]))
            await tab.get(LOGIN_URL)
            report("Sign in to Twitch in the browser window (password and verification code).")
            while not outcome.done():
                if browser.stopped or tab.closed:
                    raise SignInError("The sign-in browser was closed.")
                await asyncio.wait({outcome}, timeout=0.5)
            return outcome.result()

        try:
            login_task = asyncio.create_task(login_in_browser())
            cancel_task = asyncio.create_task(cancel.wait())
            tasks = [login_task, cancel_task]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done:
                raise SignInError("Sign-in cancelled.")
            return await login_task
        except SignInError:
            raise
        except Exception as exc:  # noqa: BLE001  never surface CDP payloads
            raise SignInError(f"Browser sign-in could not run ({type(exc).__name__}).") from None
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if not outcome.done():
                outcome.cancel()
            elif not outcome.cancelled():
                outcome.exception()
            if browser is not None:
                # Verbatim cleanup from reference lines 298-325 (zendriver 0.17 leaks pipes/listeners)
                process = getattr(browser, "_process", None)
                connections = [getattr(browser, "connection", None), *getattr(browser, "targets", [])]
                listeners = [
                    c.listener.task for c in connections
                    if c is not None and c.listener is not None and c.listener.task is not None
                ]
                try:
                    await browser.stop()
                except Exception as exc:  # noqa: BLE001
                    report(f"Browser cleanup failed ({type(exc).__name__}).")
                finally:
                    for listener in listeners:
                        if not listener.done():
                            listener.cancel()
                    await asyncio.gather(*listeners, return_exceptions=True)
                    if process is not None:
                        for stream in (process.stdin, process.stdout, process.stderr):
                            if stream is not None:
                                stream.close()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_auth_browser.py -q && uv run ruff check src tests`
Expected: `5 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/twitch/auth_browser.py tests/test_auth_browser.py
git commit -m "Add browser sign-in with Android delegation (ported), no overall timeout"
```

---

### Task 7: CLI sign-in, fixture capture, and the first live gate

**Files:**
- Create: `src/dropsminer/cli.py`, `src/dropsminer/__main__.py`, `src/dropsminer/twitch/capture.py`
- Test: `tests/test_capture.py`
- Produces fixtures: `tests/fixtures/inventory.json`, `campaigns.json`, `campaign_details.json`, `directory.json`, `stream_info.json`, `channel_page.html`

**Interfaces:**
- Consumes: `Store` (Task 4), `BrowserSignIn` (Task 6), `Gql`, `op` (Task 5).
- Produces:
  - `capture.scrub(obj, secrets: dict[str, str]) -> obj`. It deep-replaces any string equal to, or containing, a secret value with its placeholder key (e.g. `"<USER_ID>"`).
  - `capture.run_capture(gql, transport, session, out_dir: Path) -> list[Path]`
  - CLI commands, all reading `DROPSMINER_DATA` (default `./data`):
    - `dropsminer signin`
    - `dropsminer capture --out tests/fixtures`
    - `dropsminer lists [--priority CSV] [--never CSV] [--favourites CSV] [--show]`

- [ ] **Step 1: Write the failing test**

`tests/test_capture.py`:
```python
from dropsminer.twitch.capture import scrub


def test_scrub_replaces_secrets_everywhere():
    raw = {
        "user": {"id": "424242", "login": "kernelpanicattack"},
        "list": ["OAuth tok123", 424242, "x"],
        "url": "https://x/kernelpanicattack/y",
    }
    out = scrub(raw, {"tok123": "<TOKEN>", "424242": "<USER_ID>", "kernelpanicattack": "<LOGIN>"})
    assert out == {
        "user": {"id": "<USER_ID>", "login": "<LOGIN>"},
        "list": ["OAuth <TOKEN>", "<USER_ID>", "x"],
        "url": "https://x/<LOGIN>/y",
    }


def test_scrub_ignores_empty_secret():
    assert scrub({"a": "b"}, {"": "<X>"}) == {"a": "b"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_capture.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/dropsminer/twitch/capture.py`:
```python
"""Record real responses from the signed-in account into scrubbed test fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import ANDROID_APP
from .gql import Gql, op
from .session import TwitchSession, base_headers
from .transport import HttpTransport


def scrub(obj: Any, secrets: dict[str, str]) -> Any:
    secrets = {k: v for k, v in secrets.items() if k}
    if isinstance(obj, dict):
        return {k: scrub(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, secrets) for v in obj]
    if isinstance(obj, int) and not isinstance(obj, bool) and str(obj) in secrets:
        return secrets[str(obj)]
    if isinstance(obj, str):
        for secret, placeholder in secrets.items():
            obj = obj.replace(secret, placeholder)
    return obj


async def run_capture(gql: Gql, transport: HttpTransport, s: TwitchSession, out: Path) -> list[Path]:
    secrets = {s.access_token: "<TOKEN>", str(s.user_id): "<USER_ID>", s.login: "<LOGIN>",
               s.device_id: "<DEVICE_ID>", s.session_id: "<SESSION_ID>"}
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(name: str, data: Any) -> None:
        p = out / name
        text = json.dumps(scrub(data, secrets), indent=1, sort_keys=True) if not isinstance(data, str) \
            else scrub(data, secrets)
        p.write_bytes(text.encode("utf-8"))
        written.append(p)

    inventory = await gql.run(op("Inventory"))
    save("inventory.json", inventory)
    campaigns = await gql.run(op("Campaigns"))
    save("campaigns.json", campaigns)
    listed = (campaigns["data"]["currentUser"]["dropCampaigns"] or [])[:3]
    details = await gql.run_many(
        [op("CampaignDetails", channelLogin=str(s.user_id), dropID=c["id"]) for c in listed]
    )
    save("campaign_details.json", details)
    if listed:
        slug = listed[0]["game"].get("slug") or ""
        directory = await gql.run(op(
            "GameDirectory", slug=slug, limit=5, options={"systemFilters": ["DROPS_ENABLED"]}))
        save("directory.json", directory)
        edges = (directory.get("data", {}).get("game") or {}).get("streams", {}).get("edges") or []
        if edges:
            login = edges[0]["node"]["broadcaster"]["login"]
            save("stream_info.json", await gql.run(op("GetStreamInfo", channel=login)))
            page = await transport.request("GET", f"https://www.twitch.tv/{login}",
                                           headers=base_headers(None, ANDROID_APP))
            save("channel_page.html", page.text)  # str: scrubbed as text, not JSON-encoded
    return written
```

`src/dropsminer/cli.py`:
```python
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from .redact import RedactFilter
from .store import Store
from .twitch.auth_browser import BrowserSignIn, SignInError
from .twitch.capture import run_capture
from .twitch.gql import Gql
from .twitch.transport import AiohttpTransport


def data_dir() -> Path:
    return Path(os.environ.get("DROPSMINER_DATA", "data"))


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def setup_logging(store: Store) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter(lambda: [s.access_token] if (s := store.get_session()) else []))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


async def cmd_signin(store: Store) -> int:
    t = AiohttpTransport()
    try:
        session = await BrowserSignIn(t).sign_in(asyncio.Event())
    except SignInError as exc:
        print(f"Sign-in failed: {exc}")
        return 1
    finally:
        await t.close()
    store.set_session(session)
    print(f"Saved session for {session.login}.")
    return 0


async def cmd_capture(store: Store, out: Path) -> int:
    s = store.get_session()
    if s is None:
        print("Not signed in. Run: dropsminer signin")
        return 1
    t = AiohttpTransport()
    try:
        for p in await run_capture(Gql(t, lambda: s), t, s, out):
            print(f"wrote {p}")
    finally:
        await t.close()
    return 0


def cmd_lists(store: Store, args: argparse.Namespace) -> int:
    p = store.get_prefs()
    if not args.show:
        store.set_lists(
            _csv(args.priority) if args.priority is not None else list(p.priority),
            set(_csv(args.never)) if args.never is not None else set(p.never),
            _csv(args.favourites) if args.favourites is not None else list(p.favourites),
        )
        p = store.get_prefs()
    print(f"Priority:   {', '.join(p.priority) or '-'}")
    print(f"Never:      {', '.join(sorted(p.never)) or '-'}")
    print(f"Favourites: {', '.join(p.favourites) or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dropsminer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("signin")
    cap = sub.add_parser("capture")
    cap.add_argument("--out", type=Path, default=Path("tests/fixtures"))
    ls = sub.add_parser("lists")
    ls.add_argument("--priority")
    ls.add_argument("--never")
    ls.add_argument("--favourites")
    ls.add_argument("--show", action="store_true")
    sub.add_parser("run")
    args = ap.parse_args(argv)
    store = Store(data_dir() / "drops.db")
    setup_logging(store)
    if args.cmd == "signin":
        return asyncio.run(cmd_signin(store))
    if args.cmd == "capture":
        return asyncio.run(cmd_capture(store, args.out))
    if args.cmd == "lists":
        return cmd_lists(store, args)
    if args.cmd == "run":
        from .runner import run_cli  # added in Task 11
        return asyncio.run(run_cli(store))
    return 2
```

`src/dropsminer/__main__.py`:
```python
from .cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all pass (`2 passed` new), ruff clean.

- [ ] **Step 5: LIVE GATE A — sign in and capture (needs Nick)**

This step is read-only on Twitch; nothing is watched or claimed, so the dungfu container may keep running.
1. Run `uv run dropsminer signin`. A Chrome window opens on twitch.tv/login. **Nick signs in**, including 2FA.
2. Expected terminal output: `Signed in as kernelpanicattack.` then `Saved session for kernelpanicattack.`
3. Run `uv run dropsminer capture --out captures/raw-check` first, and check the scrub in both directions:
   - **Negative:** `grep -c "kernelpanicattack" captures/raw-check/*` and a grep for the numeric user ID (printed by `uv run python -c "from dropsminer.store import Store; print(Store(__import__('pathlib').Path('data/drops.db')).get_session().user_id)"`) must print 0 for every file.
   - **Positive control:** `grep -c "<USER_ID>\|<LOGIN>" captures/raw-check/*` must print at least 1 in some file, which proves the data really contained the secrets and they were replaced, rather than the probe finding nothing.
4. Then run `uv run dropsminer capture --out tests/fixtures`.
5. Check that the files exist and that `tests/fixtures/campaigns.json` has a non-empty `dropCampaigns` list. This is the decisive check that the Android token can discover campaigns (spec §4).

If step 5 shows `dropCampaigns: null`, **stop the plan and report to Nick**: the sign-in route has changed and the design needs revisiting.

- [ ] **Step 6: Commit (code + scrubbed fixtures; never `data/` or `captures/`)**

```bash
git add src/dropsminer/cli.py src/dropsminer/__main__.py src/dropsminer/twitch/capture.py tests/test_capture.py tests/fixtures
git status --porcelain   # data/ and captures/ must not appear as staged
git diff --cached --stat
git commit -m "Add CLI sign-in and fixture capture; record scrubbed fixtures from live account"
```

---

### Task 8: Parse GQL responses into models, and the TwitchClient

**Files:**
- Create: `src/dropsminer/twitch/parse.py`, `src/dropsminer/twitch/client.py`
- Test: `tests/test_parse.py`, `tests/test_client.py`

**Interfaces:**
- Consumes: models (Task 2), `Gql`, `op` (Task 5), fixtures (Task 7).
- Produces:
  - `parse`:
    - `ts(s: str) -> datetime`
    - `claimed_benefits(inventory_resp) -> dict[str, datetime]`
    - `inventory_campaigns(inventory_resp) -> dict[str, dict]`
    - `dashboard_campaigns(campaigns_resp) -> dict[str, dict]` (ACTIVE/UPCOMING only)
    - `merge(primary: dict, secondary: dict) -> dict` (port of `_merge_data`)
    - `to_campaign(raw: dict, claimed: dict[str, datetime]) -> Campaign | None` (None when `game` is null)
    - `directory_channels(resp, game: Game) -> list[LiveChannel]`
    - `stream_channel(resp) -> LiveChannel | None`
  - `client.TwitchClient(gql: Gql, user_id: int)`:
    - `async campaigns() -> list[Campaign]`
    - `async live_channels(campaigns: list[Campaign], prefs: Prefs, now: datetime) -> list[LiveChannel]`
    - `async claim(claim_id: str) -> bool`
    - `async current_drop(channel_id: int) -> tuple[str, int] | None`

Port references:
- `twitch.py`:
  - `fetch_inventory`, lines 1415–1470 (merge order: inventory is primary; details are fetched in chunks of 20)
  - `_merge_data`, lines 1376–1394
  - `get_live_streams`, lines 1554–1581
- `inventory.py`:
  - `Benefit`, lines 43–55
  - `BaseDrop.__init__`, lines 59–91 (claimed-benefit inference)
  - `TimedDrop.__init__`, lines 219–230
  - `DropsCampaign.__init__`, lines 341–362
- `channel.py`:
  - `Stream.from_get_stream`, lines 87–97
  - `from_directory`, lines 99–111 and 201–209

- [ ] **Step 1: Write the failing tests**

`tests/test_parse.py`:
```python
import json
from pathlib import Path

from dropsminer.models import Game
from dropsminer.twitch.parse import (
    claimed_benefits,
    dashboard_campaigns,
    directory_channels,
    inventory_campaigns,
    merge,
    stream_channel,
    to_campaign,
    ts,
)

FX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_ts_parses_twitch_timestamps():
    assert ts("2026-10-13T13:59:59Z").tzinfo is not None
    assert ts("2026-10-13T13:59:59.123Z").second == 59


def test_merge_primary_wins_and_recurses():
    a = {"x": 1, "d": {"p": 1}, "only_a": True}
    b = {"x": 2, "d": {"p": 2, "q": 3}, "only_b": True}
    assert merge(a, b) == {"x": 1, "d": {"p": 1, "q": 3}, "only_a": True, "only_b": True}


def test_real_inventory_parses_known_campaigns():
    inv = load("inventory.json")
    raw = inventory_campaigns(inv)
    names = {c["name"] for c in raw.values()}
    # campaigns in progress on Nick's account at capture time (spike 2026-10-09)
    assert "Frights & Delights" in names
    claimed = claimed_benefits(inv)
    camps = [c for r in raw.values() if (c := to_campaign(r, claimed))]
    palia = next(c for c in camps if c.name == "Frights & Delights")
    assert palia.game.name == "Palia"
    assert len(palia.drops) == 3
    assert all(d.required_minutes > 0 for d in palia.drops)


def test_real_dashboard_and_details_build_campaigns():
    dash = dashboard_campaigns(load("campaigns.json"))
    assert dash, "dashboard must list campaigns (spec §4 decisive check)"
    details = load("campaign_details.json")
    for item in details:
        dc = item["data"]["user"]["dropCampaign"]
        merged = merge(dash.get(dc["id"], {}), dc)
        camp = to_campaign(merged, {})
        if camp is not None:
            assert camp.ends_at > camp.starts_at
            assert isinstance(camp.allowed_logins, tuple)


def test_game_null_is_dropped():
    assert to_campaign({"id": "x", "game": None}, {}) is None


def test_claimed_inferred_from_benefits_when_no_self_edge():
    raw = {
        "id": "c", "name": "C", "status": "ACTIVE",
        "game": {"id": "1", "displayName": "G", "slug": "g", "boxArtURL": "u-285x380.jpg"},
        "self": {"isAccountConnected": True}, "accountLinkURL": "",
        "startAt": "2026-10-01T00:00:00Z", "endAt": "2026-10-20T00:00:00Z",
        "allow": {"channels": None, "isEnabled": True},
        "timeBasedDrops": [{
            "id": "d", "name": "D", "startAt": "2026-10-01T00:00:00Z",
            "endAt": "2026-10-20T00:00:00Z", "requiredMinutesWatched": 60,
            "preconditionDrops": None,
            "benefitEdges": [{"benefit": {"id": "b1", "name": "B", "distributionType": "BADGE",
                                          "imageAssetURL": "i"}}],
        }],
    }
    c = to_campaign(raw, {"b1": ts("2026-10-05T00:00:00Z")})
    assert c.drops[0].claimed is True
    assert c.has_badge_or_emote


def test_real_directory_channels():
    game = Game(1, "X", "x")
    chans = directory_channels(load("directory.json"), game)
    for ch in chans:
        assert ch.login and ch.broadcast_id and ch.drops_enabled
        assert ch.game_id is not None


def test_real_stream_info():
    ch = stream_channel(load("stream_info.json"))
    assert ch is None or (ch.login and ch.broadcast_id)
```

`tests/test_client.py`:
```python
import json
from datetime import UTC, datetime
from pathlib import Path

from dropsminer.models import Prefs
from dropsminer.twitch.client import TwitchClient

FX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


class FakeGql:
    def __init__(self):
        self.ops = []

    async def run(self, payload):
        self.ops.append(payload["operationName"])
        return {
            "Inventory": load("inventory.json"),
            "ViewerDropsDashboard": load("campaigns.json"),
            "DirectoryPage_Game": load("directory.json"),
            "DropsPage_ClaimDropRewards": {"data": {"claimDropRewards": {"status": "ELIGIBLE_FOR_ALL"}}},
            "DropCurrentSessionContext": {"data": {"currentUser": {"dropCurrentSession": {
                "dropID": "d1", "currentMinutesWatched": 23}}}},
        }[payload["operationName"]]

    async def run_many(self, payloads):
        details = {d["data"]["user"]["dropCampaign"]["id"]: d for d in load("campaign_details.json")}
        out = []
        for p in payloads:
            cid = p["variables"]["dropID"]
            out.append(details.get(cid) or {"data": {"user": {"dropCampaign": {"id": cid}}}})
        return out


async def test_campaigns_merges_inventory_dashboard_and_details():
    camps = await TwitchClient(FakeGql(), 42).campaigns()
    assert any(c.name == "Frights & Delights" for c in camps)
    assert len({c.id for c in camps}) == len(camps)


async def test_claim_and_current_drop():
    c = TwitchClient(FakeGql(), 42)
    assert await c.claim("inst") is True
    assert await c.current_drop(123) == ("d1", 23)


async def test_live_channels_skips_never_games():
    g = FakeGql()
    c = TwitchClient(g, 42)
    camps = await c.campaigns()
    never = frozenset(x.game.name for x in camps)
    await c.live_channels(camps, Prefs(never=never), datetime.now(UTC))
    assert "DirectoryPage_Game" not in g.ops
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_parse.py tests/test_client.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/dropsminer/twitch/parse.py`:
```python
"""Raw GQL JSON -> models. Field names ported from reference inventory.py and channel.py."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import chain

from ..models import Campaign, Drop, Game, LiveChannel, Reward


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _game(g: dict) -> Game:
    art = re.sub(r"-\d+x\d+(?=\.\w+$)", "", g.get("boxArtURL") or "")
    name = g.get("displayName") or g["name"]
    slug = g.get("slug") or re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")
    return Game(int(g["id"]), name, slug, art)


def claimed_benefits(inventory_resp: dict) -> dict[str, datetime]:
    inv = inventory_resp["data"]["currentUser"]["inventory"]
    return {b["id"]: ts(b["lastAwardedAt"]) for b in (inv.get("gameEventDrops") or [])}


def inventory_campaigns(inventory_resp: dict) -> dict[str, dict]:
    inv = inventory_resp["data"]["currentUser"]["inventory"]
    return {c["id"]: c for c in (inv.get("dropCampaignsInProgress") or [])}


def dashboard_campaigns(campaigns_resp: dict) -> dict[str, dict]:
    listed = campaigns_resp["data"]["currentUser"]["dropCampaigns"] or []
    return {c["id"]: c for c in listed if c.get("status") in ("ACTIVE", "UPCOMING")}


def merge(primary: dict, secondary: dict) -> dict:
    out: dict = {}
    for key in set(chain(primary, secondary)):
        if key in primary and key in secondary:
            a, b = primary[key], secondary[key]
            out[key] = merge(a, b) if isinstance(a, dict) and isinstance(b, dict) else a
        else:
            out[key] = primary[key] if key in primary else secondary[key]
    return out


def _drop(d: dict, claimed: dict[str, datetime]) -> Drop:
    rewards = tuple(
        Reward(b["benefit"]["id"], b["benefit"]["name"], b["benefit"].get("imageAssetURL", ""),
               b["benefit"].get("distributionType", "UNKNOWN"))
        for b in (d.get("benefitEdges") or [])
    )
    start, end = ts(d["startAt"]), ts(d["endAt"])
    me = d.get("self")
    if me:
        is_claimed, claim_id = bool(me.get("isClaimed")), me.get("dropInstanceID")
        current = me.get("currentMinutesWatched") or 0
    else:
        stamps = [claimed[r.id] for r in rewards if r.id in claimed]
        is_claimed = bool(stamps) and all(start <= s < end for s in stamps)
        claim_id, current = None, 0
    required = d["requiredMinutesWatched"]
    if is_claimed:
        current = required
    return Drop(d["id"], d["name"], rewards, start, end, required, current, is_claimed, claim_id,
                tuple(p["id"] for p in (d.get("preconditionDrops") or [])))


def to_campaign(raw: dict, claimed: dict[str, datetime]) -> Campaign | None:
    if raw.get("game") is None or "timeBasedDrops" not in raw:
        return None
    allow = raw.get("allow") or {}
    allowed = tuple(
        ch["name"] for ch in (allow.get("channels") or [])
    ) if allow.get("isEnabled", True) else ()
    return Campaign(
        raw["id"], raw["name"], _game(raw["game"]), ts(raw["startAt"]), ts(raw["endAt"]),
        bool((raw.get("self") or {}).get("isAccountConnected")), raw.get("accountLinkURL") or "",
        allowed, tuple(_drop(d, claimed) for d in raw["timeBasedDrops"]),
    )


def directory_channels(resp: dict, game: Game) -> list[LiveChannel]:
    g = (resp.get("data") or {}).get("game")
    if not g:
        return []
    out = []
    for edge in g["streams"]["edges"]:
        node = edge["node"]
        b = node.get("broadcaster")
        if b is None:
            continue
        out.append(LiveChannel(int(b["id"]), b["login"], game.id, node.get("viewersCount") or 0,
                               True, str(node["id"]), game.name))
    return out


def stream_channel(resp: dict) -> LiveChannel | None:
    user = (resp.get("data") or {}).get("user")
    if not user or not user.get("stream"):
        return None
    game = (user.get("broadcastSettings") or {}).get("game")
    return LiveChannel(int(user["id"]), user["login"], int(game["id"]) if game else None,
                       user["stream"].get("viewersCount") or 0, True, str(user["stream"]["id"]),
                       (game or {}).get("displayName") or (game or {}).get("name") or "")
```

> Note for the implementer: confirm `user["id"]` and `user["login"]` exist in `tests/fixtures/stream_info.json`. If the captured shape differs (for example the login sits under another key), adjust `stream_channel` to the fixture and keep the test. The fixture is the authority.

`src/dropsminer/twitch/client.py`:
```python
"""Twitch reads and writes the runner needs, built on Gql + parse."""
from __future__ import annotations

import logging
from datetime import datetime

from ..models import Campaign, LiveChannel, Prefs, campaign_active
from . import parse
from .gql import GqlError, op

log = logging.getLogger("dropsminer.client")


class TwitchClient:
    def __init__(self, gql, user_id: int):
        self._gql, self._user_id = gql, user_id

    async def campaigns(self) -> list[Campaign]:
        inv = await self._gql.run(op("Inventory"))
        claimed = parse.claimed_benefits(inv)
        data = parse.inventory_campaigns(inv)
        dash = parse.dashboard_campaigns(await self._gql.run(op("Campaigns")))
        if dash:
            ids = list(dash)
            details = await self._gql.run_many(
                [op("CampaignDetails", channelLogin=str(self._user_id), dropID=i) for i in ids])
            fetched = {}
            for item in details:
                dc = ((item.get("data") or {}).get("user") or {}).get("dropCampaign")
                if dc:
                    fetched[dc["id"]] = parse.merge(dash.get(dc["id"], {}), dc)
            data = parse.merge(data, fetched)
        out = []
        for raw in data.values():
            try:
                c = parse.to_campaign(raw, claimed)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Skipping campaign %s: unexpected shape (%s)", raw.get("id"), exc)
                continue
            if c is not None:
                out.append(c)
        return out

    async def live_channels(
        self, campaigns: list[Campaign], prefs: Prefs, now: datetime
    ) -> list[LiveChannel]:
        wanted = {c.game.id: c.game for c in campaigns
                  if campaign_active(c, now) and c.game.name not in prefs.never}
        seen: dict[str, LiveChannel] = {}
        for game in wanted.values():
            resp = await self._gql.run(op("GameDirectory", slug=game.slug,
                                          options={"systemFilters": ["DROPS_ENABLED"]}))
            for ch in parse.directory_channels(resp, game):
                seen.setdefault(ch.login, ch)
        acl = {lg for c in campaigns if c.game.id in wanted for lg in c.allowed_logins} - set(seen)
        acl |= set(prefs.favourites) - set(seen)
        if acl:
            for resp in await self._gql.run_many([op("GetStreamInfo", channel=lg) for lg in sorted(acl)]):
                ch = parse.stream_channel(resp)
                if ch is not None:
                    seen.setdefault(ch.login, ch)
        return list(seen.values())

    async def claim(self, claim_id: str) -> bool:
        try:
            resp = await self._gql.run(op("ClaimDrop", input={"dropInstanceID": claim_id}))
        except GqlError as exc:
            log.warning("Claim failed: %s", exc)
            return False
        result = (resp.get("data") or {}).get("claimDropRewards")
        return bool(result) and result.get("status") in (
            "ELIGIBLE_FOR_ALL", "DROP_INSTANCE_ALREADY_CLAIMED")

    async def current_drop(self, channel_id: int) -> tuple[str, int] | None:
        resp = await self._gql.run(op("CurrentDrop", channelID=str(channel_id)))
        cur = ((resp.get("data") or {}).get("currentUser") or {}).get("dropCurrentSession")
        return (cur["dropID"], cur["currentMinutesWatched"]) if cur else None
```

> Check against the reference before relying on it: `inventory.py` lines 210–216 list the claim statuses the reference treats as success. Copy that exact set into `claim()` if it differs from the two above.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_parse.py tests/test_client.py -q && uv run ruff check src tests`
Expected: `11 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/twitch/parse.py src/dropsminer/twitch/client.py tests/test_parse.py tests/test_client.py
git commit -m "Parse campaigns, drops and channels from GQL; add TwitchClient"
```

---

### Task 9: The watch heartbeat

**Files:**
- Create: `src/dropsminer/twitch/watch.py`
- Test: `tests/test_watch.py`

**Interfaces:**
- Consumes:
  - `LiveChannel`, `TwitchSession`, `HttpTransport`
  - fixture `channel_page.html`
- Produces:
  - `find_spade_url(text: str) -> str | None`
  - `find_settings_js(html: str) -> str | None`
  - `watch_payload(channel: LiveChannel, user_id: int, now: datetime) -> dict`, returning `{"data": base64}`
  - `Watcher(transport, session: Callable[[], TwitchSession])`, with `async send(channel, now) -> bool` (True on HTTP 204; caches the spade URL per login)

Port: `channel.py` lines 45–74 (payload) and 302–324 (`get_spade_url`), plus `send_watch` lines 484–496.

- [ ] **Step 1: Write the failing tests**

`tests/test_watch.py`:
```python
import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from dropsminer.models import LiveChannel
from dropsminer.twitch.session import TwitchSession
from dropsminer.twitch.transport import HttpResponse
from dropsminer.twitch.watch import Watcher, find_settings_js, find_spade_url, watch_payload

CH = LiveChannel(77, "streamer", 1, 10, True, "b123", "Palia")
S = TwitchSession("tok", 42, "me", "dev", "cid", "sess")
NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def test_payload_is_base64_minute_watched():
    body = watch_payload(CH, 42, NOW)
    events = json.loads(base64.b64decode(body["data"]))
    props = events[0]["properties"]
    assert events[0]["event"] == "minute-watched"
    assert props["broadcast_id"] == "b123" and props["channel_id"] == "77"
    assert props["channel"] == "streamer" and props["user_id"] == 42
    assert props["minutes_logged"] == 1 and props["game"] == "Palia" and props["game_id"] == "1"


def test_find_spade_url_variants():
    assert find_spade_url('x "spade_url": "https://video-edge.example/abc" y') == \
        "https://video-edge.example/abc"
    assert find_spade_url('"spadeUrl":"https://spade.twitch.tv/track"') == "https://spade.twitch.tv/track"
    assert find_spade_url("nothing here") is None


def test_find_settings_js():
    html = '<script src="https://static.twitchcdn.net/config/settings.0123456789abcdef0123456789abcdef.js">'
    assert find_settings_js(html).endswith(".js")


def test_real_channel_page_yields_a_url():
    html = (Path(__file__).parent / "fixtures" / "channel_page.html").read_text(encoding="utf-8")
    assert find_spade_url(html) or find_settings_js(html)


class T:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append((method, url, data))
        return self.replies.pop(0)


async def test_send_fetches_spade_once_then_posts():
    page = HttpResponse(200, '"spade_url": "https://spade.example/x"')
    t = T([page, HttpResponse(204, ""), HttpResponse(204, "")])
    w = Watcher(t, lambda: S)
    assert await w.send(CH, NOW) is True
    assert await w.send(CH, NOW) is True
    assert [c[0] for c in t.calls] == ["GET", "POST", "POST"]
    assert t.calls[1][1] == "https://spade.example/x"


async def test_send_reports_failure():
    t = T([HttpResponse(200, '"spade_url": "https://spade.example/x"'), HttpResponse(400, "")])
    assert await Watcher(t, lambda: S).send(CH, NOW) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_watch.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/dropsminer/twitch/watch.py`:
```python
"""Minute-watched heartbeat (reference channel.py send_watch / spade_payload, MIT)."""
from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime

from ..models import LiveChannel
from .constants import ANDROID_APP
from .session import TwitchSession, base_headers
from .transport import HttpTransport

log = logging.getLogger("dropsminer.watch")
SETTINGS_RE = re.compile(r'src="(https://[\w.]+/config/settings\.[0-9a-f]{32}\.js)"', re.I)
SPADE_RE = re.compile(r'"spade_?url": ?"(https://[.\w\-/]+)"', re.I)


def find_spade_url(text: str) -> str | None:
    m = SPADE_RE.search(text)
    return m.group(1) if m else None


def find_settings_js(html: str) -> str | None:
    m = SETTINGS_RE.search(html)
    return m.group(1) if m else None


def watch_payload(channel: LiveChannel, user_id: int, now: datetime) -> dict:
    events = [{
        "event": "minute-watched",
        "properties": {
            "broadcast_id": channel.broadcast_id,
            "channel_id": str(channel.id),
            "channel": channel.login,
            "client_time": now.isoformat(),
            "game": channel.game_name,
            "game_id": str(channel.game_id) if channel.game_id is not None else "",
            "hidden": False,
            "is_live": True,
            "live": True,
            "logged_in": True,
            "minutes_logged": 1,
            "muted": False,
            "user_id": user_id,
        },
    }]
    raw = json.dumps(events, separators=(",", ":")).encode("utf-8")
    return {"data": base64.b64encode(raw).decode("utf-8")}


class Watcher:
    def __init__(self, transport: HttpTransport, session: Callable[[], TwitchSession]):
        self._t, self._session = transport, session
        self._spade: dict[str, str] = {}

    async def _spade_url(self, login: str) -> str | None:
        if login in self._spade:
            return self._spade[login]
        headers = base_headers(None, ANDROID_APP)
        page = await self._t.request("GET", f"https://www.twitch.tv/{login}", headers=headers)
        url = find_spade_url(page.text)
        if url is None and (js := find_settings_js(page.text)):
            url = find_spade_url((await self._t.request("GET", js, headers=headers)).text)
        if url:
            self._spade[login] = url
        return url

    def forget(self, login: str) -> None:
        self._spade.pop(login, None)

    async def send(self, channel: LiveChannel, now: datetime) -> bool:
        url = await self._spade_url(channel.login)
        if url is None:
            log.warning("No spade URL for %s", channel.login)
            return False
        s = self._session()
        r = await self._t.request("POST", url, headers=base_headers(s, ANDROID_APP),
                                  data=watch_payload(channel, s.user_id, now))
        if r.status != 204:
            log.info("Heartbeat to %s returned HTTP %s", channel.login, r.status)
        return r.status == 204
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_watch.py -q && uv run ruff check src tests`
Expected: `6 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/twitch/watch.py tests/test_watch.py
git commit -m "Add minute-watched heartbeat with spade URL discovery"
```

---

### Task 10: PubSub (one websocket, typed events)

**Files:**
- Create: `src/dropsminer/twitch/pubsub.py`
- Test: `tests/test_pubsub.py`

**Interfaces:**
- Consumes: `constants.PUBSUB_URL`, `PING_INTERVAL`, `PONG_TIMEOUT`, `TOPICS`.
- Produces:
  - Events (frozen dataclasses):
    - `DropProgress(drop_id: str, current: int, required: int)`
    - `DropClaimable(drop_id: str, claim_id: str)`
    - `StreamUp(channel_id: int)`
    - `StreamDown(channel_id: int)`
    - `Viewers(channel_id: int, viewers: int)`
    - `StreamChanged(channel_id: int)`
    - `PointsClaimable(channel_id: int, claim_id: str)`
  - `topic(key: str, target_id: int) -> str`
  - `parse_message(topic: str, message: dict) -> object | None`
  - `PubSub(token: Callable[[], str], url=PUBSUB_URL, *, ping_interval=PING_INTERVAL, pong_timeout=PONG_TIMEOUT, session_factory=aiohttp.ClientSession)`, with:
    - `set_topics(topics: set[str])`
    - `async events()`, an async iterator of events
    - `async close()`
    - `connected: bool`

Port: `websocket.py` lines 145–304 (LISTEN/UNLISTEN in chunks of 20, PING every 3 min, reconnect on missing PONG within 10 s or on `RECONNECT`). Payload shapes: `twitch.py` `process_drops` lines 1162–1219 and `process_stream_state` lines 1052–1076.

- [ ] **Step 1: Write the failing tests**

`tests/test_pubsub.py`:
```python
import asyncio
import json

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

from dropsminer.twitch.pubsub import (
    DropClaimable,
    DropProgress,
    PubSub,
    StreamDown,
    StreamUp,
    Viewers,
    parse_message,
    topic,
)


def test_topic_names():
    assert topic("user_drops", 42) == "user-drop-events.42"
    assert topic("stream_state", 7) == "video-playback-by-id.7"


def test_parse_drop_messages():
    t = "user-drop-events.42"
    assert parse_message(t, {"type": "drop-progress", "data": {
        "drop_id": "d", "current_progress_min": 3, "required_progress_min": 10}}) == DropProgress("d", 3, 10)
    assert parse_message(t, {"type": "drop-claim", "data": {
        "drop_id": "d", "drop_instance_id": "inst"}}) == DropClaimable("d", "inst")


def test_parse_stream_state_messages():
    t = "video-playback-by-id.7"
    assert parse_message(t, {"type": "stream-down"}) == StreamDown(7)
    assert parse_message(t, {"type": "stream-up"}) == StreamUp(7)
    assert parse_message(t, {"type": "viewcount", "viewers": 12}) == Viewers(7, 12)
    assert parse_message(t, {"type": "commercial"}) is None


async def test_listens_and_delivers_events():
    received = []

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            received.append(data)
            if data["type"] == "LISTEN":
                await ws.send_json({"type": "RESPONSE", "error": ""})
                await ws.send_json({"type": "MESSAGE", "data": {
                    "topic": "video-playback-by-id.7",
                    "message": json.dumps({"type": "stream-down"})}})
        return ws

    app = web.Application()
    app.router.add_get("/", handler)
    async with TestServer(app) as server:
        ps = PubSub(lambda: "tok", str(server.make_url("/")).replace("http", "ws"))
        ps.set_topics({"video-playback-by-id.7"})
        ev = await asyncio.wait_for(anext(ps.events()), 5)
        await ps.close()
    assert ev == StreamDown(7)
    listen = next(m for m in received if m["type"] == "LISTEN")
    assert listen["data"] == {"topics": ["video-playback-by-id.7"], "auth_token": "tok"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pubsub.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/dropsminer/twitch/pubsub.py`:
```python
"""Twitch PubSub over one websocket (reference websocket.py, MIT)."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import aiohttp

from .constants import PING_INTERVAL, PONG_TIMEOUT, PUBSUB_URL, TOPICS

log = logging.getLogger("dropsminer.pubsub")


@dataclass(frozen=True)
class DropProgress:
    drop_id: str
    current: int
    required: int


@dataclass(frozen=True)
class DropClaimable:
    drop_id: str
    claim_id: str


@dataclass(frozen=True)
class StreamUp:
    channel_id: int


@dataclass(frozen=True)
class StreamDown:
    channel_id: int


@dataclass(frozen=True)
class Viewers:
    channel_id: int
    viewers: int


@dataclass(frozen=True)
class StreamChanged:
    channel_id: int


@dataclass(frozen=True)
class PointsClaimable:
    channel_id: int
    claim_id: str


def topic(key: str, target_id: int) -> str:
    return f"{TOPICS[key]}.{target_id}"


def parse_message(topic_name: str, message: dict) -> object | None:
    prefix, _, target = topic_name.rpartition(".")
    kind = message.get("type")
    data = message.get("data") or {}
    if prefix == TOPICS["user_drops"]:
        if kind == "drop-progress":
            return DropProgress(data["drop_id"], data["current_progress_min"], data["required_progress_min"])
        if kind == "drop-claim":
            return DropClaimable(data["drop_id"], data["drop_instance_id"])
    elif prefix == TOPICS["stream_state"]:
        cid = int(target)
        if kind == "stream-up":
            return StreamUp(cid)
        if kind == "stream-down":
            return StreamDown(cid)
        if kind == "viewcount":
            return Viewers(cid, message.get("viewers", 0))
    elif prefix == TOPICS["stream_update"]:
        return StreamChanged(int(target))
    elif prefix == TOPICS["user_points"] and kind == "claim-available":
        claim = data.get("claim") or {}
        return PointsClaimable(int(claim.get("channel_id", 0)), claim.get("id", ""))
    return None


class PubSub:
    def __init__(
        self,
        token: Callable[[], str],
        url: str = PUBSUB_URL,
        *,
        ping_interval: float = PING_INTERVAL,
        pong_timeout: float = PONG_TIMEOUT,
        session_factory: Callable[[], aiohttp.ClientSession] = aiohttp.ClientSession,
    ):
        self._token, self._url = token, url
        self._ping_interval, self._pong_timeout = ping_interval, pong_timeout
        self._factory = session_factory
        self._wanted: set[str] = set()
        self._changed = asyncio.Event()
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._closing = False
        self.connected = False

    def set_topics(self, topics: set[str]) -> None:
        if topics != self._wanted:
            self._wanted = set(topics)
            self._changed.set()
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def events(self) -> AsyncIterator[object]:
        while True:
            yield await self._queue.get()

    async def close(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _send_topics(self, ws, kind: str, topics: list[str]) -> None:
        for i in range(0, len(topics), 20):
            await ws.send_json({"type": kind, "data": {"topics": topics[i:i + 20],
                                                       "auth_token": self._token()}})

    async def _run(self) -> None:
        delay = 1.0
        async with self._factory() as session:
            while not self._closing:
                try:
                    async with session.ws_connect(self._url, heartbeat=None) as ws:
                        self.connected, delay = True, 1.0
                        await self._session(ws)
                except (TimeoutError, aiohttp.ClientError, OSError) as exc:
                    log.warning("PubSub connection problem: %s", type(exc).__name__)
                finally:
                    self.connected = False
                if self._closing:
                    return
                await asyncio.sleep(delay)
                delay = min(delay * 2, 180)

    async def _session(self, ws) -> None:
        submitted: set[str] = set()
        next_ping = time.monotonic()
        pong_deadline: float | None = None
        self._changed.set()
        while True:
            now = time.monotonic()
            if now >= next_ping:
                await ws.send_json({"type": "PING"})
                next_ping, pong_deadline = now + self._ping_interval, now + self._pong_timeout
            elif pong_deadline is not None and now >= pong_deadline:
                log.warning("No PONG from PubSub; reconnecting")
                return
            if self._changed.is_set():
                self._changed.clear()
                removed, added = sorted(submitted - self._wanted), sorted(self._wanted - submitted)
                if removed:
                    await self._send_topics(ws, "UNLISTEN", removed)
                if added:
                    await self._send_topics(ws, "LISTEN", added)
                submitted = set(self._wanted)
            try:
                msg = await ws.receive(timeout=0.5)
            except TimeoutError:
                continue
            if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                return
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            kind = data.get("type")
            if kind == "PONG":
                pong_deadline = None
            elif kind == "RECONNECT":
                return
            elif kind == "MESSAGE":
                t = data["data"]["topic"]
                try:
                    ev = parse_message(t, json.loads(data["data"]["message"]))
                except (KeyError, ValueError, TypeError) as exc:
                    log.warning("Unparseable PubSub message on %s: %s", t, exc)
                    continue
                if ev is not None:
                    await self._queue.put(ev)
            elif kind == "RESPONSE" and data.get("error"):
                log.warning("PubSub LISTEN error: %s", data["error"])
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_pubsub.py -q && uv run ruff check src tests`
Expected: `4 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/twitch/pubsub.py tests/test_pubsub.py
git commit -m "Add PubSub client with typed drop and stream events"
```

---

### Task 11: Runner

**Files:**
- Create: `src/dropsminer/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes:
  - `planner.plan`, `Plan`
  - models
  - `Store` (`get_prefs`, `log_event`, `get_session`)
  - `TwitchClient`-like (`campaigns`, `live_channels`, `claim`, `current_drop`)
  - `Watcher`-like (`send`, `forget`)
  - PubSub-like (`set_topics`)
  - `pubsub.topic`
  - events from Task 10
  - `gql.AuthExpired`, `gql.TwitchUnreachable`
- Produces:
  - `State` (StrEnum): `MINING`, `SWITCHED`, `PAUSED`, `IDLE`, `SIGNED_OUT`, `TWITCH_UNREACHABLE`
  - `Runner(client, watcher, pubsub, store, *, user_id: int, clock: Callable[[], datetime], emit: Callable[[str, dict], None] = lambda k, d: None)`, with:
    - attributes `state`, `plan`, `campaigns`, `live`, `watching: LiveChannel | None`, `paused_until`
    - `async refresh()`
    - `async tick()`
    - `async handle(event)`
    - `pause(until: datetime | None)`, `resume()`
    - `mine_now(campaign_id)`, `use_channel(login)`
  - `async run_cli(store) -> int`, the CLI loop: sign-in check, wiring, forever loop

Behaviour:
- `refresh()`:
  - loads campaigns and live channels;
  - claims any `claimable` drop (catch-up);
  - re-plans and sets `watching`;
  - updates PubSub topics (user drops + notifications + watched channel's stream state/update).
  - On `AuthExpired` → `SIGNED_OUT`. On `TwitchUnreachable` → `TWITCH_UNREACHABLE`.
- `tick()`:
  - if paused and not yet due, do nothing;
  - else send a heartbeat to `watching`.
  - 3 consecutive failures → `watcher.forget(login)`, exclude that channel for 10 minutes, `refresh()`.
  - If no `DropProgress` has arrived for 3 ticks, resync minutes via `current_drop`.
- `handle()`:
  - `DropProgress` → update the minutes of that drop;
  - `DropClaimable` → claim, log `claimed`, `refresh()`;
  - `StreamDown` of the watched channel → `refresh()` and state `SWITCHED` (with from/to);
  - `StreamChanged` of the watched channel → `refresh()`.
- Emits `("state", {...})`, `("claimed", {...})`, `("switched", {...})` through `emit`, and logs the same to `store`.

- [ ] **Step 1: Write the failing tests**

`tests/test_runner.py`:
```python
from datetime import UTC, datetime, timedelta

from dropsminer.models import Campaign, Drop, Game, LiveChannel, Prefs, Reward
from dropsminer.runner import Runner, State
from dropsminer.twitch.gql import AuthExpired, TwitchUnreachable
from dropsminer.twitch.pubsub import DropClaimable, DropProgress, StreamDown

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
G = Game(1, "Palia", "palia")


def camp(cur=0, claim_id=None, claimed=False):
    d = Drop("d1", "Glasses", (Reward("r", "Palcat Glasses", "", "DIRECT_ENTITLEMENT"),),
             NOW - timedelta(days=1), NOW + timedelta(days=4), 60, cur, claimed, claim_id)
    return Campaign("c1", "Frights", G, NOW - timedelta(days=1), NOW + timedelta(days=4),
                    True, "", (), (d,))


def chan(login, cid):
    return LiveChannel(cid, login, 1, 100, True, f"b{cid}", "Palia")


class FakeClient:
    def __init__(self, campaigns, live):
        self.camps, self.live, self.claims, self.fail = campaigns, live, [], None

    async def campaigns(self):
        if self.fail:
            raise self.fail
        return list(self.camps)

    async def live_channels(self, campaigns, prefs, now):
        return list(self.live)

    async def claim(self, claim_id):
        self.claims.append(claim_id)
        self.camps = [camp(cur=60, claimed=True)]
        return True

    async def current_drop(self, channel_id):
        return ("d1", 30)


class FakeWatcher:
    def __init__(self, ok=True):
        self.ok, self.sent, self.forgotten = ok, [], []

    async def send(self, channel, now):
        self.sent.append(channel.login)
        return self.ok

    def forget(self, login):
        self.forgotten.append(login)


class FakePubSub:
    def __init__(self):
        self.topics = set()

    def set_topics(self, topics):
        self.topics = set(topics)


class FakeStore:
    def __init__(self):
        self.events = []

    def get_prefs(self):
        return Prefs()

    def log_event(self, kind, data):
        self.events.append((kind, data))


def runner(client, watcher=None, clock=lambda: NOW):
    return Runner(client, watcher or FakeWatcher(), FakePubSub(), FakeStore(), user_id=42, clock=clock)


async def test_refresh_picks_channel_and_subscribes():
    r = runner(FakeClient([camp()], [chan("a", 7)]))
    await r.refresh()
    assert r.state == State.MINING and r.watching.login == "a"
    assert "video-playback-by-id.7" in r._pubsub.topics
    assert "user-drop-events.42" in r._pubsub.topics


async def test_tick_sends_heartbeat():
    w = FakeWatcher()
    r = runner(FakeClient([camp()], [chan("a", 7)]), w)
    await r.refresh()
    await r.tick()
    assert w.sent == ["a"]


async def test_claim_on_event_and_logged():
    c = FakeClient([camp(cur=60, claim_id="inst")], [chan("a", 7)])
    r = runner(c)
    await r.refresh()  # catch-up claim happens here
    assert c.claims == ["inst"]
    assert ("claimed", {"campaign": "Frights", "reward": "Palcat Glasses"}) in r._store.events
    c2 = FakeClient([camp(cur=50)], [chan("a", 7)])
    r2 = runner(c2)
    await r2.refresh()
    await r2.handle(DropClaimable("d1", "inst2"))
    assert c2.claims == ["inst2"]


async def test_progress_updates_minutes():
    r = runner(FakeClient([camp()], [chan("a", 7)]))
    await r.refresh()
    await r.handle(DropProgress("d1", 33, 60))
    assert r.campaigns[0].drop("d1").current_minutes == 33


async def test_stream_down_switches_channel():
    c = FakeClient([camp()], [chan("a", 7), chan("b", 8)])
    r = runner(c)
    await r.refresh()
    first = r.watching.login
    c.live = [x for x in c.live if x.login != first]
    await r.handle(StreamDown(r.watching.id))
    assert r.watching.login != first
    assert r.state == State.SWITCHED


async def test_three_heartbeat_failures_drop_the_channel():
    c = FakeClient([camp()], [chan("a", 7), chan("b", 8)])
    w = FakeWatcher(ok=False)
    r = runner(c, w)
    await r.refresh()
    bad = r.watching.login
    for _ in range(3):
        await r.tick()
    assert w.forgotten == [bad]
    assert r.watching.login != bad


async def test_pause_and_resume():
    w = FakeWatcher()
    r = runner(FakeClient([camp()], [chan("a", 7)]), w)
    await r.refresh()
    r.pause(NOW + timedelta(hours=1))
    await r.tick()
    assert r.state == State.PAUSED and w.sent == []
    r.resume()
    await r.tick()
    assert w.sent == ["a"]


async def test_pause_expires_by_clock():
    now = [NOW]
    w = FakeWatcher()
    r = runner(FakeClient([camp()], [chan("a", 7)]), w, clock=lambda: now[0])
    await r.refresh()
    r.pause(NOW + timedelta(minutes=30))
    now[0] = NOW + timedelta(minutes=31)
    await r.tick()
    assert w.sent == ["a"]


async def test_auth_expired_sets_signed_out():
    c = FakeClient([camp()], [chan("a", 7)])
    c.fail = AuthExpired("401")
    r = runner(c)
    await r.refresh()
    assert r.state == State.SIGNED_OUT


async def test_unreachable_state():
    c = FakeClient([camp()], [chan("a", 7)])
    c.fail = TwitchUnreachable("down")
    r = runner(c)
    await r.refresh()
    assert r.state == State.TWITCH_UNREACHABLE


async def test_idle_when_nothing_live():
    r = runner(FakeClient([camp()], []))
    await r.refresh()
    assert r.state == State.IDLE and r.watching is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_runner.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/dropsminer/runner.py`:
```python
"""Mining loop. Owns state; never touches any UI (spec §5, §9)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .models import Campaign, LiveChannel, claimable, with_drop
from .planner import Plan, plan
from .twitch.constants import WATCH_INTERVAL
from .twitch.gql import AuthExpired, TwitchUnreachable
from .twitch.pubsub import DropClaimable, DropProgress, StreamChanged, StreamDown, topic

log = logging.getLogger("dropsminer.runner")
FAILS_BEFORE_SWITCH = 3
STALL_TICKS = 3
EXCLUDE_FOR = timedelta(minutes=10)
REFRESH_EVERY = timedelta(minutes=5)


class State(StrEnum):
    MINING = "mining"
    SWITCHED = "switched"
    PAUSED = "paused"
    IDLE = "idle"
    SIGNED_OUT = "signed_out"
    TWITCH_UNREACHABLE = "twitch_unreachable"


class Runner:
    def __init__(self, client, watcher, pubsub, store, *, user_id: int,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 emit: Callable[[str, dict], None] = lambda k, d: None):
        self._client, self._watcher, self._pubsub, self._store = client, watcher, pubsub, store
        self._user_id, self._clock, self._emit = user_id, clock, emit
        self.state: State = State.IDLE
        self.plan: Plan | None = None
        self.campaigns: list[Campaign] = []
        self.live: list[LiveChannel] = []
        self.watching: LiveChannel | None = None
        self.paused_until: datetime | None = None
        self._paused = False
        self._fails = 0
        self._ticks_since_progress = 0
        self._excluded: dict[str, datetime] = {}
        self._override_campaign: str | None = None
        self._override_channel: str | None = None
        self.last_refresh: datetime | None = None

    # --- commands
    def pause(self, until: datetime | None) -> None:
        self._paused, self.paused_until = True, until
        self._set_state(State.PAUSED, {"until": until.isoformat() if until else None})

    def resume(self) -> None:
        self._paused, self.paused_until = False, None
        self._set_state(State.MINING if self.watching else State.IDLE)

    def mine_now(self, campaign_id: str) -> None:
        self._override_campaign = campaign_id

    def use_channel(self, login: str) -> None:
        self._override_channel = login

    # --- core
    def _set_state(self, state: State, extra: dict | None = None) -> None:
        if state != self.state or extra:
            self.state = state
            data = {"state": str(state), **(extra or {})}
            self._emit("state", data)
            self._store.log_event("state", data)

    async def refresh(self) -> None:
        now = self._clock()
        prefs = self._store.get_prefs()
        try:
            self.campaigns = await self._client.campaigns()
            await self._catch_up_claims(now)
            self.live = await self._client.live_channels(self.campaigns, prefs, now)
        except AuthExpired:
            self.watching = None
            self._set_state(State.SIGNED_OUT)
            return
        except TwitchUnreachable as exc:
            self._set_state(State.TWITCH_UNREACHABLE, {"error": str(exc)})
            return
        self.last_refresh = now
        self._excluded = {k: v for k, v in self._excluded.items() if v > now}
        usable = [c for c in self.live if c.login not in self._excluded]
        previous = self.watching
        self.plan = plan(self.campaigns, usable, prefs, now,
                         watching=previous.login if previous else None,
                         override_campaign=self._override_campaign,
                         override_channel=self._override_channel)
        cur = self.plan.current
        self.watching = next((c for c in usable if cur and c.login == cur.channel_login), None)
        topics = {topic("user_drops", self._user_id), topic("user_notifications", self._user_id)}
        if self.watching:
            topics |= {topic("stream_state", self.watching.id), topic("stream_update", self.watching.id)}
        self._pubsub.set_topics(topics)
        if self._paused:
            return
        if self.watching is None:
            self._set_state(State.IDLE)
        elif previous and previous.login != self.watching.login:
            self._fails = 0
            info = {"from": previous.login, "to": self.watching.login}
            self._emit("switched", info)
            self._store.log_event("switched", info)
            self._set_state(State.SWITCHED, info)
        else:
            self._set_state(State.MINING)

    async def _catch_up_claims(self, now: datetime) -> None:
        for c in list(self.campaigns):
            for d in c.drops:
                if claimable(c, d, now) and d.current_minutes >= d.required_minutes:
                    await self._claim(c, d.id, d.claim_id)

    async def _claim(self, c: Campaign, drop_id: str, claim_id: str | None) -> None:
        if not claim_id:
            return
        d = c.drop(drop_id)
        if await self._client.claim(claim_id):
            info = {"campaign": c.name, "reward": ", ".join(r.name for r in d.rewards) if d else drop_id}
            self._emit("claimed", info)
            self._store.log_event("claimed", info)
            self.campaigns = await self._client.campaigns()
        else:
            self._store.log_event("claim_failed", {"campaign": c.name, "drop": drop_id})

    async def tick(self) -> None:
        now = self._clock()
        if self._paused:
            if self.paused_until is None or now < self.paused_until:
                self._set_state(State.PAUSED)
                return
            self.resume()
        if self.last_refresh is None or now - self.last_refresh >= REFRESH_EVERY:
            await self.refresh()
        if self.watching is None:
            return
        if await self._watcher.send(self.watching, now):
            self._fails = 0
        else:
            self._fails += 1
            if self._fails >= FAILS_BEFORE_SWITCH:
                bad = self.watching.login
                self._watcher.forget(bad)
                self._excluded[bad] = now + EXCLUDE_FOR
                self._store.log_event("channel_dropped", {"channel": bad})
                self._fails = 0
                await self.refresh()
                return
        self._ticks_since_progress += 1
        if self._ticks_since_progress >= STALL_TICKS and self.watching:
            cur = await self._client.current_drop(self.watching.id)
            if cur:
                await self.handle(DropProgress(cur[0], cur[1], -1))

    async def handle(self, event: object) -> None:
        if isinstance(event, DropProgress):
            self._ticks_since_progress = 0
            for i, c in enumerate(self.campaigns):
                d = c.drop(event.drop_id)
                if d is not None:
                    self.campaigns[i] = with_drop(c, replace(d, current_minutes=event.current))
            self._emit("progress", {"drop": event.drop_id, "minutes": event.current})
        elif isinstance(event, DropClaimable):
            for c in self.campaigns:
                if c.drop(event.drop_id) is not None:
                    await self._claim(c, event.drop_id, event.claim_id)
                    break
            await self.refresh()
        elif isinstance(event, (StreamDown, StreamChanged)):
            if self.watching and event.channel_id == self.watching.id:
                if isinstance(event, StreamDown):
                    self.live = [c for c in self.live if c.id != event.channel_id]
                await self.refresh()


async def run_cli(store) -> int:
    """`dropsminer run`: wire the real pieces and loop until Ctrl+C."""
    from .twitch.client import TwitchClient
    from .twitch.gql import Gql
    from .twitch.pubsub import PubSub
    from .twitch.transport import AiohttpTransport
    from .twitch.watch import Watcher

    session = store.get_session()
    if session is None:
        print("Not signed in. Run: dropsminer signin")
        return 1
    transport = AiohttpTransport()
    pubsub = PubSub(lambda: session.access_token)

    def emit(kind: str, data: dict) -> None:
        log.info("%s %s", kind, data)

    r = Runner(TwitchClient(Gql(transport, lambda: session), session.user_id),
               Watcher(transport, lambda: session), pubsub, store,
               user_id=session.user_id, emit=emit)

    async def events() -> None:
        async for ev in pubsub.events():
            await r.handle(ev)

    events_task = asyncio.create_task(events())
    try:
        await r.refresh()
        while r.state != State.SIGNED_OUT:
            await r.tick()
            await asyncio.sleep(WATCH_INTERVAL)
        print("Twitch session expired. Run: dropsminer signin")
        return 1
    finally:
        events_task.cancel()
        await pubsub.close()
        await transport.close()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: whole suite passes (`11 passed` in `test_runner.py`), ruff clean.

- [ ] **Step 5: Revert-check one runner test**

In `tick()`, change `FAILS_BEFORE_SWITCH` to `99`. `test_three_heartbeat_failures_drop_the_channel` must FAIL with `assert [] == ['a']` or similar. Restore it.

- [ ] **Step 6: Commit**

```bash
git add src/dropsminer/runner.py tests/test_runner.py
git commit -m "Add runner: refresh, heartbeat, claims, switching, pause, auth and outage states"
```

---

### Task 12: Phase gate: mutation check, review, live acceptance

**Files:**
- Modify: `README.md` (record the live-run result)

- [ ] **Step 1: Mutation-check the planner**

Use the `mutation-check` skill on `src/dropsminer/planner.py` with `tests/test_planner.py`. Every surviving mutant must be either killed by a new test or reported as equivalent with a reason. Commit any new tests:
```bash
git add tests/test_planner.py
git commit -m "Strengthen planner tests from mutation check"
```

- [ ] **Step 2: Code review of the whole phase**

Run a local review of `git diff $(git rev-list --max-parents=0 HEAD)..HEAD -- src tests`, using the `superpowers:requesting-code-review` skill. Fix findings in their own commits.

- [ ] **Step 3: LIVE GATE B — mine on Nick's account (needs Nick)**

1. **Nick stops the `twitch-drops-miner` (dungfu) container on Unraid.** Confirm it's stopped before continuing.
2. Run `uv run dropsminer lists --priority "Palia,Phasmophobia"`, or whatever Nick wants.
3. Run `uv run dropsminer run`. Leave it running for **at least 2 hours**.
4. Pass criteria, all from the log and from Twitch itself (not only our log):
   - a `state {'state': 'mining'}` line is followed by heartbeats with no repeated failures;
   - Twitch's drops inventory page shows the watched campaign's minutes increasing over the run;
   - at least one `claimed` event, and Twitch's inventory shows that reward as claimed;
   - stop with Ctrl+C and run again: it resumes without asking to sign in.
5. Record the result (date, duration, rewards claimed, any warnings) in `README.md` under "Phase 1 live run".

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Record phase 1 live acceptance"
```

- [ ] **Step 5: Report to Nick**

Report:
- what was claimed;
- anything that misbehaved;
- that the dungfu container is still stopped (his call whether to restart it until phase 5);
- the next step: the Phase 2 plan (API and store).
