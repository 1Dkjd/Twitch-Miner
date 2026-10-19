"""Reward pictures in notifications (2026-10-18)."""
from datetime import UTC, datetime, timedelta

from test_notify_send import FakePost

from dropwatch.alerts import Notifier, Snapshot
from dropwatch.notify import send
from dropwatch.store import Store

IMG = "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/abc.png"


async def sent(kind, values, image=IMG):
    post = FakePost()
    ok, _ = await send(kind, values, "Dropwatch: Claimed Hat", "Palia, after 1 h.", post, image)
    assert ok
    return post.calls[0]


async def test_discord_gets_an_embed_with_the_reward_picture():
    c = await sent("discord", {"webhook_url": "https://discord.com/api/webhooks/1/x"})
    (e,) = c["json"]["embeds"]
    assert e["title"] == "Dropwatch: Claimed Hat" and e["description"] == "Palia, after 1 h."
    assert e["thumbnail"] == {"url": IMG}
    plain = await sent("discord", {"webhook_url": "https://discord.com/api/webhooks/1/x"}, image="")
    assert plain["json"] == {"content": "**Dropwatch: Claimed Hat**\nPalia, after 1 h."}


async def test_other_services_show_it_their_own_way():
    t = await sent("telegram", {"token": "T", "chat_id": "1"})
    assert t["url"].endswith("/sendPhoto") and t["json"]["photo"] == IMG
    assert "Claimed Hat" in t["json"]["caption"]
    n = await sent("ntfy", {"topic": "dw"})
    assert n["json"]["icon"] == IMG and n["json"]["attach"] == IMG
    s = await sent("slack", {"webhook_url": "https://hooks.slack.com/x"})
    assert s["json"]["blocks"][0]["accessory"]["image_url"] == IMG
    g = await sent("gotify", {"server": "https://g.example", "token": "k"})
    assert g["json"]["extras"]["client::notification"]["bigImageUrl"] == IMG
    w = await sent("webhook", {"url": "https://hook.example"})
    assert w["json"]["image"] == IMG


async def test_only_twitch_pictures_are_ever_sent():
    c = await sent("discord", {"webhook_url": "https://discord.com/api/webhooks/1/x"},
                   image="https://tracker.example/pixel.png")
    assert "embeds" not in c["json"]


def test_a_claim_alert_carries_the_reward_picture_or_the_box_art(tmp_path):
    st = Store(tmp_path / "d.db")
    st.put_settings({"notify_claimed": True})
    clock = [datetime(2026, 10, 18, 12, tzinfo=UTC)]
    n = Notifier(st, clock=lambda: clock[0], tz=UTC)
    n.handle("claimed", {"campaign": "S2", "game": "WARDOGS", "reward": "Dog tag", "image": IMG,
                         "box_art": "https://static-cdn.jtvnw.net/ttv-boxart/1.jpg"})
    clock[0] += timedelta(minutes=2)
    (a,) = n.check(Snapshot(None, None, []))
    assert a.image == IMG
    n.handle("claimed", {"campaign": "S2", "game": "WARDOGS", "reward": "No pic", "image": "",
                         "box_art": "https://static-cdn.jtvnw.net/ttv-boxart/1.jpg"})
    clock[0] += timedelta(minutes=2)
    (b,) = n.check(Snapshot(None, None, []))
    assert b.image == "https://static-cdn.jtvnw.net/ttv-boxart/1.jpg"
