from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp


@dataclass(frozen=True)
class HttpResponse:
    status: int
    text: str

    def json(self) -> Any:
        return _json.loads(self.text)


class HttpTransport(Protocol):
    async def request(
        self, method: str, url: str, *, headers: dict[str, str], json: Any = None, data: Any = None
    ) -> HttpResponse: ...


class AiohttpTransport:
    """The real transport. Owns one aiohttp session with its own cookie jar."""

    def __init__(self, timeout: float = 30):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def request(self, method, url, *, headers, json=None, data=None) -> HttpResponse:
        async with self.session.request(method, url, headers=headers, json=json, data=data) as r:
            return HttpResponse(r.status, await r.text(encoding="utf-8"))

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
