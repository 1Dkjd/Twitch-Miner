from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from .redact import RedactFilter
from .store import Store
from .twitch.auth_browser import BrowserSignIn, SignInError
from .twitch.auth_device import DeviceCodeSignIn
from .twitch.capture import run_capture
from .twitch.gql import Gql
from .twitch.transport import AiohttpTransport


def data_dir() -> Path:
    return Path(os.environ.get("DROPWATCH_DATA", "data"))


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def setup_logging(store: Store) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter(lambda: [s.access_token] if (s := store.get_session()) else []))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


async def cmd_signin(store: Store, *, browser: bool = False, provider=None) -> int:
    """Default: Twitch's TV code sign-in. --browser: the phase-1 browser sign-in (PC fallback)."""
    t = AiohttpTransport()
    try:
        if browser:
            session = await BrowserSignIn(t).sign_in(asyncio.Event())
        else:
            p = provider or DeviceCodeSignIn(t)
            code = await p.start()
            minutes = max(1, round((code.expires_at - datetime.now(UTC)).total_seconds() / 60))
            print(f"Go to {code.verification_uri} on any device and enter the code {code.user_code}")
            print(f"(it works for about {minutes} minutes). Waiting for you to click Authorize...")
            session = await p.wait(code, asyncio.Event())
    except SignInError as exc:
        print(f"Sign-in failed: {exc}")
        return 1
    finally:
        await t.close()
    store.set_session(session)
    print(f"Saved session for {session.login}.")
    return 0


async def cmd_capture(store: Store, out: Path) -> int:
    s = store.get_session()
    if s is None:
        print("Not signed in. Run: dropwatch signin")
        return 1
    t = AiohttpTransport()
    try:
        for p in await run_capture(Gql(t, lambda: s), t, s, out):
            print(f"wrote {p}")
    finally:
        await t.close()
    return 0


def cmd_lists(store: Store, args: argparse.Namespace) -> int:
    p = store.get_prefs()
    if not args.show:
        store.set_lists(
            _csv(args.priority) if args.priority is not None else list(p.priority),
            set(_csv(args.never)) if args.never is not None else set(p.never),
            _csv(args.favourites) if args.favourites is not None else list(p.favourites),
        )
        p = store.get_prefs()
    print(f"Priority:   {', '.join(p.priority) or '-'}")
    print(f"Never:      {', '.join(sorted(p.never)) or '-'}")
    print(f"Favourites: {', '.join(p.favourites) or '-'}")
    return 0


def build_app_for_schema():
    from .api.app import AppContext, create_app
    return create_app(AppContext(store=None, bus=None, service=None, signin=None))


def server_config(app, host: str, port: int):
    import uvicorn

    return uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False)


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
        return DeviceCodeSignIn(t), t.close

    async def on_signed_in() -> None:
        await service.stop()
        await service.start()

    signin = SignInManager(store, bus, provider, on_signed_in)
    app = create_app(AppContext(store=store, bus=bus, service=service, signin=signin))
    started = await service.start()
    logging.getLogger("dropwatch").info(
        "Serving on http://%s:%s (%s)", host, port, "mining" if started else "not signed in to Twitch")
    server = uvicorn.Server(server_config(app, host, port))
    try:
        await server.serve()
    finally:
        await service.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dropwatch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    si = sub.add_parser("signin")
    si.add_argument("--browser", action="store_true", help="sign in through a browser window (PC fallback)")
    cap = sub.add_parser("capture")
    cap.add_argument("--out", type=Path, default=Path("tests/fixtures"))
    ls = sub.add_parser("lists")
    ls.add_argument("--priority")
    ls.add_argument("--never")
    ls.add_argument("--favourites")
    ls.add_argument("--show", action="store_true")
    sub.add_parser("run")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=5810)
    oa = sub.add_parser("openapi")
    oa.add_argument("--out", type=Path, default=Path("docs/api/openapi.json"))
    args = ap.parse_args(argv)
    store = Store(data_dir() / "drops.db")
    setup_logging(store)
    if args.cmd == "signin":
        return asyncio.run(cmd_signin(store, browser=args.browser))
    if args.cmd == "capture":
        return asyncio.run(cmd_capture(store, args.out))
    if args.cmd == "lists":
        return cmd_lists(store, args)
    if args.cmd == "run":
        from .runner import run_cli  # added in Task 11
        return asyncio.run(run_cli(store))
    if args.cmd == "serve":
        return asyncio.run(serve(store, args.host, args.port))
    if args.cmd == "openapi":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(build_app_for_schema().openapi(), indent=1, sort_keys=True) + "\n"
        args.out.write_bytes(text.encode("utf-8"))
        print(f"wrote {args.out}")
        return 0
    return 2
