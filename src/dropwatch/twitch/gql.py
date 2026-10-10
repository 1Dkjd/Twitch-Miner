"""GQL persisted-query client.

Retry behaviour follows reference twitch.py gql_request (lines 1298-1374):
- transient GQL error messages are retried with backoff;
- a top-level "error" body is a hard error;
- 429/5xx and network errors are retried a few times.

Two differences from the reference, both deliberate:
- we give up after a few tries and raise, so the runner can report an outage and back off;
- a partial "server error" response is retried, not accepted with holes.

Requests are rate-limited to 5 per second (reference RateLimiter(capacity=5, window=1)).
"""
from __future__ import annotations

import asyncio
import collections
import copy
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .constants import GQL_BATCH, GQL_OPS, GQL_URL, ClientInfo, client_for
from .session import TwitchSession, gql_headers
from .transport import HttpTransport

log = logging.getLogger("dropwatch.gql")
RETRYABLE = {
    "service error", "PersistedQueryNotFound", "service timeout", "request cancelled",
    "service unavailable", "context deadline exceeded", "server error",
}
TRIES = 3
RATE_CAPACITY, RATE_WINDOW = 5, 1.0


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
        client: ClientInfo | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._t, self._session, self._client = transport, session, client
        self._sleep, self._clock = sleep, clock
        self._stamps: collections.deque[float] = collections.deque()
        self._rate_lock = asyncio.Lock()

    async def run(self, payload: dict) -> dict:
        return await self._post(payload)

    async def run_many(self, payloads: list[dict]) -> list[dict]:
        chunks = [payloads[i:i + GQL_BATCH] for i in range(0, len(payloads), GQL_BATCH)]
        results = await asyncio.gather(*(self._post(c) for c in chunks))
        return [item for chunk in results for item in chunk]

    async def _throttle(self) -> None:
        async with self._rate_lock:
            while True:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= RATE_WINDOW:
                    self._stamps.popleft()
                if len(self._stamps) < RATE_CAPACITY:
                    self._stamps.append(now)
                    return
                await self._sleep(RATE_WINDOW - (now - self._stamps[0]))

    def _headers(self) -> dict[str, str]:
        s = self._session()
        return gql_headers(s, self._client or client_for(s.client_id))  # None: the session's own client

    async def _post(self, body: dict | list) -> Any:
        delay = 1.0
        failures = 0
        gql_retries = 0
        while True:
            await self._throttle()
            try:
                r = await self._t.request(
                    "POST", GQL_URL, headers=self._headers(), json=body
                )
            except (OSError, TimeoutError, aiohttp.ClientError) as exc:
                failures += 1
                log.warning("GQL network error (%s), try %d", type(exc).__name__, failures)
                if failures >= TRIES:
                    raise TwitchUnreachable(type(exc).__name__) from None
                await self._sleep(delay)
                delay = min(delay * 2, 60)
                continue
            if r.status == 401:
                raise AuthExpired("Twitch rejected the session (401)")
            if r.status == 429 or r.status >= 500:
                failures += 1
                log.warning("GQL HTTP %s, try %d", r.status, failures)
                if failures >= TRIES:
                    raise TwitchUnreachable(f"HTTP {r.status}")
                await self._sleep(delay)
                delay = min(delay * 2, 60)
                continue
            try:
                data = r.json()
            except ValueError:
                raise GqlError(f"HTTP {r.status}: response was not JSON") from None
            if isinstance(data, dict) and "error" in data:
                raise GqlError(f"HTTP {r.status}: {data.get('error')}: {data.get('message', '')}")
            if r.status >= 400:
                raise GqlError(f"HTTP {r.status}")
            items = data if isinstance(data, list) else [data]
            messages = [e.get("message", "") for i in items for e in (i.get("errors") or [])]
            if messages:
                if gql_retries < TRIES - 1 and RETRYABLE.intersection(messages):
                    gql_retries += 1
                    log.warning("GQL %s, retry %d", "; ".join(messages), gql_retries)
                    await self._sleep(5 * gql_retries)
                    continue
                raise GqlError("; ".join(messages))
            return data
