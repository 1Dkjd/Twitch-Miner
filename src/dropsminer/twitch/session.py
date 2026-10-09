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
