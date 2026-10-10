"""Notifications API: settings, channels (secrets never sent back to the page), and Send test."""
from apihelpers import logged_in, make_app
from test_notify_send import FakePost


async def test_settings_carry_the_alert_switches_and_wait_times(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    s = (await c.get("/api/settings")).json()
    assert s["notify_needs_you"] is False and s["notify_stopped"] is True
    assert s["notify_unreachable_minutes"] == 15
    r = await c.put("/api/settings", json={"notify_not_earning_minutes": 60, "notify_claim_failed": False})
    assert r.status_code == 200 and r.json()["notify_not_earning_minutes"] == 60
    assert r.json()["notify_claim_failed"] is False
    for bad in ({"notify_unreachable_minutes": 2}, {"notify_unreachable_minutes": 500},
                {"notify_not_earning_minutes": "30"}, {"notify_target": "x"}):
        assert (await c.put("/api/settings", json=bad)).status_code == 422, bad
    await c.aclose()


async def test_channels_add_edit_remove_and_never_echo_a_secret(tmp_path):
    app, _ = make_app(tmp_path)
    c = await logged_in(app)
    first = (await c.get("/api/notify/channels")).json()
    assert first["channels"] == []
    assert [a["type"] for a in first["available"]][:3] == ["ntfy", "telegram", "discord"]
    r = await c.put("/api/notify/channels/discord", json={"values": {}})  # "Add a channel": added, not set up
    (ch,) = r.json()["channels"]
    assert (ch["type"], ch["configured"], ch["summary"]) == ("discord", False, "not set")
    assert "discord" not in [a["type"] for a in r.json()["available"]]
    secret = "https://discord.com/api/webhooks/1/VERY-SECRET"
    r = await c.put("/api/notify/channels/discord", json={"values": {"webhook_url": secret}})
    (ch,) = r.json()["channels"]
    assert ch["configured"] and ch["summary"] == "webhook set"
    assert ch["fields"] == [{"key": "webhook_url", "label": "Discord webhook URL", "secret": True,
                             "value": "", "set": True}]
    assert secret not in r.text and secret not in (await c.get("/api/notify/channels")).text
    assert secret not in (await c.get("/api/settings")).text
    r = await c.put("/api/notify/channels/ntfy", json={"values": {"topic": "dw-nick"}})
    assert [x["type"] for x in r.json()["channels"]] == ["discord", "ntfy"]
    assert r.json()["channels"][1]["fields"][0]["value"] == "dw-nick"  # not secret: shown
    r = await c.delete("/api/notify/channels/discord")
    assert [x["type"] for x in r.json()["channels"]] == ["ntfy"]
    assert (await c.put("/api/notify/channels/carrier-pigeon", json={"values": {}})).status_code == 404
    assert (await c.put("/api/notify/channels/ntfy", json={"values": {"nope": "x"}})).status_code == 422
    too_long = {"values": {"topic": "x" * 501}}
    assert (await c.put("/api/notify/channels/ntfy", json=too_long)).status_code == 422
    await c.aclose()


async def test_send_test_reports_each_channel(tmp_path):
    app, ctx = make_app(tmp_path)
    ctx.post = FakePost()
    c = await logged_in(app)
    r = (await c.post("/api/notify/test")).json()
    assert r == {"ok": False, "message": "Add a channel first.", "results": []}
    ctx.store.put_channel("ntfy", {"topic": "dw-nick"})
    ctx.store.put_channel("slack", {"webhook_url": "https://hooks.slack.com/x"})
    r = (await c.post("/api/notify/test")).json()
    assert r["ok"] and r["message"] == "Sent to ntfy and Slack."
    assert ctx.post.calls[0]["json"]["title"] == "Dropwatch: Test notification"
    ctx.post = FakePost(status=404)
    r = (await c.post("/api/notify/test")).json()
    assert not r["ok"] and r["message"] == "Failed: ntfy: HTTP 404; Slack: HTTP 404."
    await c.aclose()


async def test_notification_routes_need_the_page_password(tmp_path):
    app, _ = make_app(tmp_path)
    from apihelpers import client
    c = client(app)
    for method, path in (("get", "/api/notify/channels"), ("post", "/api/notify/test"),
                         ("delete", "/api/notify/channels/ntfy")):
        assert (await getattr(c, method)(path)).status_code == 401
    assert (await c.put("/api/notify/channels/ntfy", json={"values": {}})).status_code == 401
    await c.aclose()
