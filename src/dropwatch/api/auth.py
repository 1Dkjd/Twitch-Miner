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
