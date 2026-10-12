"""Page password and session cookie (spec §8, plan Global Constraints)."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..store import MIN_PASSWORD, SESSION_TTL, Store
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


LOGIN_TRIES = 5  # wrong passwords from one address...
LOGIN_WINDOW = timedelta(minutes=15)  # ...within this long, and that address waits out the window


class LoginLimiter:
    """Counts wrong page passwords per client address. In memory: a restart forgets, which is fine
    for a LAN page (the attacker can't restart it)."""

    def __init__(self) -> None:
        self._fails: dict[str, deque[datetime]] = {}

    def _recent(self, who: str, now: datetime) -> deque[datetime]:
        q = self._fails.get(who, deque())
        while q and now - q[0] >= LOGIN_WINDOW:
            q.popleft()
        return q

    def wait(self, who: str, now: datetime) -> int:
        """Seconds this address must wait before trying again (0 = go ahead)."""
        q = self._recent(who, now)
        if len(q) < LOGIN_TRIES:
            return 0
        return max(1, int((q[0] + LOGIN_WINDOW - now).total_seconds()) + 1)

    def failed(self, who: str, now: datetime) -> None:
        q = self._recent(who, now)
        q.append(now)
        self._fails[who] = q
        if len(self._fails) > 1000:  # forget addresses whose window has passed
            self._fails = {k: v for k, v in self._fails.items() if self._recent(k, now)}

    def succeeded(self, who: str) -> None:
        self._fails.pop(who, None)


def _who(request: Request) -> str:
    return request.client.host if request.client else "?"


public = APIRouter(prefix="/api")


@public.get("/health")
async def health() -> dict:
    return {"ok": True}


@public.get("/health/miner")
async def miner_health(request: Request, response: Response) -> dict:
    """Docker's health check, open without sign-in, so it says only ok or not (the reason is logged): 503
    when mining crashed or stopped ticking. Signed out, paused or idle are healthy."""
    from ..maintenance import miner_health
    ctx = _ctx(request)
    ok, why = miner_health(ctx.service, ctx.clock())
    if not ok:
        logging.getLogger("dropwatch").warning("Health check: %s", why)
        response.status_code = 503
    return {"ok": ok}


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
    _set_cookie(response, ctx.store.create_web_session(ctx.clock(), request.headers.get("user-agent", "")))


@public.post("/login", status_code=204)
async def login(body: PasswordIn, request: Request, response: Response) -> None:
    ctx = _ctx(request)
    limiter: LoginLimiter = request.app.state.login_limiter
    who, now = _who(request), ctx.clock()
    if wait := limiter.wait(who, now):
        minutes = -(-wait // 60)
        raise HTTPException(status_code=429, headers={"Retry-After": str(wait)},
                            detail=f"Too many wrong passwords. Try again in {minutes} min.")
    # argon2 is slow by design: verify in a worker thread so the miner and other requests keep going;
    # the hash is read here, on the loop, because the database connection belongs to this thread
    h = ctx.store.password_hash()
    if h is None or not await asyncio.to_thread(Store.verify_password, h, body.password):
        limiter.failed(who, now)
        await asyncio.sleep(0.5)  # blunt online guessing
        raise HTTPException(status_code=401, detail="Wrong password.")
    limiter.succeeded(who)
    _set_cookie(response, ctx.store.create_web_session(ctx.clock(), request.headers.get("user-agent", "")))


private_auth = APIRouter(prefix="/api", dependencies=[Depends(require_session)])


@private_auth.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    ctx = _ctx(request)
    token = request.cookies.get(COOKIE)
    if token:
        ctx.store.delete_web_session(token)
    response.delete_cookie(COOKIE, path="/")
