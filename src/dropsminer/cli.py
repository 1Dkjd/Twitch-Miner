from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from .redact import RedactFilter
from .store import Store
from .twitch.auth_browser import BrowserSignIn, SignInError
from .twitch.capture import run_capture
from .twitch.gql import Gql
from .twitch.transport import AiohttpTransport


def data_dir() -> Path:
    return Path(os.environ.get("DROPSMINER_DATA", "data"))


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def setup_logging(store: Store) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter(lambda: [s.access_token] if (s := store.get_session()) else []))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


async def cmd_signin(store: Store) -> int:
    t = AiohttpTransport()
    try:
        session = await BrowserSignIn(t).sign_in(asyncio.Event())
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
        print("Not signed in. Run: dropsminer signin")
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dropsminer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("signin")
    cap = sub.add_parser("capture")
    cap.add_argument("--out", type=Path, default=Path("tests/fixtures"))
    ls = sub.add_parser("lists")
    ls.add_argument("--priority")
    ls.add_argument("--never")
    ls.add_argument("--favourites")
    ls.add_argument("--show", action="store_true")
    sub.add_parser("run")
    args = ap.parse_args(argv)
    store = Store(data_dir() / "drops.db")
    setup_logging(store)
    if args.cmd == "signin":
        return asyncio.run(cmd_signin(store))
    if args.cmd == "capture":
        return asyncio.run(cmd_capture(store, args.out))
    if args.cmd == "lists":
        return cmd_lists(store, args)
    if args.cmd == "run":
        from .runner import run_cli  # added in Task 11
        return asyncio.run(run_cli(store))
    return 2
