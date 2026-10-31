"""The seven push services, mirroring Clawdmeter's remote_notify (same request shapes)."""
import pytest

from dropwatch.notify import CHANNELS, configured, dispatch, send, summary


class FakePost:
    def __init__(self, status=200, exc=None):
        self.status, self.exc, self.calls = status, exc, []

    async def __call__(self, url, *, json=None, data=None, headers=None):
        self.calls.append({"url": url, "json": json, "data": data, "headers": headers})
        if self.exc:
            raise self.exc
        return self.status


async def one(kind, values, post=None):
    post = post or FakePost()
    ok, msg = await send(kind, values, "Dropwatch: Test", "It works.", post)
    return ok, msg, post.calls


async def test_ntfy_publishes_json_to_the_server_root():
    ok, _, (c,) = await one("ntfy", {"topic": "dw-nick"})
    assert ok and c["url"] == "https://ntfy.sh/"
    assert c["json"] == {"topic": "dw-nick", "title": "Dropwatch: Test", "message": "It works.",
                         "tags": ["pick"]}
    _, _, (c,) = await one("ntfy", {"topic": "https://ntfy.example.com/dw-nick/"})  # self-hosted
    assert c["url"] == "https://ntfy.example.com/" and c["json"]["topic"] == "dw-nick"


async def test_telegram_discord_slack_webhook_pushover_gotify_shapes():
    _, _, (c,) = await one("telegram", {"token": "123:abc", "chat_id": "42"})
    assert c["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert c["json"] == {"chat_id": "42", "text": "Dropwatch: Test\nIt works."}
    _, _, (c,) = await one("discord", {"webhook_url": "https://discord.com/api/webhooks/1/x"})
    (e,) = c["json"]["embeds"]
    assert c["json"]["username"] == "Dropwatch"
    assert (e["title"], e["description"], e["footer"]) == ("🔔 Test", "It works.", {"text": "Dropwatch"})
    _, _, (c,) = await one("slack", {"webhook_url": "https://hooks.slack.com/services/x"})
    assert c["json"] == {"text": "*Dropwatch: Test*\nIt works."}
    _, _, (c,) = await one("webhook", {"url": "https://n8n.local/hook"})
    assert c["json"] == {"title": "Dropwatch: Test", "body": "It works.", "app": "Dropwatch"}
    _, _, (c,) = await one("pushover", {"token": "apptok", "user": "ukey"})
    assert c["url"] == "https://api.pushover.net/1/messages.json"
    assert c["data"] == {"token": "apptok", "user": "ukey", "title": "Dropwatch: Test",
                         "message": "It works."}
    _, _, (c,) = await one("gotify", {"server": "https://gotify.example.com/", "token": "gtok"})
    assert c["url"] == "https://gotify.example.com/message" and c["headers"] == {"X-Gotify-Key": "gtok"}
    assert c["json"] == {"title": "Dropwatch: Test", "message": "It works.", "priority": 5}


async def test_discord_content_is_capped():
    post = FakePost()
    await send("discord", {"webhook_url": "https://d/x"}, "T", "x" * 5000, post)
    assert len(post.calls[0]["json"]["embeds"][0]["description"]) <= 4000


async def test_failures_never_leak_a_secret():
    secret = "123:VERY-SECRET"
    ok, msg, _ = await one("telegram", {"token": secret, "chat_id": "1"}, FakePost(status=401))
    assert not ok and msg == "Telegram: HTTP 401" and secret not in msg
    boom = OSError(f"cannot connect to https://api.telegram.org/bot{secret}/sendMessage")
    ok, msg, _ = await one("telegram", {"token": secret, "chat_id": "1"}, FakePost(exc=boom))
    assert not ok and secret not in msg and msg == "Telegram: couldn't connect (OSError)"


async def test_incomplete_or_bad_values_are_refused_before_sending():
    post = FakePost()
    ok, msg, calls = await one("pushover", {"token": "t"}, post)
    assert (ok, calls) == (False, []) and "incomplete" in msg
    ok, msg, calls = await one("discord", {"webhook_url": "discord.com/x"}, post)
    assert not ok and calls == [] and "http" in msg


def test_summary_and_configured_match_clawdmeter():
    assert summary("ntfy", {"topic": "dw-nick"}) == "dw-nick"
    assert summary("telegram", {"token": "t", "chat_id": "1"}) == "bot + chat set"
    assert summary("telegram", {"token": "t"}) == "incomplete"
    assert summary("discord", {}) == "not set"
    assert summary("pushover", {"token": "t", "user": "u"}) == "token + user key set"
    assert configured("gotify", {"server": "https://g", "token": "x"})
    assert not configured("gotify", {"server": "s"})
    assert list(CHANNELS) == ["ntfy", "telegram", "discord", "slack", "pushover", "gotify", "webhook"]


async def test_dispatch_sends_to_every_configured_channel_and_reports_each():
    post = FakePost()
    results = await dispatch({"ntfy": {"topic": "dw"}, "discord": {"webhook_url": ""},
                              "slack": {"webhook_url": "https://s/x"}}, "T", "B", post)
    # Discord isn't set up, so it isn't tried
    assert [(r["type"], r["ok"]) for r in results] == [("ntfy", True), ("slack", True)]
    assert len(post.calls) == 2


@pytest.mark.parametrize("kind", ["ntfy", "telegram", "discord", "slack", "pushover", "gotify", "webhook"])
def test_every_channel_has_fields_and_a_hint(kind):
    spec = CHANNELS[kind]
    assert spec.name and spec.hint and spec.fields


async def test_discord_styles_by_alert_kind():
    async def embed(title, body="b"):
        post = FakePost()
        await send("discord", {"webhook_url": "https://d/x"}, title, body, post)
        return post.calls[0]["json"]["embeds"][0]
    down = await embed("Dropwatch: Can't reach Twitch")
    assert down["title"] == "⚠️ Can't reach Twitch" and down["color"] == 0xED4245
    back = await embed("Dropwatch: Twitch is reachable again")
    assert back["title"].startswith("✅") and back["color"] == 0x57F287
    link = await embed("Dropwatch: 2 campaigns need your account linked", "A (G1), B (G2)")
    assert link["title"].startswith("🔗") and link["url"] == "https://www.twitch.tv/drops/campaigns"
    assert link["description"] == "• A (G1)\n• B (G2)"
