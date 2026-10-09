# Drops Miner Phase 2 (API and Store) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `dropsminer serve` command that runs the miner and a password-protected JSON API together, plus a live event stream. Phase 3's dashboard is built against this API.

**Architecture:**
- The miner loop moves out of `run_cli` into a `MinerService` that can start and stop at runtime. Sign-in through the API starts it; sign-out stops it.
- Runner events go to an in-process `EventBus`, which fans them out to SSE clients.
- FastAPI routers read the runner's state through one pure view builder (`api/views.py`) and change it only through runner commands.
- SQLite gains claims, page-password and web-session tables.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, pydantic v2, argon2-cffi, httpx (tests), pytest, ruff. This is on top of phase 1.

**Spec:** `docs/superpowers/specs/2026-10-09-drops-miner-design.md` (§7 Data, §8 API, §9 Runner states, §14 phase 2).

**Spike (2026-10-09):** every code block was applied to a scratch copy of main b68aa5f and run.
- Result: 182 tests pass, ruff is clean, and 18 of 18 targeted mutations are killed.
- `serve` was smoke-tested against an empty data dir: health, me, 401 without cookie, setup, state, SSE connect, and 409 for pause while signed out.
- Fixed in this plan:
  - sync handlers ran in a worker thread, which sqlite refuses;
  - the route-list test broke on FastAPI 0.143;
  - `"yes"` was accepted as a boolean;
  - history grouped by UTC day;
  - lint.
- This proves the plan's tests pass against the plan's code with fakes. It says nothing about live Twitch; that is Task 12's live gate.

**Declared deviations from the spec** (Nick to confirm when reviewing):
1. **Moved to phase 4**, together with the notifier and missed-reward logic:
   - `POST /api/notify/test`;
   - the history's "ended campaigns with missed reasons".

   Phase 2 stores the notification settings and returns claims-only history.
