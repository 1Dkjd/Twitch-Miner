"""Push notifications to the services Clawdmeter supports (its remote_notify.py, same request shapes).

Each send is one HTTPS POST through an injected `post(url, *, json=, data=, headers=) -> status` so the
request shapes are testable without a network. Failures come back as (False, message) and never raise.
Messages name the service and the HTTP status or exception TYPE only: a Telegram token sits in the URL and
a webhook URL is itself the secret, so neither may reach a log line or the page.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

log = logging.getLogger("dropwatch.notify")

Post = Callable[..., Awaitable[int]]
NTFY_SERVER = "https://ntfy.sh"
TIMEOUT_S = 10


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    secret: bool


@dataclass(frozen=True)
class Channel:
    name: str
    fields: tuple[Field, ...]
    hint: str


# Clawdmeter's order, labels and setup hints (dashboard.py _PUSH_FIELD_SPECS / _PUSH_HINTS)
CHANNELS: dict[str, Channel] = {
    "ntfy": Channel("ntfy", (Field("topic", "ntfy topic (e.g. dropwatch-nick-7f3a) or full URL", False),),
                    "Subscribe to the same topic in the ntfy app (Android/iOS). Pick a long, hard-to-guess "
                    "topic: anyone who knows it can read your alerts."),
    "telegram": Channel("Telegram", (Field("token", "Telegram bot token (from @BotFather)", True),
                                     Field("chat_id", "Telegram chat ID (e.g. 123456789)", False)),
                        "Message @BotFather to create a bot and copy its token, then DM the bot and read "
                        "your chat ID from api.telegram.org/bot<token>/getUpdates. Keep the token private."),
    "discord": Channel("Discord", (Field("webhook_url", "Discord webhook URL", True),),
                       "In Discord: Channel Settings → Integrations → Webhooks → New Webhook → Copy URL. "
                       "Anyone with the URL can post there, so keep it private."),
    "slack": Channel("Slack", (Field("webhook_url", "Slack incoming webhook URL", True),),
                     "In Slack: create an Incoming Webhook for a channel (api.slack.com/messaging/webhooks) "
                     "and paste its URL. Keep it private."),
    "pushover": Channel("Pushover", (Field("token", "Pushover application API token", True),
                                     Field("user", "Pushover user key", True)),
                        "Create an application at pushover.net for the API token; your user key is on your "
                        "Pushover dashboard. Get the app on iOS/Android."),
    "gotify": Channel("Gotify", (Field("server", "Gotify server URL (e.g. https://gotify.example.com)",
                                       False),
                                 Field("token", "Gotify app token", True)),
                      "Self-hosted Gotify: your server URL plus an application token from the Gotify apps "
                      "page."),
    "webhook": Channel("Webhook", (Field("url", "Webhook URL (receives a JSON POST)", True),),
                       "POSTs JSON {title, body, app} to any URL: wire it to Zapier, Make, IFTTT, n8n, "
                       "Home Assistant, or your own endpoint."),
}
_URL_FIELDS = {("discord", "webhook_url"), ("slack", "webhook_url"), ("webhook", "url"), ("gotify", "server")}


def configured(kind: str, values: dict[str, str]) -> bool:
    return all((values.get(f.key) or "").strip() for f in CHANNELS[kind].fields)


def summary(kind: str, values: dict[str, str]) -> str:
    """Glanceable state for the channel card: the ntfy topic (not secret), otherwise set / incomplete."""
    got = [bool((values.get(f.key) or "").strip()) for f in CHANNELS[kind].fields]
    if kind == "ntfy":
        return (values.get("topic") or "").strip() or "not set"
    if not any(got):
        return "not set"
    if not all(got):
        return "incomplete"
    return {"telegram": "bot + chat set", "discord": "webhook set", "slack": "webhook set",
            "webhook": "URL set", "pushover": "token + user key set", "gotify": "server + token set"}[kind]


def _ntfy_target(topic: str) -> tuple[str, str]:
    """A bare topic goes to ntfy.sh; a full URL means a self-hosted server: (server root, topic)."""
    topic = topic.strip().rstrip("/")
    if not topic.startswith(("http://", "https://")):
        return NTFY_SERVER + "/", topic
    parts = urlsplit(topic)
    *prefix, name = parts.path.strip("/").split("/")
    return f"{parts.scheme}://{parts.netloc}/" + "".join(p + "/" for p in prefix), name


# Discord (2026-10-31): every alert as an embed, styled by what it says: (words in the title, emoji, colour),
# first match wins. The "Dropwatch: " prefix moves to the webhook's name and the footer.
_DISCORD_STYLES = (
    (("again", "after all"), "✅", 0x57F287),
    (("Claimed",), "🎁", 0x9146FF),
    (("Ending soon",), "⏳", 0xF0B232),
    (("account linked",), "🔗", 0xF0B232),
    (("Your week",), "📊", 0x5865F2),
    (("Can't reach", "stopped", "isn't earning", "couldn't be claimed"), "⚠️", 0xED4245),
)
LINK_URL = "https://www.twitch.tv/drops/campaigns"


def _discord(title: str, body: str, image: str) -> dict:
    from datetime import UTC, datetime
    name = title.removeprefix("Dropwatch: ")
    emoji, colour = next(((e, c) for words, e, c in _DISCORD_STYLES if any(w in name for w in words)),
                         ("🔔", 0x9146FF))
    if "account linked" in name and name[:1].isdigit():  # "2 campaigns need…": one per line
        body = "• " + body.replace("), ", ")\n• ")
    embed = {"title": f"{emoji} {name}"[:256], "description": body[:4000], "color": colour,
             "footer": {"text": "Dropwatch"}, "timestamp": datetime.now(UTC).isoformat()}
    if "account linked" in name:
        embed["url"] = LINK_URL  # the title opens Twitch's drops page to link accounts
    if image:
        embed["thumbnail"] = {"url": image}
    return {"username": "Dropwatch", "embeds": [embed]}


async def send(kind: str, values: dict[str, str], title: str, body: str, post: Post,
               image: str = "") -> tuple[bool, str]:
    """image (2026-10-18): a Twitch CDN picture shown by services that can (Discord embed, Telegram photo,
    ntfy icon and attachment, Slack and Gotify image, the webhook's "image"); the others get the text."""
    spec = CHANNELS.get(kind)
    if spec is None:
        return False, f"unknown channel {kind}"
    v = {f.key: (values.get(f.key) or "").strip() for f in spec.fields}
    if not configured(kind, v):
        return False, f"{spec.name}: incomplete, fill in every field"
    for k in v:
        if (kind, k) in _URL_FIELDS and not v[k].startswith(("http://", "https://")):
            return False, f"{spec.name}: the URL must start with http:// or https://"
    image = image if image.startswith("https://static-cdn.jtvnw.net/") else ""
    if kind == "ntfy":
        server, topic = _ntfy_target(v["topic"])
        msg = {"topic": topic, "title": title, "message": body, "tags": ["pick"]}
        req = (server, {"json": {**msg, "icon": image, "attach": image} if image else msg})
    elif kind == "telegram":
        text = f"{title}\n{body}" if title else body
        req = ((f"https://api.telegram.org/bot{v['token']}/sendPhoto",
                {"json": {"chat_id": v["chat_id"], "photo": image, "caption": text[:1000]}}) if image else
               (f"https://api.telegram.org/bot{v['token']}/sendMessage",
                {"json": {"chat_id": v["chat_id"], "text": text}}))
    elif kind == "discord":
        req = (v["webhook_url"], {"json": _discord(title, body, image)})
    elif kind == "slack":
        text = f"*{title}*\n{body}" if title else body
        msg = {"text": text}
        if image:
            msg["blocks"] = [{"type": "section", "text": {"type": "mrkdwn", "text": text},
                              "accessory": {"type": "image", "image_url": image,
                                            "alt_text": title or "reward"}}]
        req = (v["webhook_url"], {"json": msg})
    elif kind == "webhook":
        msg = {"title": title, "body": body, "app": "Dropwatch"}
        req = (v["url"], {"json": {**msg, "image": image} if image else msg})
    elif kind == "pushover":
        req = ("https://api.pushover.net/1/messages.json",
               {"data": {"token": v["token"], "user": v["user"], "title": title, "message": body}})
    else:  # gotify
        msg = {"title": title, "message": body, "priority": 5}
        if image:
            msg["extras"] = {"client::notification": {"bigImageUrl": image}}
        req = (v["server"].rstrip("/") + "/message", {"json": msg, "headers": {"X-Gotify-Key": v["token"]}})
    url, kw = req
    try:
        status = await post(url, **kw)
    except Exception as exc:  # noqa: BLE001 - any network failure is reported, never raised
        return False, f"{spec.name}: couldn't connect ({type(exc).__name__})"
    if not 200 <= status < 300:
        return False, f"{spec.name}: HTTP {status}"
    return True, "sent"


async def dispatch(channels: dict[str, dict[str, str]], title: str, body: str, post: Post,
                   image: str = "") -> list[dict]:
    """Every configured channel, in the order they were added; one result per channel tried."""
    out = []
    for kind, values in channels.items():
        if kind in CHANNELS and configured(kind, values):
            ok, msg = await send(kind, values, title, body, post, image)
            out.append({"type": kind, "name": CHANNELS[kind].name, "ok": ok, "message": msg})
    return out


def aiohttp_post(session) -> Post:
    """The real `post`: one aiohttp request with a 10 s budget, returning the HTTP status."""
    import aiohttp

    async def post(url, *, json=None, data=None, headers=None) -> int:
        async with session.post(url, json=json, data=data, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=TIMEOUT_S)) as resp:
            return resp.status
    return post


async def send_all(channels: dict[str, dict[str, str]], title: str, body: str,
                   post: Post | None = None, image: str = "") -> list[dict]:
    """dispatch() with a fresh aiohttp session unless a `post` is given (tests)."""
    if post is not None:
        return await dispatch(channels, title, body, post, image)
    import aiohttp

    async with aiohttp.ClientSession() as session:
        return await dispatch(channels, title, body, aiohttp_post(session), image)
