from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TwitchSession:
    access_token: str = field(repr=False)
    user_id: int
    login: str
    device_id: str
    client_id: str
    session_id: str

from .constants import ClientInfo  # noqa: E402


def base_headers(s: TwitchSession | None, client: ClientInfo) -> dict[str, str]:
    h = {
        "Accept": "*/*",
        "Accept-Language": "en-US",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Client-Id": client.client_id,
        "User-Agent": client.user_agent,
    }
    if s is not None:
        h["Client-Session-Id"] = s.session_id
        h["X-Device-Id"] = s.device_id
    return h


def gql_headers(s: TwitchSession, client: ClientInfo) -> dict[str, str]:
    h = base_headers(s, client)
    h.update(Origin=client.client_url, Referer=client.client_url, Authorization=f"OAuth {s.access_token}")
    return h