2. **`GET /api/twitch/signin/vnc` moves to phase 5.** It needs Xvfb/noVNC, which only exist in the container. In phase 2, `POST /api/twitch/signin` opens the sign-in browser on the machine running the server (Nick's PC), exactly like `dropsminer signin`.
3. **A `refreshed` SSE event replaces the spec's `needs_you` event.** The page re-reads `GET /api/state` on `refreshed`, `claimed` and `switched`. One snapshot is simpler than mirroring every list as an event.
4. **History is a flat claim list.** The page groups claims by the viewer's local day, because the server can't know the zone and UTC days would split evenings.
5. **TypeScript type generation moves to phase 3**, which creates `web/`. Phase 2 commits `docs/api/openapi.json` with a test that fails if it is stale.
6. **Two phase-1 deferred minor issues are fixed here, because the API makes them reachable:**
   - "Mine now" and channel overrides now clear once the campaign or channel stops being chosen (spec §6).
   - Favourite channels are stored lowercased.

## Global Constraints

- Every `/api/*` route requires the page session cookie, except `GET /api/health`, `GET /api/me`, `POST /api/setup` and `POST /api/login` (spec §8).
- **Page password:**
  - argon2 hash, minimum 8 characters;
  - `POST /api/setup` refuses (409) once a password exists.
- **Session cookie:**
  - name `dm_session`, `HttpOnly`, `SameSite=Strict`, 30-day lifetime;
  - the server stores only `sha256(token)`;
  - `Secure` is off, because it's served over plain http on the LAN; phase 5 revisits it behind a proxy.
- **Every route handler and dependency is `async def`.** FastAPI runs a plain `def` in a worker thread;
  the SQLite connection refuses other threads, and the runner must only be touched on the event loop.
  `SignInManager.start()` also needs the running loop for `create_task`.
- Never log or return the Twitch token, the page password, a session token or a signed playlist URL.
- **The API never mutates the runner directly.** It calls `pause`, `resume`, `mine_now`, `use_channel` and `refresh` only.
- **The EventBus never blocks the runner.** A slow client loses its oldest events.
- Default bind `127.0.0.1:5810`. Phase 5 sets `0.0.0.0`.
- Commits:
  - author `Nick <37944729+weltern@users.noreply.github.com>`;
  - message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - stage explicit paths only.
- **One miner per Twitch account.** Before the live gate, stop the phase-1 `dropsminer run` process (PID shown by `Get-CimInstance Win32_Process | ? CommandLine -match 'dropsminer'`). The dungfu container stays stopped.

## Review Focus

1. **A slow or stuck SSE client.** It must never block the runner, and it loses only its own oldest events. Pinned in Task 1 (`test_slow_subscriber_drops_oldest_not_blocks`).
2. **Auth bypass.**
   - Every non-public route returns 401 without the cookie.
   - `/api/setup` can't overwrite an existing password.
   - A logged-out token stops working.

   Pinned in Task 6 (`test_every_private_route_requires_session`, `test_setup_refused_once_password_exists`, `test_logout_invalidates_token`).
3. **Bad command input:**
   - pause with 0, a negative or more than 1440 minutes;
   - mine-now with an unknown campaign;
   - commands while signed out.

   These are rejected with 422/404/409, never silently accepted. Pinned in Task 8.
4. **Contradictory lists.**
   - A game in both Priority and Never → 422.
   - Duplicates are collapsed.
   - Favourites are lowercased.

   Pinned in Task 2 and Task 7.
5. **State before the first refresh, while signed out, and for a drop with no rewards.** `GET /api/state` returns a valid, empty-safe snapshot. Pinned in Task 5.

---

## File structure

```
src/dropsminer/
  events.py            EventBus: fan-out with bounded per-subscriber queues
  service.py           MinerService: start/stop the mining loop; default wiring
  store.py             (+ claims, page password, web sessions, typed settings)
  runner.py            (+ record claims, `refreshed` event, clear stale overrides)
  cli.py               (+ `serve`, `openapi`; `run` uses MinerService)
  api/
    __init__.py
    models.py          pydantic request/response models
    views.py           pure: runner/store -> StateOut, history grouping
    auth.py            setup/login/logout/me + session dependency
    app.py             create_app(ctx) and all routers
    signin.py          SignInManager (browser sign-in as a background job)
    sse.py             sse_stream() async generator
docs/api/openapi.json  committed schema (freshness-tested)
tests/
  test_events.py test_store_phase2.py test_runner_phase2.py test_service.py
  test_views.py test_auth_api.py test_api_data.py test_api_commands.py
  test_sse.py test_signin_api.py test_openapi.py
  apihelpers.py        shared app/test fixtures
```

---

### Task 1: EventBus

**Files:**
- Create: `src/dropsminer/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Produces: `EventBus(maxsize: int = 100)`, with:
  - `publish(kind: str, data: dict) -> None` (synchronous, never blocks);
  - `subscribe() -> asyncio.Queue[tuple[str, dict]]`;
  - `unsubscribe(q) -> None`;
  - `subscribers: int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_events.py`:
```python
import asyncio

from dropsminer.events import EventBus


async def test_fan_out_to_every_subscriber():
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish("claimed", {"reward": "x"})
    assert await a.get() == ("claimed", {"reward": "x"})
    assert await b.get() == ("claimed", {"reward": "x"})


async def test_slow_subscriber_drops_oldest_not_blocks():
    bus = EventBus(maxsize=3)
    q = bus.subscribe()
    for i in range(10):
        bus.publish("progress", {"i": i})   # must return immediately
    got = [q.get_nowait()[1]["i"] for _ in range(q.qsize())]
    assert got == [7, 8, 9]


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.publish("state", {})
    assert q.empty() and bus.subscribers == 0


async def test_publish_without_subscribers_is_fine():
    EventBus().publish("state", {})
    await asyncio.sleep(0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_events.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.events'`

- [ ] **Step 3: Implement**

`src/dropsminer/events.py`:
```python
"""In-process event fan-out for the live page (SSE). Never blocks the publisher."""
from __future__ import annotations

import asyncio


class EventBus:
    def __init__(self, maxsize: int = 100):
        self._maxsize = maxsize
        self._subs: set[asyncio.Queue[tuple[str, dict]]] = set()

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def subscribe(self) -> asyncio.Queue[tuple[str, dict]]:
        q: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=self._maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[tuple[str, dict]]) -> None:
        self._subs.discard(q)

    def publish(self, kind: str, data: dict) -> None:
        for q in list(self._subs):
            if q.full():
                q.get_nowait()  # a slow client loses its oldest event, never the runner's time
            q.put_nowait((kind, data))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_events.py -q && uv run ruff check src tests`
Expected: `4 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/events.py tests/test_events.py
git commit -m "Add non-blocking EventBus for live page events"
```

---

### Task 2: Store: claims, page password, web sessions, typed settings, list normalisation

**Files:**
- Modify: `pyproject.toml` (add `argon2-cffi>=23.1`)
- Modify: `src/dropsminer/store.py`
- Test: `tests/test_store_phase2.py`

**Interfaces:**
- Consumes: `Store` (phase 1).
- Produces:
  - `Store.add_claim(at: datetime, campaign_id: str, campaign: str, game: str, rewards: list[tuple[str, str]]) -> None`, where `rewards` is `(name, image_url)` pairs;
  - `Store.claims_since(since: datetime) -> list[dict]`, where each dict has the keys `at` (datetime), `campaign_id`, `campaign`, `game`, `rewards` (list of `{"name", "image_url"}`), newest first;
  - `Store.has_password() -> bool`;
  - `Store.set_password(plain: str) -> None`;
  - `Store.check_password(plain: str) -> bool`;
  - `Store.create_web_session(now: datetime) -> str` returns the raw token;
  - `Store.valid_web_session(token: str | None, now: datetime) -> bool`;
  - `Store.delete_web_session(token: str) -> None`;
  - `Store.get_settings() -> dict` and `Store.put_settings(values: dict) -> dict`, typed per `SETTINGS`;
  - `set_lists` now dedupes (keeping first occurrence) and lowercases favourites.
  - Constants: `SETTINGS: dict[str, type]`, `SESSION_TTL = timedelta(days=30)`, `MIN_PASSWORD = 8`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml` `dependencies`, add `"argon2-cffi>=23.1",`. Run `uv sync`. Expected: installs argon2-cffi.

- [ ] **Step 2: Write the failing tests**

`tests/test_store_phase2.py`:
```python
from datetime import UTC, datetime, timedelta

import pytest

from dropsminer.store import Store

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def test_claims_round_trip_newest_first(tmp_path):
    st = Store(tmp_path / "d.db")
    st.add_claim(NOW - timedelta(hours=2), "c1", "Frights", "Palia", [("Palcat Glasses", "u1")])
    st.add_claim(NOW, "c2", "Crimson", "Phasmophobia", [("T-Shirt", "u2"), ("Badge", "u3")])
    rows = st.claims_since(NOW - timedelta(days=1))
    assert [r["campaign"] for r in rows] == ["Crimson", "Frights"]
    assert rows[0]["rewards"] == [{"name": "T-Shirt", "image_url": "u2"},
                                  {"name": "Badge", "image_url": "u3"}]
    assert rows[0]["at"] == NOW
    assert st.claims_since(NOW - timedelta(minutes=1))[0]["campaign"] == "Crimson"
    assert len(st.claims_since(NOW - timedelta(minutes=1))) == 1


def test_password_set_check(tmp_path):
    st = Store(tmp_path / "d.db")
    assert not st.has_password()
    st.set_password("correct horse")
    assert st.has_password()
    assert st.check_password("correct horse")
    assert not st.check_password("wrong")
    assert "correct horse" not in (st.get_setting("page_password_hash") or "")


def test_password_minimum_length(tmp_path):
    with pytest.raises(ValueError):
        Store(tmp_path / "d.db").set_password("short")


def test_web_sessions_store_only_hash_and_expire(tmp_path):
    st = Store(tmp_path / "d.db")
    tok = st.create_web_session(NOW)
    assert st.valid_web_session(tok, NOW + timedelta(days=29))
    assert not st.valid_web_session(tok, NOW + timedelta(days=31))
    assert not st.valid_web_session("nope", NOW)
    assert not st.valid_web_session(None, NOW)
    raw = (tmp_path / "d.db").read_bytes()
    assert tok.encode() not in raw
    st.delete_web_session(tok)
    assert not st.valid_web_session(tok, NOW)


def test_settings_typed_defaults_and_validation(tmp_path):
    st = Store(tmp_path / "d.db")
    s = st.get_settings()
    assert s == {"mine_badges": False, "claim_points": True, "notify_target": "",
                 "notify_claimed": True, "notify_needs_you": True, "notify_signin": True}
    out = st.put_settings({"mine_badges": True, "notify_target": "https://ntfy.sh/x"})
    assert out["mine_badges"] is True and out["notify_target"] == "https://ntfy.sh/x"
    assert st.get_prefs().mine_badges is True
    with pytest.raises(ValueError):
        st.put_settings({"unknown": 1})
    with pytest.raises(ValueError):
        st.put_settings({"mine_badges": "yes"})


def test_lists_dedupe_and_lowercase_favourites(tmp_path):
    st = Store(tmp_path / "d.db")
    st.set_lists(["Palia", "Palia", "Phasmophobia"], {"AION 2"}, ["KernelPanic", "kernelpanic", "Other"])
    p = st.get_prefs()
    assert p.priority == ("Palia", "Phasmophobia")
    assert p.favourites == ("kernelpanic", "other")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_store_phase2.py -q`
Expected: FAIL. `AttributeError: 'Store' object has no attribute 'add_claim'` (and the related ones).

- [ ] **Step 4: Implement**

Extend `SCHEMA` in `src/dropsminer/store.py`. Add these two lines before the closing `"""`:
```python
CREATE TABLE IF NOT EXISTS claims (at TEXT NOT NULL, campaign_id TEXT NOT NULL, campaign TEXT NOT NULL,
  game TEXT NOT NULL, rewards TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS web_sessions (token_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
```

Add to the imports:
```python
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
```

Add the constants after `EVENT_RETENTION`:
```python
SESSION_TTL = timedelta(days=30)
MIN_PASSWORD = 8
SETTINGS: dict[str, type] = {
    "mine_badges": bool, "claim_points": bool, "notify_target": str,
    "notify_claimed": bool, "notify_needs_you": bool, "notify_signin": bool,
}
SETTING_DEFAULTS = {"mine_badges": False, "claim_points": True, "notify_target": "",
                    "notify_claimed": True, "notify_needs_you": True, "notify_signin": True}
_ph = PasswordHasher()
```

Replace `set_lists` with:
```python
    def set_lists(
        self, priority: Sequence[str], never: Iterable[str], favourites: Sequence[str]
    ) -> None:
        pr = list(dict.fromkeys(priority))
        fv = list(dict.fromkeys(f.strip().lower() for f in favourites if f.strip()))
        with self._db:
            self._db.execute("DELETE FROM priority")
            self._db.execute("DELETE FROM never")
            self._db.execute("DELETE FROM favourites")
            self._db.executemany("INSERT INTO priority VALUES (?, ?)", enumerate(pr))
            self._db.executemany("INSERT INTO never VALUES (?)", [(g,) for g in dict.fromkeys(never)])
            self._db.executemany("INSERT INTO favourites VALUES (?, ?)", enumerate(fv))
```

Replace `get_prefs`'s last line with `return Prefs(pr, nv, fv, self.get_settings()["mine_badges"])`.

Append these methods to `Store`:
```python
    # --- typed settings
    def get_settings(self) -> dict:
        out = dict(SETTING_DEFAULTS)
        for key, kind in SETTINGS.items():
            raw = self.get_setting(key)
            if raw is not None:
                out[key] = (raw == "1") if kind is bool else raw
        return out

    def put_settings(self, values: dict) -> dict:
        for key, value in values.items():
            kind = SETTINGS.get(key)
            if kind is None:
                raise ValueError(f"unknown setting {key!r}")
            if type(value) is not kind:
                raise ValueError(f"{key} must be {kind.__name__}")
        for key, value in values.items():
            self.set_setting(key, ("1" if value else "0") if SETTINGS[key] is bool else value)
        return self.get_settings()

    # --- claims
    def add_claim(self, at: datetime, campaign_id: str, campaign: str, game: str,
                  rewards: list[tuple[str, str]]) -> None:
        payload = json.dumps([{"name": n, "image_url": u} for n, u in rewards])
        with self._db:
            self._db.execute("INSERT INTO claims VALUES (?, ?, ?, ?, ?)",
                             (at.astimezone(UTC).isoformat(), campaign_id, campaign, game, payload))

    def claims_since(self, since: datetime) -> list[dict]:
        rows = self._db.execute(
            "SELECT at, campaign_id, campaign, game, rewards FROM claims WHERE at >= ? ORDER BY at DESC",
            (since.astimezone(UTC).isoformat(),))
        return [{"at": datetime.fromisoformat(at), "campaign_id": cid, "campaign": camp, "game": game,
                 "rewards": json.loads(rw)} for at, cid, camp, game, rw in rows]

    # --- page password (argon2) and web sessions (sha256 of the token only)
    def has_password(self) -> bool:
        return self.get_setting("page_password_hash") is not None

    def set_password(self, plain: str) -> None:
        if len(plain) < MIN_PASSWORD:
            raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
        self.set_setting("page_password_hash", _ph.hash(plain))

    def check_password(self, plain: str) -> bool:
        h = self.get_setting("page_password_hash")
        if h is None:
            return False
        try:
            return _ph.verify(h, plain)
        except VerificationError:
            return False

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_web_session(self, now: datetime) -> str:
        token = secrets.token_urlsafe(32)
        with self._db:
            self._db.execute("INSERT INTO web_sessions VALUES (?, ?)",
                             (self._token_hash(token), (now + SESSION_TTL).astimezone(UTC).isoformat()))
            self._db.execute("DELETE FROM web_sessions WHERE expires_at < ?",
                             (now.astimezone(UTC).isoformat(),))
        return token

    def valid_web_session(self, token: str | None, now: datetime) -> bool:
        if not token:
            return False
        row = self._db.execute("SELECT expires_at FROM web_sessions WHERE token_hash = ?",
                               (self._token_hash(token),)).fetchone()
        return bool(row) and datetime.fromisoformat(row[0]) > now

    def delete_web_session(self, token: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM web_sessions WHERE token_hash = ?", (self._token_hash(token),))
```

- [ ] **Step 5: Run to verify pass, including the phase-1 store tests**

Run: `uv run pytest tests/test_store_phase2.py tests/test_store.py -q && uv run ruff check src tests`
Expected: all pass (`6` new + phase-1 store tests), ruff clean.

> Note: phase 1's `test_mine_badges_setting` sets `"mine_badges"` to `"1"` via `set_setting`. `get_settings` reads it as `True`, so it still passes. Keep it.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/dropsminer/store.py tests/test_store_phase2.py
git commit -m "Store claims, page password, web sessions and typed settings"
```

---

### Task 3: Runner: record claims, emit `refreshed`, clear stale overrides

**Files:**
- Modify: `src/dropsminer/runner.py`
- Test: `tests/test_runner_phase2.py`

**Interfaces:**
- Consumes:
  - `Store.add_claim` (Task 2). The runner's store fakes must accept it, so `FakeStore` gains `add_claim`.
- Produces:
  - Runner emits `("refreshed", {"at": iso})` after every successful refresh.
  - On a successful claim it calls `store.add_claim(now, c.id, c.name, c.game.name, [(r.name, r.image_url) ...])`.
  - `_override_campaign` / `_override_channel` are cleared when the plan no longer honours them.

- [ ] **Step 1: Write the failing tests**

`tests/test_runner_phase2.py`:
```python
from dropsminer.runner import Runner
from test_runner import NOW, FakeClient, FakePubSub, FakeWatcher, camp, chan


class RecStore:
    def __init__(self):
        self.events, self.claims = [], []

    def get_prefs(self):
        from dropsminer.models import Prefs
        return Prefs()

    def log_event(self, kind, data):
        self.events.append((kind, data))

    def add_claim(self, at, campaign_id, campaign, game, rewards):
        self.claims.append((campaign_id, campaign, game, rewards))


def make(client, store=None, emitted=None):
    emitted = [] if emitted is None else emitted
    return Runner(client, FakeWatcher(), FakePubSub(), store or RecStore(), user_id=42,
                  clock=lambda: NOW, emit=lambda k, d: emitted.append((k, d))), emitted


async def test_claim_is_recorded_for_history():
    st = RecStore()
    r, _ = make(FakeClient([camp(cur=60, claim_id="inst")], [chan("a", 7)]), st)
    await r.refresh()
    assert st.claims == [("c1", "Frights", "Palia", [("Palcat Glasses", "")])]


async def test_refreshed_event_after_successful_refresh():
    r, emitted = make(FakeClient([camp()], [chan("a", 7)]))
    await r.refresh()
    assert any(k == "refreshed" for k, _ in emitted)


async def test_stale_campaign_override_is_cleared():
    r, _ = make(FakeClient([camp()], [chan("a", 7)]))
    r.mine_now("gone-campaign")
    await r.refresh()
    assert r._override_campaign is None


async def test_honoured_override_is_kept():
    r, _ = make(FakeClient([camp()], [chan("a", 7), chan("b", 8)]))
    r.use_channel("b")
    await r.refresh()
    assert r.watching.login == "b" and r._override_channel == "b"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_runner_phase2.py -q`
Expected: 3 FAIL (claims not recorded, no `refreshed`, override not cleared); `test_honoured_override_is_kept` passes.

- [ ] **Step 3: Implement**

In `Runner._claim`, after `self._store.log_event("claimed", info)`, add:
```python
            if hasattr(self._store, "add_claim"):
                self._store.add_claim(self._clock(), c.id, c.name, c.game.name,
                                      [(r.name, r.image_url) for r in (d.rewards if d else ())])
```

In `Runner._refresh`, right after `cur = self.plan.current`, add:
```python
        # spec §6: overrides last only while the plan still honours them
        if self._override_campaign and (cur is None or cur.campaign_id != self._override_campaign):
            self._override_campaign = None
        if self._override_channel and (cur is None or cur.channel_login != self._override_channel):
            self._override_channel = None
```

At the end of `_refresh` (after the state is set, before returning), add:
```python
        self._emit("refreshed", {"at": now.isoformat()})
```
Make it the last statement of `_refresh`, so it runs on every successful path, paused included. To do that, change the early `if self._paused: return` into an `if not self._paused:` block around the state-setting `if/elif/else`.

- [ ] **Step 4: Run to verify pass, with the whole suite**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/runner.py tests/test_runner_phase2.py
git commit -m "Runner records claims, emits refreshed, clears stale overrides"
```

---

### Task 4: MinerService (start/stop at runtime); `run` uses it

**Files:**
- Create: `src/dropsminer/service.py`
- Modify: `src/dropsminer/runner.py` (`run_cli` delegates), `src/dropsminer/cli.py` (unchanged call)
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `Runner`, `EventBus`, `Store`, phase-1 Twitch classes.
- Produces:
  - `Parts(runner, pubsub, close: Callable[[], Awaitable[None]])`;
  - `build_parts(store, session, emit) -> Parts`, the real wiring;
  - `MinerService(store, bus, build=build_parts)`, with:
    - `runner: Runner | None`;
    - `running: bool`;
    - `async start() -> bool` (False when there is no Twitch session);
    - `async stop()`;
    - `async wait_stopped()`.

  The loop is: `refresh`, then repeatedly `safe_tick`, sleeping for the value it returns, until the state is `SIGNED_OUT`. Every runner event is logged and published on the bus.

- [ ] **Step 1: Write the failing tests**

`tests/test_service.py`:
```python
import asyncio

from dropsminer.events import EventBus
from dropsminer.runner import Runner, State
from dropsminer.service import MinerService, Parts
from dropsminer.twitch.session import TwitchSession
from test_runner import NOW, FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan

S = TwitchSession("tok", 42, "me", "dev", "cid", "sess")


class SessionStore(FakeStore):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def get_session(self):
        return self.session


def builder(closed):
    def build(store, session, emit):
        r = Runner(FakeClient([camp()], [chan("a", 7)]), FakeWatcher(), FakePubSub(), store,
                   user_id=session.user_id, clock=lambda: NOW, emit=emit)

        async def close():
            closed.append(True)
        return Parts(r, FakePubSub(), close)
    return build


async def test_start_without_session_returns_false():
    svc = MinerService(SessionStore(None), EventBus(), build=builder([]))
    assert await svc.start() is False and svc.runner is None


async def test_start_runs_and_publishes_then_stop_closes():
    closed = []
    bus = EventBus()
    q = bus.subscribe()
    svc = MinerService(SessionStore(S), bus, build=builder(closed))
    assert await svc.start() is True
    kind, data = await asyncio.wait_for(q.get(), 2)
    assert kind == "state" and data["state"] == "mining"
    assert svc.running and svc.runner.state == State.MINING
    await svc.stop()
    assert closed == [True] and not svc.running and svc.runner is None


async def test_start_twice_is_noop():
    svc = MinerService(SessionStore(S), EventBus(), build=builder([]))
    assert await svc.start()
    first = svc.runner
    assert await svc.start()
    assert svc.runner is first
    await svc.stop()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_service.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.service'`

- [ ] **Step 3: Implement**

`src/dropsminer/service.py`:
```python
"""Run the mining loop as a startable/stoppable service (API sign-in starts it, sign-out stops it)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .events import EventBus
from .runner import Runner, State

log = logging.getLogger("dropsminer.service")


@dataclass
class Parts:
    runner: Runner
    pubsub: object
    close: Callable[[], Awaitable[None]]


def build_parts(store, session, emit) -> Parts:
    from .twitch.client import TwitchClient
    from .twitch.gql import Gql
    from .twitch.pubsub import PubSub
    from .twitch.transport import AiohttpTransport
    from .twitch.watch import Watcher

    transport = AiohttpTransport()
    pubsub = PubSub(lambda: session.access_token)
    gql = Gql(transport, lambda: session)
    runner = Runner(TwitchClient(gql, session.user_id), Watcher(transport, lambda: session, gql),
                    pubsub, store, user_id=session.user_id, emit=emit)

    async def close() -> None:
        await pubsub.close()
        await transport.close()
    return Parts(runner, pubsub, close)


class MinerService:
    def __init__(self, store, bus: EventBus, build=build_parts):
        self._store, self._bus, self._build = store, bus, build
        self._parts: Parts | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopped = asyncio.Event()
        self._stopped.set()

    @property
    def runner(self) -> Runner | None:
        return self._parts.runner if self._parts else None

    @property
    def running(self) -> bool:
        return self._parts is not None

    def _emit(self, kind: str, data: dict) -> None:
        log.info("%s %s", kind, data)
        self._bus.publish(kind, data)

    async def start(self) -> bool:
        if self._parts is not None:
            return True
        session = self._store.get_session()
        if session is None:
            return False
        self._parts = self._build(self._store, session, self._emit)
        self._stopped.clear()
        self._tasks = [asyncio.create_task(self._loop()), asyncio.create_task(self._events())]
        return True

    async def _loop(self) -> None:
        r = self._parts.runner
        await r.refresh()
        while r.state != State.SIGNED_OUT:
            delay = await r.safe_tick()
            await asyncio.sleep(delay)
        self._bus.publish("signin", {"status": "expired"})

    async def _events(self) -> None:
        pubsub = self._parts.pubsub
        if not hasattr(pubsub, "events"):
            return
        async for ev in pubsub.events():
            await self._parts.runner.safe_handle(ev)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        if self._parts is not None:
            await self._parts.close()
            self._parts = None
        self._stopped.set()

    async def wait_stopped(self) -> None:
        loop = self._tasks[0] if self._tasks else None
        if loop is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await loop
        await self.stop()
```

Replace `run_cli` in `src/dropsminer/runner.py` with:
```python
async def run_cli(store) -> int:
    """`dropsminer run`: headless mining until Ctrl+C or the Twitch session expires."""
    from .events import EventBus
    from .service import MinerService

    svc = MinerService(store, EventBus())
    if not await svc.start():
        print("Not signed in. Run: dropsminer signin")
        return 1
    try:
        await svc.wait_stopped()
    finally:
        await svc.stop()
    print("Twitch session expired. Run: dropsminer signin")
    return 1
```
Then remove `run_cli`'s now-unused local imports and the module-level `PLAY_INTERVAL` import if ruff reports it unused. `safe_tick` still uses it, so keep it if it is used.

- [ ] **Step 4: Run to verify pass, with the whole suite**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/service.py src/dropsminer/runner.py tests/test_service.py
git commit -m "Add MinerService so mining can start and stop at runtime"
```

---

### Task 5: API models and the state view

**Files:**
- Modify: `pyproject.toml` (add `fastapi>=0.115`, `uvicorn>=0.30`; dev group adds `httpx>=0.27`)
- Create: `src/dropsminer/api/__init__.py`, `src/dropsminer/api/models.py`, `src/dropsminer/api/views.py`
- Test: `tests/test_views.py`

**Interfaces:**
- Consumes: `Runner` attributes (`state`, `plan`, `campaigns`, `live`, `watching`, `paused_until`, `last_refresh`), `Store.get_session`, `Store.get_prefs`, `Store.claims_since`, models.
- Produces:
  - `models`:
    - `RewardOut`, `DropOut`, `CampaignOut`, `ChannelOut`, `CurrentOut`, `StateOut`;
    - `ListsIn` / `ListsOut`;
    - `SettingsIn` / `SettingsOut`;
    - `PasswordIn`, `PauseIn`, `MineNowIn`, `ChannelIn`;
    - `HistoryOut`, `ClaimOut`;
    - `SignInStatus`, `MeOut`, `SuggestionsOut`.
  - `views`:
    - `state_view(runner, store, now) -> StateOut`;
    - `history_view(claims: list[dict]) -> HistoryOut` (flat, newest first: the page groups by the
      viewer's local day, which the server can't know; UTC days would split Nick's evenings);
    - `campaign_out(c, now, verdict) -> CampaignOut`.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add `"fastapi>=0.115", "uvicorn>=0.30",` to `dependencies`, and `"httpx>=0.27"` to the `dev` group. Run `uv sync`.

- [ ] **Step 2: Write the failing tests**

`tests/test_views.py`:
```python
from datetime import timedelta

from dropsminer.api.views import history_view, state_view
from dropsminer.models import Campaign, Drop, Game
from dropsminer.runner import Runner
from test_runner import NOW, FakeClient, FakePubSub, FakeStore, FakeWatcher, camp, chan


class ViewStore(FakeStore):
    def __init__(self, signed_in=True):
        super().__init__()
        self.signed_in = signed_in

    def get_session(self):
        from dropsminer.twitch.session import TwitchSession
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
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_views.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.api'`

- [ ] **Step 4: Implement**

`src/dropsminer/api/__init__.py`:
```python
```

`src/dropsminer/api/models.py`:
```python
"""Request/response models. Field names are the contract phase 3's UI types are generated from."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, StrictBool


class RewardOut(BaseModel):
    name: str
    image_url: str


class DropOut(BaseModel):
    id: str
    name: str
    required_minutes: int
    current_minutes: int
    claimed: bool
    starts_at: datetime
    ends_at: datetime
    rewards: list[RewardOut]


class CampaignOut(BaseModel):
    id: str
    name: str
    game: str
    box_art_url: str
    ends_at: datetime
    linked: bool
    link_url: str
    allowed_channels: list[str]
    minutes_needed: int
    verdict: str | None
    drops: list[DropOut]


class ChannelOut(BaseModel):
    login: str
    viewers: int
    favourite: bool


class CurrentOut(BaseModel):
    campaign: CampaignOut
    channel: ChannelOut
    reason: str
    channel_reason: str
    also_credited: list[str]


class StateOut(BaseModel):
    state: str
    signed_in: bool
    login: str | None
    paused_until: datetime | None
    last_refresh: datetime | None
    current: CurrentOut | None
    needs_you: list[CampaignOut]
    up_next: list[CampaignOut]
    done: list[CampaignOut]


class ListsIn(BaseModel):
    priority: list[str] = Field(default_factory=list, max_length=200)
    never: list[str] = Field(default_factory=list, max_length=200)
    favourites: list[str] = Field(default_factory=list, max_length=200)


class ListsOut(BaseModel):
    priority: list[str]
    never: list[str]
    favourites: list[str]


class SettingsIn(BaseModel):
    # StrictBool: pydantic's lax mode would turn "yes" or 1 into True
    mine_badges: StrictBool | None = None
    claim_points: StrictBool | None = None
    notify_target: str | None = Field(default=None, max_length=500)
    notify_claimed: StrictBool | None = None
    notify_needs_you: StrictBool | None = None
    notify_signin: StrictBool | None = None


class SettingsOut(BaseModel):
    mine_badges: bool
    claim_points: bool
    notify_target: str
    notify_claimed: bool
    notify_needs_you: bool
    notify_signin: bool


class PasswordIn(BaseModel):
    password: str = Field(max_length=200)


class PauseIn(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=1440)


class MineNowIn(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=100)


class ChannelIn(BaseModel):
    login: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_]+$")


class ClaimOut(BaseModel):
    at: datetime
    campaign_id: str
    campaign: str
    game: str
    rewards: list[RewardOut]


class HistoryOut(BaseModel):
    total_rewards: int
    claims: list[ClaimOut]  # newest first; the page groups by the viewer's local day


class SignInStatus(BaseModel):
    status: str  # idle | running | done | failed
    message: str = ""


class MeOut(BaseModel):
    authenticated: bool
    setup_required: bool


class SuggestionsOut(BaseModel):
    games: list[str]
    channels: list[str]
```

`src/dropsminer/api/views.py`:
```python
"""Pure snapshots of runner/store state for the API. No I/O beyond the store reads passed in."""
from __future__ import annotations

from datetime import datetime

from ..models import Campaign, campaign_minutes_needed, campaign_ratio, deadline_verdict
from .models import (
    CampaignOut, ChannelOut, ClaimOut, CurrentOut, DropOut, HistoryOut, RewardOut, StateOut,
)


def campaign_out(c: Campaign, now: datetime, verdict: str | None) -> CampaignOut:
    return CampaignOut(
        id=c.id, name=c.name, game=c.game.name, box_art_url=c.game.box_art_url, ends_at=c.ends_at,
        linked=c.linked, link_url=c.link_url, allowed_channels=list(c.allowed_logins),
        minutes_needed=campaign_minutes_needed(c, now), verdict=verdict,
        drops=[DropOut(id=d.id, name=d.name, required_minutes=d.required_minutes,
                       current_minutes=d.current_minutes, claimed=d.claimed, starts_at=d.starts_at,
                       ends_at=d.ends_at, rewards=[RewardOut(name=r.name, image_url=r.image_url)
                                                   for r in d.rewards])
               for d in c.drops],
    )


def state_view(runner, store, now: datetime) -> StateOut:
    session = store.get_session()
    if runner is None:
        return StateOut(state="signed_out" if session is None else "idle", signed_in=session is not None,
                        login=session.login if session else None, paused_until=None, last_refresh=None,
                        current=None, needs_you=[], up_next=[], done=[])
    by_id = {c.id: c for c in runner.campaigns}
    plan = runner.plan
    verdicts = plan.verdicts if plan else {}

    def out(cid: str):
        c = by_id.get(cid)
        if c is None:
            return None
        v = verdicts.get(cid)
        if v is None and campaign_minutes_needed(c, now) > 0:
            v = deadline_verdict(campaign_ratio(c, now))
        return campaign_out(c, now, v)

    current = None
    if plan and plan.current and runner.watching and (camp := out(plan.current.campaign_id)):
        favs = store.get_prefs().favourites
        w = runner.watching
        current = CurrentOut(
            campaign=camp, channel=ChannelOut(login=w.login, viewers=w.viewers, favourite=w.login in favs),
            reason=plan.current.reason, channel_reason=plan.current.channel_reason,
            also_credited=list(plan.also_credited))
    keep = lambda ids: [o for i in ids if (o := out(i)) is not None]  # noqa: E731
    return StateOut(
        state=str(runner.state), signed_in=session is not None, login=session.login if session else None,
        paused_until=runner.paused_until, last_refresh=runner.last_refresh, current=current,
        needs_you=keep(plan.needs_you if plan else ()), up_next=keep(plan.queue if plan else ()),
        done=keep(plan.done if plan else ()),
    )


def history_view(claims: list[dict]) -> HistoryOut:
    """Flat and newest first. Day grouping is the page's job: only the browser knows the viewer's zone."""
    out = [ClaimOut(at=row["at"], campaign_id=row["campaign_id"], campaign=row["campaign"], game=row["game"],
                    rewards=[RewardOut(**r) for r in row["rewards"]]) for row in claims]
    return HistoryOut(total_rewards=sum(len(c.rewards) for c in out), claims=out)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_views.py -q && uv run ruff check src tests`
Expected: `5 passed`, ruff clean. If ruff reports import ordering, run `uv run ruff check --fix src tests` and re-run.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/dropsminer/api tests/test_views.py
git commit -m "Add API models and pure state/history views"
```

---

### Task 6: App factory and page auth

**Files:**
- Create: `src/dropsminer/api/auth.py`, `src/dropsminer/api/app.py`, `tests/apihelpers.py`
- Test: `tests/test_auth_api.py`

**Interfaces:**
- Consumes:
  - `Store` password and session methods (Task 2);
  - `MinerService` (Task 4; the `service` interface is `runner`, `start`, `stop`, `running`);
  - `EventBus`.
- Produces:
  - `AppContext(store, bus, service, signin, clock)` (dataclass);
  - `create_app(ctx) -> FastAPI`;
  - `COOKIE = "dm_session"`;
  - a `require_session` dependency;
  - `PUBLIC = {"/api/health", "/api/me", "/api/setup", "/api/login"}`.

- [ ] **Step 1: Write the shared test helpers and the failing tests**

`tests/apihelpers.py`:
```python
from datetime import UTC, datetime

import httpx

from dropsminer.api.app import AppContext, create_app
from dropsminer.events import EventBus
from dropsminer.runner import Runner
from dropsminer.store import Store
from test_runner import FakeClient, FakePubSub, FakeWatcher, camp, chan

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


class FakeService:
    def __init__(self, runner=None):
        self.runner, self.started, self.stopped = runner, 0, 0

    @property
    def running(self):
        return self.runner is not None

    async def start(self):
        self.started += 1
        return self.runner is not None

    async def stop(self):
        self.stopped += 1
        self.runner = None


class FakeSignIn:
    def __init__(self):
        self.started = self.cancelled = 0
        self.state = {"status": "idle", "message": ""}

    def status(self):
        return dict(self.state)

    def start(self):
        if self.state["status"] == "running":
            return False
        self.started += 1
        self.state = {"status": "running", "message": ""}
        return True

    def cancel(self):
        self.cancelled += 1


async def runner_with_plan(store):
    r = Runner(FakeClient([camp()], [chan("a", 7), chan("b", 8)]), FakeWatcher(), FakePubSub(), store,
               user_id=42, clock=lambda: NOW)
    await r.refresh()
    return r


def make_app(tmp_path, runner=None, password="correct horse"):
    store = Store(tmp_path / "d.db")
    if password:
        store.set_password(password)
    ctx = AppContext(store=store, bus=EventBus(), service=FakeService(runner), signin=FakeSignIn(),
                     clock=lambda: NOW)
    return create_app(ctx), ctx


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def logged_in(app, password="correct horse"):
    c = client(app)
    r = await c.post("/api/login", json={"password": password})
    assert r.status_code == 204, r.text
    return c
```

`tests/test_auth_api.py`:
```python
from apihelpers import client, logged_in, make_app

PRIVATE = [
    ("GET", "/api/state"), ("GET", "/api/events"), ("POST", "/api/pause"), ("POST", "/api/resume"),
    ("POST", "/api/mine-now"), ("POST", "/api/channel"), ("GET", "/api/lists"), ("PUT", "/api/lists"),
    ("GET", "/api/suggestions"), ("GET", "/api/history"), ("GET", "/api/settings"), ("PUT", "/api/settings"),
    ("POST", "/api/twitch/signin"), ("DELETE", "/api/twitch/signin"), ("GET", "/api/twitch/signin"),
    ("POST", "/api/twitch/signout"), ("POST", "/api/logout"),
]


async def test_every_private_route_requires_session(tmp_path):
    app, _ = make_app(tmp_path)
    async with client(app) as c:
        for method, path in PRIVATE:
            r = await c.request(method, path, json={})
            assert r.status_code == 401, (method, path, r.status_code)


async def test_private_route_list_matches_app_routes(tmp_path):
    # read the schema, not app.routes: FastAPI 0.14x keeps included routers as lazy wrappers
    app, _ = make_app(tmp_path)
    public = {"/api/health", "/api/me", "/api/setup", "/api/login"}
    routes = {(m.upper(), path) for path, ops in app.openapi()["paths"].items() for m in ops}
    assert {x for x in routes if x[1] not in public} == set(PRIVATE)


async def test_me_and_setup_flow(tmp_path):
    app, ctx = make_app(tmp_path, password=None)
    async with client(app) as c:
        assert (await c.get("/api/me")).json() == {"authenticated": False, "setup_required": True}
        assert (await c.post("/api/setup", json={"password": "short"})).status_code == 422
        r = await c.post("/api/setup", json={"password": "correct horse"})
        assert r.status_code == 204 and "dm_session" in r.cookies
        assert (await c.get("/api/me")).json() == {"authenticated": True, "setup_required": False}
        assert (await c.get("/api/state")).status_code == 200


async def test_setup_refused_once_password_exists(tmp_path):
    app, ctx = make_app(tmp_path)
    async with client(app) as c:
        assert (await c.post("/api/setup", json={"password": "attacker pw"})).status_code == 409
    assert ctx.store.check_password("correct horse")


async def test_wrong_password_rejected(tmp_path):
    app, _ = make_app(tmp_path)
    async with client(app) as c:
        r = await c.post("/api/login", json={"password": "nope nope"})
        assert r.status_code == 401 and "dm_session" not in r.cookies


async def test_cookie_flags(tmp_path):
    app, _ = make_app(tmp_path)
    async with client(app) as c:
        r = await c.post("/api/login", json={"password": "correct horse"})
        sc = r.headers["set-cookie"].lower()
        assert "httponly" in sc and "samesite=strict" in sc and "max-age=" in sc


async def test_logout_invalidates_token(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    token = c.cookies["dm_session"]
    assert (await c.post("/api/logout")).status_code == 204
    async with client(app) as other:
        other.cookies.set("dm_session", token)
        assert (await other.get("/api/state")).status_code == 401
    await c.aclose()


async def test_health_is_public(tmp_path):
    app, _ = make_app(tmp_path)
    async with client(app) as c:
        assert (await c.get("/api/health")).json() == {"ok": True}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_auth_api.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.api.app'`

- [ ] **Step 3: Implement `auth.py` and `app.py` with stub routers for the private routes**

The private routes are declared here, so the 401 test can see them. Tasks 7–10 replace each stub body with the real handler.

`src/dropsminer/api/auth.py`:
```python
"""Page password and session cookie (spec §8, plan Global Constraints)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..store import MIN_PASSWORD, SESSION_TTL
from .models import MeOut, PasswordIn

COOKIE = "dm_session"


def _ctx(request: Request):
    return request.app.state.ctx


async def require_session(request: Request) -> None:
    ctx = _ctx(request)
    if not ctx.store.valid_web_session(request.cookies.get(COOKIE), ctx.clock()):
        raise HTTPException(status_code=401, detail="Sign in to this page first.")


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=int(SESSION_TTL.total_seconds()), httponly=True,
                        samesite="strict", secure=False, path="/")


public = APIRouter(prefix="/api")


@public.get("/health")
async def health() -> dict:
    return {"ok": True}


@public.get("/me", response_model=MeOut)
async def me(request: Request) -> MeOut:
    ctx = _ctx(request)
    authed = ctx.store.valid_web_session(request.cookies.get(COOKIE), ctx.clock())
    return MeOut(authenticated=authed, setup_required=not ctx.store.has_password())


@public.post("/setup", status_code=204)
async def setup(body: PasswordIn, request: Request, response: Response) -> None:
    ctx = _ctx(request)
    if ctx.store.has_password():
        raise HTTPException(status_code=409, detail="A page password is already set.")
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"Use at least {MIN_PASSWORD} characters.")
    ctx.store.set_password(body.password)
    _set_cookie(response, ctx.store.create_web_session(ctx.clock()))


@public.post("/login", status_code=204)
async def login(body: PasswordIn, request: Request, response: Response) -> None:
    ctx = _ctx(request)
    if not ctx.store.check_password(body.password):
        await asyncio.sleep(0.5)  # blunt online guessing
        raise HTTPException(status_code=401, detail="Wrong password.")
    _set_cookie(response, ctx.store.create_web_session(ctx.clock()))


private_auth = APIRouter(prefix="/api", dependencies=[Depends(require_session)])


@private_auth.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    ctx = _ctx(request)
    token = request.cookies.get(COOKIE)
    if token:
        ctx.store.delete_web_session(token)
    response.delete_cookie(COOKIE, path="/")
```

`src/dropsminer/api/app.py`:
```python
"""FastAPI application: public auth routes plus the session-protected API (spec §8)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from .auth import private_auth, public, require_session

api = APIRouter(prefix="/api", dependencies=[Depends(require_session)])


@dataclass
class AppContext:
    store: object
    bus: object
    service: object
    signin: object
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


async def _todo() -> None:
    raise HTTPException(status_code=501, detail="Not implemented yet")


for _method, _path in [
    ("GET", "/state"), ("GET", "/events"), ("POST", "/pause"), ("POST", "/resume"), ("POST", "/mine-now"),
    ("POST", "/channel"), ("GET", "/lists"), ("PUT", "/lists"), ("GET", "/suggestions"), ("GET", "/history"),
    ("GET", "/settings"), ("PUT", "/settings"), ("POST", "/twitch/signin"), ("DELETE", "/twitch/signin"),
    ("GET", "/twitch/signin"), ("POST", "/twitch/signout"),
]:
    api.add_api_route(_path, _todo, methods=[_method])


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="Drops Miner", version="0.2.0", docs_url=None, redoc_url=None)
    app.state.ctx = ctx
    app.include_router(public)
    app.include_router(private_auth)
    app.include_router(api)
    return app
```

> Tasks 7–10 delete the stub loop entries as they add real handlers on the same `api` router. By the end of Task 10 the stub loop is gone. `test_private_route_list_matches_app_routes` keeps the 401 coverage exhaustive while that happens.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_auth_api.py -q && uv run ruff check src tests`
Expected: `8 passed`, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/api/auth.py src/dropsminer/api/app.py tests/apihelpers.py tests/test_auth_api.py
git commit -m "Add API app with page password, session cookie and protected route table"
```

---

### Task 7: Read and write data: state, lists, suggestions, settings, history

**Files:**
- Modify: `src/dropsminer/api/app.py`
- Test: `tests/test_api_data.py`

**Interfaces:**
- Consumes: `state_view`, `history_view`, `Store.get_prefs/set_lists/get_settings/put_settings/claims_since`, `ctx.service.runner`.
- Produces: real handlers for:
  - `GET /api/state` → `StateOut`;
  - `GET/PUT /api/lists` → `ListsOut`. PUT returns 422 when a game is in both Priority and Never;
  - `GET /api/suggestions` → `SuggestionsOut`;
  - `GET/PUT /api/settings` → `SettingsOut`;
  - `GET /api/history?days=1..365` (default 30) → `HistoryOut`.

- [ ] **Step 1: Write the failing tests**

`tests/test_api_data.py`:
```python
from datetime import timedelta

from apihelpers import NOW, logged_in, make_app, runner_with_plan


async def test_state_signed_out(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    s = (await c.get("/api/state")).json()
    assert s["state"] == "signed_out" and s["current"] is None
    await c.aclose()


async def test_state_mining(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    c = await logged_in(app)
    s = (await c.get("/api/state")).json()
    assert s["state"] == "mining" and s["current"]["channel"]["login"] in ("a", "b")
    await c.aclose()


async def test_lists_round_trip_and_normalisation(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.put("/api/lists", json={"priority": ["Palia", "Palia"], "never": ["AION 2"],
                                        "favourites": ["KernelPanic"]})
    assert r.status_code == 200
    assert r.json() == {"priority": ["Palia"], "never": ["AION 2"], "favourites": ["kernelpanic"]}
    assert (await c.get("/api/lists")).json() == r.json()
    await c.aclose()


async def test_lists_reject_game_in_priority_and_never(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.put("/api/lists", json={"priority": ["Palia"], "never": ["Palia"], "favourites": []})
    assert r.status_code == 422
    await c.aclose()


async def test_suggestions(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    ctx.store.set_lists([], set(), ["fav_x"])
    c = await logged_in(app)
    s = (await c.get("/api/suggestions")).json()
    assert s == {"games": ["Palia"], "channels": ["a", "b", "fav_x"]}
    await c.aclose()


async def test_settings_partial_update_and_validation(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    r = await c.put("/api/settings", json={"mine_badges": True})
    assert r.status_code == 200 and r.json()["mine_badges"] is True and r.json()["claim_points"] is True
    assert (await c.put("/api/settings", json={"mine_badges": "yes"})).status_code == 422
    await c.aclose()


async def test_history(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.store.add_claim(NOW, "c1", "Frights", "Palia", [("Glasses", "g")])
    ctx.store.add_claim(NOW - timedelta(days=40), "c0", "Old", "X", [("R", "")])
    c = await logged_in(app)
    h = (await c.get("/api/history")).json()
    assert h["total_rewards"] == 1 and h["claims"][0]["campaign"] == "Frights"
    assert (await c.get("/api/history?days=0")).status_code == 422
    assert (await c.get("/api/history?days=60")).json()["total_rewards"] == 2
    await c.aclose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api_data.py -q`
Expected: FAIL. The stub handlers answer 501.

- [ ] **Step 3: Implement**

In `src/dropsminer/api/app.py`:
- remove `("GET", "/state")`, `("GET", "/lists")`, `("PUT", "/lists")`, `("GET", "/suggestions")`, `("GET", "/history")`, `("GET", "/settings")` and `("PUT", "/settings")` from the stub list;
- add these imports and handlers below the stub loop:
```python
from datetime import timedelta

from fastapi import Query, Request

from .models import HistoryOut, ListsIn, ListsOut, SettingsIn, SettingsOut, StateOut, SuggestionsOut
from .views import history_view, state_view


def _c(request: Request) -> AppContext:
    return request.app.state.ctx


@api.get("/state", response_model=StateOut)
async def get_state(request: Request) -> StateOut:
    ctx = _c(request)
    return state_view(ctx.service.runner, ctx.store, ctx.clock())


def _lists(ctx) -> ListsOut:
    p = ctx.store.get_prefs()
    return ListsOut(priority=list(p.priority), never=sorted(p.never), favourites=list(p.favourites))


@api.get("/lists", response_model=ListsOut)
async def get_lists(request: Request) -> ListsOut:
    return _lists(_c(request))


@api.put("/lists", response_model=ListsOut)
async def put_lists(body: ListsIn, request: Request) -> ListsOut:
    clash = set(body.priority) & set(body.never)
    if clash:
        raise HTTPException(status_code=422, detail=f"In both Priority and Never: {', '.join(sorted(clash))}")
    ctx = _c(request)
    ctx.store.set_lists(body.priority, set(body.never), body.favourites)
    return _lists(ctx)


@api.get("/suggestions", response_model=SuggestionsOut)
async def get_suggestions(request: Request) -> SuggestionsOut:
    ctx = _c(request)
    r = ctx.service.runner
    games = sorted({c.game.name for c in r.campaigns}) if r else []
    chans = {ch.login for ch in r.live} if r else set()
    chans |= set(ctx.store.get_prefs().favourites)
    return SuggestionsOut(games=games, channels=sorted(chans))


@api.get("/settings", response_model=SettingsOut)
async def get_settings(request: Request) -> SettingsOut:
    return SettingsOut(**_c(request).store.get_settings())


@api.put("/settings", response_model=SettingsOut)
async def put_settings(body: SettingsIn, request: Request) -> SettingsOut:
    values = body.model_dump(exclude_none=True)
    return SettingsOut(**_c(request).store.put_settings(values))


@api.get("/history", response_model=HistoryOut)
async def get_history(request: Request, days: int = Query(30, ge=1, le=365)) -> HistoryOut:
    ctx = _c(request)
    return history_view(ctx.store.claims_since(ctx.clock() - timedelta(days=days)))
```
Merge the new imports into the existing import block. `Request` and `HTTPException` are already used by the file.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_api_data.py tests/test_auth_api.py -q && uv run ruff check --fix src tests && uv run ruff check src tests`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/api/app.py tests/test_api_data.py
git commit -m "Serve state, lists, suggestions, settings and history"
```

---

### Task 8: Commands: pause, resume, mine-now, channel

**Files:**
- Modify: `src/dropsminer/api/app.py`
- Test: `tests/test_api_commands.py`

**Interfaces:**
- Consumes: `Runner.pause/resume/mine_now/use_channel/refresh`, `PauseIn`, `MineNowIn`, `ChannelIn`.
- Produces:
  - `POST /api/pause {minutes|null}`;
  - `POST /api/resume`;
  - `POST /api/mine-now {campaign_id}`;
  - `POST /api/channel {login}`.

  All of these return 204, or 409 while signed out (there is no runner). mine-now returns 404 for an unknown campaign; channel returns 404 for a channel that isn't live.

- [ ] **Step 1: Write the failing tests**

`tests/test_api_commands.py`:
```python
from datetime import timedelta

from apihelpers import NOW, logged_in, make_app, runner_with_plan


async def test_commands_while_signed_out_conflict(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    for path, body in [("/api/pause", {"minutes": 30}), ("/api/resume", {}),
                       ("/api/mine-now", {"campaign_id": "c1"}), ("/api/channel", {"login": "a"})]:
        assert (await c.post(path, json=body)).status_code == 409, path
    await c.aclose()


async def test_pause_validation_and_effect(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    c = await logged_in(app)
    for bad in (0, -5, 1441):
        assert (await c.post("/api/pause", json={"minutes": bad})).status_code == 422
    assert (await c.post("/api/pause", json={"minutes": 30})).status_code == 204
    assert ctx.service.runner.paused_until == NOW + timedelta(minutes=30)
    assert (await c.post("/api/resume")).status_code == 204
    assert ctx.service.runner.paused_until is None
    assert (await c.post("/api/pause", json={"minutes": None})).status_code == 204
    assert ctx.service.runner.state == "paused" and ctx.service.runner.paused_until is None
    await c.aclose()


async def test_mine_now_unknown_and_known(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    c = await logged_in(app)
    assert (await c.post("/api/mine-now", json={"campaign_id": "nope"})).status_code == 404
    assert (await c.post("/api/mine-now", json={"campaign_id": "c1"})).status_code == 204
    assert ctx.service.runner.plan.current.campaign_id == "c1"
    await c.aclose()


async def test_channel_override(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.service.runner = await runner_with_plan(ctx.store)
    other = "b" if ctx.service.runner.watching.login == "a" else "a"
    c = await logged_in(app)
    assert (await c.post("/api/channel", json={"login": "not live"})).status_code == 422
    assert (await c.post("/api/channel", json={"login": "nobody"})).status_code == 404
    assert (await c.post("/api/channel", json={"login": other.upper()})).status_code == 204
    assert ctx.service.runner.watching.login == other
    await c.aclose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api_commands.py -q`
Expected: FAIL (501s from the stubs).

- [ ] **Step 3: Implement**

In `app.py`:
- remove the `/pause`, `/resume`, `/mine-now` and `/channel` stubs;
- add `ChannelIn`, `MineNowIn`, `PauseIn` to the models import;
- add:
```python
def _runner(ctx):
    r = ctx.service.runner
    if r is None:
        raise HTTPException(status_code=409, detail="Not signed in to Twitch.")
    return r


@api.post("/pause", status_code=204)
async def pause(body: PauseIn, request: Request) -> None:
    ctx = _c(request)
    until = ctx.clock() + timedelta(minutes=body.minutes) if body.minutes else None
    _runner(ctx).pause(until)


@api.post("/resume", status_code=204)
async def resume(request: Request) -> None:
    _runner(_c(request)).resume()


@api.post("/mine-now", status_code=204)
async def mine_now(body: MineNowIn, request: Request) -> None:
    r = _runner(_c(request))
    if not any(c.id == body.campaign_id for c in r.campaigns):
        raise HTTPException(status_code=404, detail="No such campaign.")
    r.mine_now(body.campaign_id)
    await r.refresh()


@api.post("/channel", status_code=204)
async def channel(body: ChannelIn, request: Request) -> None:
    r = _runner(_c(request))
    login = body.login.lower()
    if not any(ch.login == login for ch in r.live):
        raise HTTPException(status_code=404, detail="That channel isn't live with drops right now.")
    r.use_channel(login)
    await r.refresh()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_api_commands.py tests/test_auth_api.py -q && uv run ruff check src tests`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/api/app.py tests/test_api_commands.py
git commit -m "Add pause, resume, mine-now and channel commands"
```

---

### Task 9: Live events (SSE)

**Files:**
- Create: `src/dropsminer/api/sse.py`
- Modify: `src/dropsminer/api/app.py`
- Test: `tests/test_sse.py`

**Interfaces:**
- Consumes: `EventBus` (Task 1).
- Produces:
  - `sse_stream(bus, is_disconnected: Callable[[], Awaitable[bool]], ping: float = 15.0) -> AsyncIterator[str]`. Its first chunk is `": connected\n\n"`; each event is `event: <kind>\ndata: <json>\n\n`; it sends `: ping\n\n` on idle, and unsubscribes on exit;
  - `GET /api/events` (text/event-stream).

- [ ] **Step 1: Write the failing tests**

`tests/test_sse.py`:
```python
import asyncio
import json

from dropsminer.api.sse import sse_stream
from dropsminer.events import EventBus


async def test_stream_formats_events_and_pings():
    bus = EventBus()
    gone = asyncio.Event()

    async def disconnected():
        return gone.is_set()

    gen = sse_stream(bus, disconnected, ping=0.05)
    assert await anext(gen) == ": connected\n\n"
    bus.publish("claimed", {"reward": "Glasses"})
    chunk = await anext(gen)
    head, data = chunk.strip().split("\n")
    assert head == "event: claimed" and json.loads(data[len("data: "):]) == {"reward": "Glasses"}
    assert await asyncio.wait_for(anext(gen), 1) == ": ping\n\n"
    gone.set()
    await gen.aclose()
    assert bus.subscribers == 0


async def test_stream_ends_when_client_disconnects():
    bus = EventBus()

    async def disconnected():
        return True

    chunks = [c async for c in sse_stream(bus, disconnected, ping=0.01)]
    assert chunks == [": connected\n\n"] and bus.subscribers == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_sse.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.api.sse'`

- [ ] **Step 3: Implement**

`src/dropsminer/api/sse.py`:
```python
"""Server-sent events from the EventBus. One bounded queue per client (EventBus drops oldest)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable


async def sse_stream(bus, is_disconnected: Callable[[], Awaitable[bool]],
                     ping: float = 15.0) -> AsyncIterator[str]:
    q = bus.subscribe()
    try:
        yield ": connected\n\n"
        while not await is_disconnected():
            try:
                kind, data = await asyncio.wait_for(q.get(), ping)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
    finally:
        bus.unsubscribe(q)
```

In `app.py`, remove the `/events` stub and add:
```python
from fastapi.responses import StreamingResponse

from .sse import sse_stream


@api.get("/events")
async def events(request: Request) -> StreamingResponse:
    return StreamingResponse(sse_stream(_c(request).bus, request.is_disconnected),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_sse.py tests/test_auth_api.py -q && uv run ruff check src tests`
Expected: all pass, ruff clean. `test_every_private_route_requires_session` still gets 401 on `/api/events`, because the dependency runs before the stream starts.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/api/sse.py src/dropsminer/api/app.py tests/test_sse.py
git commit -m "Stream live runner events over SSE"
```

---

### Task 10: Twitch sign-in and sign-out through the API

**Files:**
- Create: `src/dropsminer/api/signin.py`
- Modify: `src/dropsminer/api/app.py` (remove the last stubs and the stub loop)
- Test: `tests/test_signin_api.py`

**Interfaces:**
- Consumes:
  - `BrowserSignIn` (phase 1; anything with `async sign_in(cancel) -> TwitchSession`);
  - `Store.set_session/clear_session`;
  - `MinerService.start/stop`;
  - `EventBus`.
- Produces:
  - `SignInManager(store, bus, provider_factory: Callable[[], tuple[provider, Callable[[], Awaitable[None]]]], on_signed_in: Callable[[], Awaitable[None]])`, with:
    - `status() -> dict` (`status`: idle|running|done|failed, `message`);
    - `start() -> bool` (False if already running);
    - `cancel() -> None`;
    - `async wait() -> None` (tests).
  - Endpoints:
    - `POST /api/twitch/signin` → 202, or 409 if already running;
    - `GET /api/twitch/signin` → `SignInStatus`;
    - `DELETE /api/twitch/signin` → 204;
    - `POST /api/twitch/signout` → 204: stops the service, clears the session, publishes `signin {status: signed_out}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_signin_api.py`:
```python
import asyncio

from apihelpers import logged_in, make_app
from dropsminer.api.signin import SignInManager
from dropsminer.events import EventBus
from dropsminer.twitch.auth_browser import SignInError
from dropsminer.twitch.session import TwitchSession

S = TwitchSession("tok", 42, "kp", "d", "c", "s")


class Store:
    def __init__(self):
        self.session = None

    def set_session(self, s):
        self.session = s


def factory(result):
    class P:
        async def sign_in(self, cancel):
            if isinstance(result, Exception):
                raise result
            if result == "wait":
                await cancel.wait()
                raise SignInError("Sign-in cancelled.")
            return result

    async def close():
        return None
    return lambda: (P(), close)


async def test_successful_sign_in_saves_session_and_starts_miner():
    started = []

    async def on_signed_in():
        started.append(True)
    bus, st = EventBus(), Store()
    q = bus.subscribe()
    m = SignInManager(st, bus, factory(S), on_signed_in)
    assert m.start() is True
    await m.wait()
    assert st.session == S and started == [True]
    assert m.status() == {"status": "done", "message": "Signed in as kp."}
    assert (await q.get())[0] == "signin"


async def test_failure_reports_message_without_saving():
    st = Store()
    m = SignInManager(st, EventBus(), factory(SignInError("Twitch issued a WEB token.")),
                      lambda: asyncio.sleep(0))
    m.start()
    await m.wait()
    assert st.session is None and m.status() == {"status": "failed", "message": "Twitch issued a WEB token."}


async def test_cancel_and_no_double_start():
    m = SignInManager(Store(), EventBus(), factory("wait"), lambda: asyncio.sleep(0))
    assert m.start() is True and m.start() is False
    m.cancel()
    await m.wait()
    assert m.status()["status"] == "failed" and "cancelled" in m.status()["message"]


async def test_endpoints(tmp_path):
    app, ctx = make_app(tmp_path)
    c = await logged_in(app)
    assert (await c.post("/api/twitch/signin")).status_code == 202
    assert (await c.post("/api/twitch/signin")).status_code == 409
    assert (await c.get("/api/twitch/signin")).json()["status"] == "running"
    assert (await c.delete("/api/twitch/signin")).status_code == 204 and ctx.signin.cancelled == 1
    ctx.store.set_session(S)
    r = await c.post("/api/twitch/signout")
    assert r.status_code == 204 and ctx.store.get_session() is None and ctx.service.stopped == 1
    await c.aclose()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_signin_api.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'dropsminer.api.signin'`

- [ ] **Step 3: Implement**

`src/dropsminer/api/signin.py`:
```python
"""Browser sign-in as a background job the page can start, watch and cancel."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ..twitch.auth_browser import SignInError

log = logging.getLogger("dropsminer.signin")


class SignInManager:
    def __init__(self, store, bus, provider_factory, on_signed_in: Callable[[], Awaitable[None]]):
        self._store, self._bus, self._factory, self._on = store, bus, provider_factory, on_signed_in
        self._state = {"status": "idle", "message": ""}
        self._cancel: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    def status(self) -> dict:
        return dict(self._state)

    def _set(self, status: str, message: str = "") -> None:
        self._state = {"status": status, "message": message}
        self._bus.publish("signin", dict(self._state))

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._cancel = asyncio.Event()
        self._set("running")
        self._task = asyncio.create_task(self._run(self._cancel))
        return True

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    async def wait(self) -> None:
        if self._task is not None:
            await self._task

    async def _run(self, cancel: asyncio.Event) -> None:
        provider, close = self._factory()
        try:
            session = await provider.sign_in(cancel)
        except SignInError as exc:
            self._set("failed", str(exc))
            return
        except Exception as exc:  # noqa: BLE001  never surface browser payloads
            log.exception("Sign-in crashed")
            self._set("failed", f"Sign-in could not run ({type(exc).__name__}).")
            return
        finally:
            await close()
        self._store.set_session(session)
        await self._on()
        self._set("done", f"Signed in as {session.login}.")
```

In `app.py`:
- delete the `_todo` function, the stub list and the stub loop entirely;
- add `SignInStatus` to the models import;
- add:
```python
@api.post("/twitch/signin", status_code=202)
async def signin_start(request: Request) -> None:
    if not _c(request).signin.start():
        raise HTTPException(status_code=409, detail="A sign-in is already running.")


@api.get("/twitch/signin", response_model=SignInStatus)
async def signin_status(request: Request) -> SignInStatus:
    return SignInStatus(**_c(request).signin.status())


@api.delete("/twitch/signin", status_code=204)
async def signin_cancel(request: Request) -> None:
    _c(request).signin.cancel()


@api.post("/twitch/signout", status_code=204)
async def signout(request: Request) -> None:
    ctx = _c(request)
    await ctx.service.stop()
    ctx.store.clear_session()
    ctx.bus.publish("signin", {"status": "signed_out", "message": ""})
```

- [ ] **Step 4: Run to verify pass, with the whole suite**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all pass, including `test_private_route_list_matches_app_routes`, which now matches the real routes. Ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/api/signin.py src/dropsminer/api/app.py tests/test_signin_api.py
git commit -m "Run Twitch sign-in from the API; sign-out stops mining"
```

---

### Task 11: `dropsminer serve`, OpenAPI export

**Files:**
- Modify: `src/dropsminer/cli.py`
- Create: `docs/api/openapi.json` (generated)
- Test: `tests/test_openapi.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `serve(store, host, port) -> int` (async);
  - CLI `dropsminer serve [--host 127.0.0.1] [--port 5810]`;
  - CLI `dropsminer openapi --out docs/api/openapi.json`;
  - `build_app_for_schema() -> FastAPI` (an app with inert context, for schema export and tests).

- [ ] **Step 1: Write the failing test**

`tests/test_openapi.py`:
```python
import json
from pathlib import Path

from dropsminer.cli import build_app_for_schema

COMMITTED = Path(__file__).parent.parent / "docs" / "api" / "openapi.json"


def test_committed_openapi_is_fresh():
    current = build_app_for_schema().openapi()
    assert COMMITTED.exists(), "run: uv run dropsminer openapi --out docs/api/openapi.json"
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == current, \
        "API changed: run `uv run dropsminer openapi --out docs/api/openapi.json` and commit it"


def test_schema_has_every_endpoint():
    paths = build_app_for_schema().openapi()["paths"]
    for p in ("/api/state", "/api/events", "/api/lists", "/api/history", "/api/settings",
              "/api/twitch/signin", "/api/login", "/api/setup"):
        assert p in paths
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_openapi.py -q`
Expected: FAIL, `ImportError: cannot import name 'build_app_for_schema'`

- [ ] **Step 3: Implement**

Add to `src/dropsminer/cli.py`:
```python
import json


def build_app_for_schema():
    from .api.app import AppContext, create_app
    return create_app(AppContext(store=None, bus=None, service=None, signin=None))


async def serve(store: Store, host: str, port: int) -> int:
    import uvicorn

    from .api.app import AppContext, create_app
    from .api.signin import SignInManager
    from .events import EventBus
    from .service import MinerService

    bus = EventBus()
    service = MinerService(store, bus)

    def provider():
        t = AiohttpTransport()
        return BrowserSignIn(t, report=lambda m: logging.getLogger("dropsminer.signin").info(m)), t.close

    async def on_signed_in() -> None:
        await service.stop()
        await service.start()

    signin = SignInManager(store, bus, provider, on_signed_in)
    app = create_app(AppContext(store=store, bus=bus, service=service, signin=signin))
    started = await service.start()
    logging.getLogger("dropsminer").info(
        "Serving on http://%s:%s (%s)", host, port, "mining" if started else "not signed in to Twitch")
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False))
    try:
        await server.serve()
    finally:
        await service.stop()
    return 0
```

In `main()`:
- add these subparsers:
```python
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=5810)
    oa = sub.add_parser("openapi")
    oa.add_argument("--out", type=Path, default=Path("docs/api/openapi.json"))
```
- add these dispatch branches before `return 2`:
```python
    if args.cmd == "serve":
        return asyncio.run(serve(store, args.host, args.port))
    if args.cmd == "openapi":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(build_app_for_schema().openapi(), indent=1, sort_keys=True) + "\n"
        args.out.write_bytes(text.encode("utf-8"))
        print(f"wrote {args.out}")
        return 0
```

Then generate the schema: `uv run dropsminer openapi --out docs/api/openapi.json`

- [ ] **Step 4: Run to verify pass, with the whole suite**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/dropsminer/cli.py docs/api/openapi.json tests/test_openapi.py
git commit -m "Add serve command (miner + API) and committed OpenAPI schema"
```

---

### Task 12: Phase gate: mutation check, review, live gate

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Mutation-check the auth gate**

Use the `mutation-check` skill on `src/dropsminer/api/auth.py` and `src/dropsminer/store.py` (session/password methods), with `tests/test_auth_api.py` and `tests/test_store_phase2.py`. At minimum these mutants must be killed:
- `require_session` always passes;
- `valid_web_session` ignores expiry;
- `setup` skips the `has_password` check;
- `check_password` returns True on any error;
- `delete_web_session` does nothing.

Commit any new tests.

- [ ] **Step 2: Whole-phase code review**

Run a fresh-reviewer review of `git diff <phase-2 base>..HEAD -- src tests`, using the `superpowers:requesting-code-review` skill. Use the plan's Review Focus as its checklist. Fix Critical and Important findings test-first.

- [ ] **Step 3: LIVE GATE (needs the PC; Nick only if sign-in is needed)**

1. Stop the phase-1 `dropsminer run` process. Find it with PowerShell `Get-CimInstance Win32_Process | ? CommandLine -match 'dropsminer.exe" run'` and stop that PID only. Confirm it's gone.
2. `uv run dropsminer serve` (127.0.0.1:5810). The log must say "mining", because the session is saved from phase 1.
3. Use a temporary page password, removed afterwards with `uv run python -c "..."` deleting the `page_password_hash` setting, or keep it if Nick wants it. Check with `curl`:
   - `GET /api/me` → `setup_required: true`;
   - `POST /api/setup` → cookie;
   - `GET /api/state` → `state: mining`, with the current campaign matching the log's channel;
   - `GET /api/events` streamed for 3 minutes shows `progress` events;
   - `GET /api/history` lists claims made after the server started (if any). Earlier claims are not in the claims table, because it's new in phase 2.
4. Without a cookie, `GET /api/state` → 401.
5. `POST /api/pause {"minutes": 1}`, then confirm heartbeats stop (no progress for 1 minute) and resume after it.
6. Leave `serve` running as the miner. It replaces `run`.

- [ ] **Step 4: Record and commit**

Add a "Phase 2 live check" section to `README.md` with the date and what each step showed:
```bash
git add README.md
git commit -m "Record phase 2 live check"
```

- [ ] **Step 5: Report to Nick**

Report:
- what passed;
- that the API runs on `http://127.0.0.1:5810` (localhost only until phase 5);
- that phase 3 (mockup round for the first-run and sign-in screens, then the UI) is next.
