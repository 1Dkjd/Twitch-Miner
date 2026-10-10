"""FastAPI application: public auth routes plus the session-protected API (spec §8)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..runner import State
from .auth import private_auth, public, require_session
from .models import (
    ChannelIn,
    ChannelSuggestion,
    HistoryOut,
    ListsIn,
    ListsOut,
    MineNowIn,
    PauseIn,
    SettingsIn,
    SettingsOut,
    SignInStatus,
    StateOut,
    SuggestionsOut,
)
from .sse import sse_stream
from .views import history_view, state_view

api = APIRouter(prefix="/api", dependencies=[Depends(require_session)])


@dataclass
class AppContext:
    store: object
    bus: object
    service: object
    signin: object
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)




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
    if ctx.service.runner is not None:
        await ctx.service.runner.replan()  # takes effect now, not at the next 5-minute refresh
    return _lists(ctx)


@api.get("/suggestions", response_model=SuggestionsOut)
async def get_suggestions(request: Request) -> SuggestionsOut:
    ctx = _c(request)
    r = ctx.service.runner
    games = sorted({c.game.name for c in r.campaigns}) if r else []
    live = {ch.login: ch.game_name or None for ch in r.live} if r else {}
    seen = {row["login"]: row for row in ctx.store.seen_channels(ctx.clock())}
    out = [ChannelSuggestion(login=lg, live=True, game=g, last_seen=seen.get(lg, {}).get("last_seen"))
           for lg, g in sorted(live.items())]
    favs = ctx.store.get_prefs().favourites
    offline = [lg for lg in seen if lg not in live]  # newest first
    keep = set(offline[:SEEN_SUGGESTIONS]) | set(favs)  # a long tail of offline channels isn't useful
    out += [ChannelSuggestion(login=lg, live=False, game=seen[lg]["game"] or None,
                              last_seen=seen[lg]["last_seen"]) for lg in offline if lg in keep]
    known = {c.login for c in out}
    out += [ChannelSuggestion(login=f, live=False, game=None, last_seen=None) for f in favs if f not in known]
    return SuggestionsOut(games=games, channels=out)


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


def _runner(ctx):
    r = ctx.service.runner
    if r is None or r.state == State.SIGNED_OUT:
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
    await r.replan()
    if not (r.plan and r.plan.current and r.plan.current.campaign_id == body.campaign_id):
        raise HTTPException(status_code=409, detail="Can't mine that campaign right now: it needs a linked "
                            "account, a live channel, or it's on your Never list.")


@api.post("/channel", status_code=204)
async def channel(body: ChannelIn, request: Request) -> None:
    r = _runner(_c(request))
    login = body.login.lower()
    if not any(ch.login == login for ch in r.live):
        raise HTTPException(status_code=404, detail="That channel isn't live with drops right now.")
    r.use_channel(login)
    await r.replan()
    if not (r.watching and r.watching.login == login):
        raise HTTPException(status_code=409, detail="That channel can't earn the campaign being mined.")


@api.get("/events")
async def events(request: Request) -> StreamingResponse:
    return StreamingResponse(sse_stream(_c(request).bus, request.is_disconnected),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@api.post("/refresh", status_code=204)
async def check_now(request: Request) -> None:
    """The idle card's "Check now": re-read campaigns and live channels immediately."""
    await _runner(_c(request)).refresh(force_campaigns=True)


@api.post("/twitch/signin", status_code=202, response_model=SignInStatus)
async def signin_start(request: Request) -> SignInStatus:
    status = await _c(request).signin.start()
    if status is None:
        raise HTTPException(status_code=409, detail="A sign-in is already waiting for its code.")
    return SignInStatus(**status)


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
    ctx.signin.reset()
    ctx.bus.publish("signin", {"status": "signed_out", "message": ""})


def create_app(ctx: AppContext, web_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Dropwatch", version="0.3.0", docs_url=None, redoc_url=None)
    app.state.ctx = ctx
    app.include_router(public)
    app.include_router(private_auth)
    app.include_router(api)
    if web_dir is not None and (web_dir / "index.html").is_file():
        _serve_web(app, web_dir)
    return app


SEEN_SUGGESTIONS = 300  # offline channels offered in the favourites add box (most recent first)
NO_CACHE = {"Cache-Control": "no-cache"}  # a rebuilt page must not be served from a stale cache


def _serve_web(app: FastAPI, web_dir: Path) -> None:
    """The built page (web/dist): its assets, and index.html for every other non-API path."""
    if (web_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")
    index = web_dir / "index.html"
    root = web_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def page(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        # never hand a network path (\host\share, //host, c:) to the filesystem: on Windows that
        # would open an SMB connection to whoever named it
        if not path or path.startswith("/") or "\\" in path or ":" in path:
            return FileResponse(index, headers=NO_CACHE)
        # all handlers stay async (one event loop owns the store and runner); these checks are on
        # small local files, so the blocking cost is negligible
        f = (web_dir / path).resolve()  # noqa: ASYNC240
        if f.is_relative_to(root) and f.is_file():  # noqa: ASYNC240
            return FileResponse(f)
        return FileResponse(index, headers=NO_CACHE)
