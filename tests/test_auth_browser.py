import json

import pytest

from dropsminer.twitch.auth_browser import SignInError, delegated_payload, validate_token
from dropsminer.twitch.constants import ANDROID_APP, WEB
from dropsminer.twitch.transport import HttpResponse

LOGIN = "https://passport.twitch.tv/protected_login"


def test_rewrites_only_protected_login_posts():
    body = json.dumps({"username": "u", "password": "p", "client_id": WEB.client_id})
    out = json.loads(delegated_payload(LOGIN, "POST", body))
    assert out["client_id"] == WEB.client_id
    assert out["delegate_client_id"] == ANDROID_APP.client_id
    assert out["username"] == "u"
    assert delegated_payload(LOGIN + "/shim", "POST", body) is not None
    assert delegated_payload(LOGIN, "GET", body) is None
    assert delegated_payload("https://passport.twitch.tv/other", "POST", body) is None
    assert delegated_payload("http://passport.twitch.tv/protected_login", "POST", body) is None


def test_rejects_unexpected_login_body():
    with pytest.raises(SignInError):
        delegated_payload(LOGIN, "POST", "not json")
    with pytest.raises(SignInError):
        delegated_payload(LOGIN, "POST", json.dumps({"user": "x"}))


class T:
    def __init__(self, resp):
        self.resp = resp

    async def request(self, method, url, *, headers, json=None, data=None):
        assert headers["Authorization"] == "OAuth tok"
        return self.resp


async def test_validate_accepts_android_token():
    body = json.dumps({"client_id": ANDROID_APP.client_id, "user_id": "42", "login": "me"})
    assert await validate_token(T(HttpResponse(200, body)), "tok") == (42, "me")


async def test_validate_rejects_web_token():
    body = json.dumps({"client_id": WEB.client_id, "user_id": "42", "login": "me"})
    with pytest.raises(SignInError, match="WEB"):
        await validate_token(T(HttpResponse(200, body)), "tok")


async def test_validate_rejects_http_error():
    with pytest.raises(SignInError, match="401"):
        await validate_token(T(HttpResponse(401, "{}")), "tok")
