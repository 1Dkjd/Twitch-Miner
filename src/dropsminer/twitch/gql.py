"""GQL persisted-query client. Retry rules ported from reference twitch.py gql_request."""
from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .constants import ANDROID_APP, GQL_BATCH, GQL_OPS, GQL_URL, ClientInfo
from .session import TwitchSession, gql_headers
from .transport import HttpTransport

log = logging.getLogger("dropsminer.gql")
RETRY_ONCE = {"service error", "PersistedQueryNotFound"}
NETWORK_TRIES = 3


class GqlError(Exception):
    pass


class AuthExpired(GqlError):
    pass


class TwitchUnreachable(GqlError):
    pass


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def op(key: str, **variables: Any) -> dict:
    name, sha, defaults = GQL_OPS[key]
    return {
        "operationName": name,
        "variables": _merge(defaults, variables),
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha}},
    }


class Gql:
    def __init__(
        self,
        transport: HttpTransport,
        session: Callable[[], TwitchSession],
        client: ClientInfo = ANDROID_APP,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._t, self._session, self._client, self._sleep = transport, session, client, sleep

    async def run(self, payload: dict) -> dict:
        return (await self._post(payload))

    async def run_many(self, payloads: list[dict]) -> list[dict]:
        chunks = [payloads[i:i + GQL_BATCH] for i in range(0, len(payloads), GQL_BATCH)]
        results = await asyncio.gather(*(self._post(c) for c in chunks))
        return [item for chunk in results for item in chunk]

    async def _post(self, body: dict | list) -> Any:
        retried = False
        delay = 1.0
        failures = 0
        while True:
            try:
                r = await self._t.request(
                    "POST", GQL_URL, headers=gql_headers(self._session(), self._client), json=body
                )
            except (OSError, TimeoutError, aiohttp.ClientError) as exc:
                failures += 1
                log.warning("GQL network error (%s), try %d", type(exc).__name__, failures)
                if failures >= NETWORK_TRIES:
                    raise TwitchUnreachable(type(exc).__name__) from None
                await self._sleep(delay)
                delay = min(delay * 2, 60)
                continue
            if r.status == 401:
                raise AuthExpired("Twitch rejected the session (401)")
            if r.status >= 500:
                failures += 1
                if failures >= NETWORK_TRIES:
                    raise TwitchUnreachable(f"HTTP {r.status}")
                await self._sleep(delay)
                delay = min(delay * 2, 60)
                continue
            data = r.json()
            items = data if isinstance(data, list) else [data]
            messages = [e.get("message", "") for i in items for e in (i.get("errors") or [])]
            if messages:
                if not retried and RETRY_ONCE.intersection(messages):
                    retried = True
                    await self._sleep(5)
                    continue
                raise GqlError("; ".join(messages))
            return data
