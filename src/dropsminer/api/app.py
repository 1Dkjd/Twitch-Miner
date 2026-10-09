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
