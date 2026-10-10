"""Phase 2b Task 6: Twitch TV code sign-in (spec §4, 2026-10-10)."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from dropwatch.twitch.auth_browser import SignInError
from dropwatch.twitch.auth_device import DeviceCodeSignIn
from dropwatch.twitch.constants import ANDROID_APP, SMARTBOX
from dropwatch.twitch.transport import HttpResponse

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
DEVICE = {"device_code": "dc", "user_code": "BKDQMDGP", "verification_uri": "https://www.twitch.tv/activate",
          "expires_in": 1800, "interval": 5}


def resp(status, obj):
    return HttpResponse(status, json.dumps(obj))


class Net:
    def __init__(self, tokens, validate=None, device=None):
        self.tokens, self.calls = list(tokens), []
        self.validate = validate or resp(200, {"client_id": SMARTBOX.client_id, "user_id": "42",
                                               "login": "kp", "expires_in": 0})
        self.device = device or resp(200, DEVICE)

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append((method, url, dict(headers), data))
        if url.endswith("/oauth2/device"):
            return self.device
        if url.endswith("/oauth2/token"):
            return self.tokens.pop(0)
        if url.endswith("/oauth2/validate"):
            return self.validate
        return HttpResponse(200, "")


PENDING = resp(400, {"status": 400, "message": "authorization_pending"})
TOKEN = resp(200, {"access_token": "secret-token", "token_type": "bearer"})


def make(net, clock=None):
    waits = []

    async def pause(cancel, seconds):
        waits.append(seconds)
        if clock is not None:
            clock[0] += timedelta(seconds=seconds)
    c = clock or [NOW]
    return DeviceCodeSignIn(net, clock=lambda: c[0], pause=pause), waits


async def test_start_returns_code_and_uses_tv_client():
    net = Net([])
    s, _ = make(net)
    code = await s.start()
    assert (code.user_code, code.verification_uri) == ("BKDQMDGP", "https://www.twitch.tv/activate")
    assert code.expires_at == NOW + timedelta(seconds=1800)
    method, url, headers, data = next(c for c in net.calls if c[1].endswith("/oauth2/device"))
    assert data["client_id"] == SMARTBOX.client_id and headers["Client-Id"] == SMARTBOX.client_id


async def test_start_failure_is_a_readable_error():
    s, _ = make(Net([], device=resp(400, {"status": 400, "message": "invalid client"})))
    with pytest.raises(SignInError, match="invalid client"):
        await s.start()


async def test_wait_polls_until_token_and_builds_tv_session():
    s, waits = make(Net([PENDING, PENDING, TOKEN]))
    code = await s.start()
    session = await s.wait(code, asyncio.Event())
    assert session.client_id == SMARTBOX.client_id and session.user_id == 42 and session.login == "kp"
    assert waits == [5, 5, 5]


async def test_slow_down_respected():
    s, waits = make(Net([resp(400, {"message": "slow_down"}), TOKEN]))
    await s.wait(await s.start(), asyncio.Event())
    assert waits == [5, 10]


async def test_expired_by_twitch_message():
    s, _ = make(Net([PENDING, resp(400, {"status": 400, "message": "invalid device code"})]))
    with pytest.raises(SignInError, match="expired"):
        await s.wait(await s.start(), asyncio.Event())


async def test_expired_by_time_without_own_timeout():
    clock = [NOW]
    s, waits = make(Net([PENDING] * 400), clock)
    with pytest.raises(SignInError, match="expired"):
        await s.wait(await s.start(), asyncio.Event())
    assert sum(waits) >= 1800  # it waited out Twitch's own 30 minutes, nothing shorter


async def test_cancel():
    s, _ = make(Net([PENDING] * 3))
    code = await s.start()
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(SignInError, match="cancelled"):
        await s.wait(code, cancel)


async def test_rejects_non_tv_token():
    android = resp(200, {"client_id": ANDROID_APP.client_id, "user_id": "42", "login": "kp"})
    net = Net([TOKEN], validate=android)
    s, _ = make(net)
    with pytest.raises(SignInError, match="not the TV app"):
        await s.wait(await s.start(), asyncio.Event())


async def test_token_never_in_error_text():
    net = Net([TOKEN], validate=resp(401, {"message": "invalid"}))
    s, _ = make(net)
    with pytest.raises(SignInError) as e:
        await s.wait(await s.start(), asyncio.Event())
    assert "secret-token" not in str(e.value)
