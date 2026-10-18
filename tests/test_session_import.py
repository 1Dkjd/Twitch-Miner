"""PC sign-in import (2026-10-18): an Android-app token made on a PC replaces the TV sign-in."""
import json

from apihelpers import logged_in, make_app

from dropwatch.api.signin import SignInManager
from dropwatch.events import EventBus
from dropwatch.twitch import auth_browser, pc_signin_helper
from dropwatch.twitch.auth_browser import SignInError
from dropwatch.twitch.constants import ANDROID_APP, SMARTBOX
from dropwatch.twitch.transport import HttpResponse


class Store:
    def __init__(self):
        self.session = None

    def set_session(self, s):
        self.session = s


class Net:
    """Twitch's token check: answers with whichever client the token belongs to."""

    def __init__(self, client_id=ANDROID_APP.client_id, status=200):
        self.client_id, self.status, self.calls = client_id, status, []

    async def request(self, method, url, *, headers, json=None, data=None):
        self.calls.append(url)
        if "validate" in url:
            body = {"client_id": self.client_id, "user_id": "4242", "login": "dk"}
            return HttpResponse(self.status, __import__("json").dumps(body))
        return HttpResponse(200, "")


def manager(net, restarted):
    async def on():
        restarted.append(True)

    async def close():
        pass
    return SignInManager(Store(), EventBus(), lambda: None, on, lambda: (net, close))


async def test_an_android_token_replaces_the_session_and_restarts_mining():
    restarted = []
    m = manager(Net(), restarted)
    assert await m.import_android("OAuth abc123") == "dk"
    s = m._store.session
    assert (s.access_token, s.user_id, s.login, s.client_id) == ("abc123", 4242, "dk", ANDROID_APP.client_id)
    assert restarted == [True]
    assert m.status()["status"] == "done"


async def test_a_tv_or_rejected_token_changes_nothing():
    for net in (Net(client_id=SMARTBOX.client_id), Net(status=401)):
        restarted = []
        m = manager(net, restarted)
        try:
            await m.import_android("abc123")
        except SignInError:
            pass
        else:
            raise AssertionError("should have refused")
        assert m._store.session is None and restarted == []


async def test_junk_is_refused_before_asking_twitch():
    net = Net()
    m = manager(net, [])
    for bad in ("", "has spaces in it", "x" * 300, "semi;colon"):
        try:
            await m.import_android(bad)
        except SignInError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    assert net.calls == []


def test_the_helper_rewrites_logins_exactly_like_dropwatch():
    body = json.dumps({"username": "dk", "password": "p", "client_id": "x"})
    for url in ("https://passport.twitch.tv/protected_login", "https://passport.twitch.tv/protected_login/shim"):
        assert json.loads(pc_signin_helper.delegated_payload(url, "POST", body)) == \
            json.loads(auth_browser.delegated_payload(url, "POST", body))
    assert pc_signin_helper.delegated_payload("https://www.twitch.tv/", "POST", body) is None
    assert pc_signin_helper.ANDROID_CLIENT_ID == ANDROID_APP.client_id


def test_the_helper_file_holds_what_the_import_needs():
    f = pc_signin_helper.session_file("abc123", 4242, "dk")
    assert f["format"] == "dropwatch-session" and f["access_token"] == "abc123" and f["login"] == "dk"


class ImportingSignIn:
    def __init__(self, fail=None):
        self.fail, self.got = fail, []

    async def import_android(self, token):
        self.got.append(token)
        if self.fail:
            raise SignInError(self.fail)
        return "dk"


async def test_import_endpoint_and_helper_download(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.signin.import_android = ImportingSignIn().import_android
    c = await logged_in(app)
    r = await c.post("/api/twitch/session", json={"access_token": "abc123"})
    assert r.status_code == 200 and r.json() == {"login": "dk"}
    r = await c.get("/api/twitch/signin-helper")
    assert r.status_code == 200
    assert 'filename="dropwatch-signin.py"' in r.headers["content-disposition"]
    assert b"delegate_client_id" in r.content and b"# /// script" in r.content
    ctx.signin.import_android = ImportingSignIn("Twitch issued a website token").import_android
    r = await c.post("/api/twitch/session", json={"access_token": "abc123"})
    assert r.status_code == 422 and "website token" in r.json()["detail"]


def test_state_says_which_kind_of_sign_in():
    from dropwatch.api.views import signin_kind
    from dropwatch.twitch.session import TwitchSession
    assert signin_kind(None) is None
    assert signin_kind(TwitchSession("t", 1, "dk", "d", SMARTBOX.client_id, "s")) == "tv"
    assert signin_kind(TwitchSession("t", 1, "dk", "d", ANDROID_APP.client_id, "s")) == "android"
