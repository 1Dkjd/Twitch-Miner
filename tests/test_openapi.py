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
