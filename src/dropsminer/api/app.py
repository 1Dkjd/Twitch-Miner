"""FastAPI application: public auth routes plus the session-protected API (spec §8)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request

from .auth import private_auth, public, require_session
from .models import HistoryOut, ListsIn, ListsOut, SettingsIn, SettingsOut, StateOut, SuggestionsOut
from .views import history_view, state_view

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
    ("GET", "/events"), ("POST", "/pause"), ("POST", "/resume"), ("POST", "/mine-now"),
    ("POST", "/channel"), ("POST", "/twitch/signin"), ("DELETE", "/twitch/signin"),
    ("GET", "/twitch/signin"), ("POST", "/twitch/signout"),
]:
    api.add_api_route(_path, _todo, methods=[_method])


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


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="Drops Miner", version="0.2.0", docs_url=None, redoc_url=None)
    app.state.ctx = ctx
    app.include_router(public)
    app.include_router(private_auth)
    app.include_router(api)
    return app
