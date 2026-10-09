# Drops Miner (private)

Phase 1: headless miner. See `docs/superpowers/specs/` for the design.

    uv sync
    uv run dropsminer signin      # opens a browser; sign in to Twitch
    uv run dropsminer lists --priority "Palia,Phasmophobia"
    uv run dropsminer run

Data (SQLite + session) lives in `./data` unless `DROPSMINER_DATA` is set.
Stop any other miner on the same Twitch account first.
