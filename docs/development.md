# Developing Dropwatch

## Layout

- `src/dropwatch/`: the miner (Python 3.12, FastAPI, SQLite). `planner.py` decides what to mine, `runner.py` runs it, `api/` serves the dashboard.
- `web/`: the dashboard (React, TypeScript, Vite).
- `docs/design/`: the approved mockups each screen was built from. `docs/superpowers/`: the original design spec and plans.
- `reference/`: the MIT-licensed projects the Twitch protocol code was ported from, kept unmodified (see `NOTICE`). Not used at runtime.
- `brand/`: the logo in every size (its README says which file goes where).

## Running it locally

```
uv sync
cd web && npm ci && npm run build && cd ..
uv run dropwatch serve          # http://localhost:5810
```

Data lives in `./data` unless `DROPWATCH_DATA` is set. Stop any other miner on the same Twitch account first.

## Tests and checks

```
uv run pytest -q
uv run ruff check src tests
cd web && npx tsc --noEmit && npm test
```

After changing the API: `uv run dropwatch openapi --out docs/api/openapi.json`, then `npm run gen:api` in `web/`.

## Releasing

1. Bump `version` in `pyproject.toml`, run `uv lock`, then regenerate the API schema (`uv run dropwatch openapi --out docs/api/openapi.json`); its test fails otherwise.
2. Add the release to the top of `<Changes>` in `unraid/dropwatch.xml`. Community Applications shows it on the listing. Say what the release does for users, newest first.
3. Push a tag like `v0.2.0`. The `docker` workflow tests, then publishes `ghcr.io/kernelpanic-studios/dropwatch:<version>` and `:latest`.

## Early live runs (2026-10-09)

The notes below are from the first live tests of the headless miner and the API, kept for the record.

### Phase 1 live run (2026-10-09)

Account: the owner's Twitch account. The old dungfu container was stopped by name for the whole test.
Priority list: Palia, Phasmophobia.

| Run | Window (UTC) | Result |
|---|---|---|
| 1 | 05:32–05:58 | Spade-only heartbeats returned 204 but earned nothing: Palia stayed at 22 min. |
| 2 | 05:58–06:13 | Timestamp format fixed to match the reference. Still nothing earned. Upstream DevilXD#1183 shows Twitch now needs simulated playback. |
| 3 | 06:16–08:16 (2 h) | Simulated HLS playback (`327fc68`). Palia went from 22 to 138 min. 3 channel switches, no errors. |
| Restart | 08:17 | Stopped and restarted on `4c12b0d`. It resumed mining with no sign-in prompt, and progress arrived in 20 s. |

Run 3 claimed 10× Ectoplasm and 5× Tattered Cloth (Frights & Delights) at 07:19:54. Twitch's inventory confirms `isClaimed: true`.

Twitch never sent the PubSub drop-claim message, so the claim waited 25 minutes for the hourly fetch. `4c12b0d` now re-fetches at the next 5-minute refresh. That path is unit-tested only so far.

### Phase 2 live check (2026-10-09)

`dropwatch serve` (branch `phase2-api`, `58077a7`) took over from the phase-1 `run` process on the saved session at 19:11. Bound to 127.0.0.1:5810.

| Check | Result |
|---|---|
| Start | `Serving … (mining)`, then the first refresh 3 s later; no sign-in prompt. |
| `GET /api/me` before setup | `setup_required: true` |
| `GET /api/state` without the cookie | 401 (`/api/history` too) |
| `POST /api/setup`, then again | 204 with cookie; the second gets 409 |
| `GET /api/state` | `mining`: Escape from Tarkov "EXFIL Brothers Day 1" on lvndmark, drops at 358 min, 85 needs-you / 3 up next / 4 done. Matched the log. |
| `GET /api/events` for 4 min | `progress` 359 → 360, keepalive pings every 15 s |
| `POST /api/pause` `{"minutes": 0}` / `{"minutes": 1}` | 422 / 204. The state went to `paused` with `paused_until`, then back to `mining` by itself 66 s later. |
| Live claim | "Common 3" claimed at 19:17:18. It was in `GET /api/history` with its image and a UTC `Z` timestamp. |

The temporary page password and its session were removed afterwards, so phase 3's first run asks for a new one.

Not checked live:
- Ctrl+C with an open event stream. A real-server test covers it (shutdown in 0.5 s).
- Sign-in and sign-out through the API.
- Session expiry. The unit tests cover it.
