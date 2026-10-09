# Drops Miner (private)

Phase 1: headless miner. See `docs/superpowers/specs/` for the design.

    uv sync
    uv run dropsminer signin      # opens a browser; sign in to Twitch
    uv run dropsminer lists --priority "Palia,Phasmophobia"
    uv run dropsminer run

Data (SQLite + session) lives in `./data` unless `DROPSMINER_DATA` is set.
Stop any other miner on the same Twitch account first.

## Phase 1 live run (2026-10-09)

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
