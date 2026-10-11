"""Settings › Backup: save lists, pins, settings and notification channels to a file, and restore them
(approved mockup docs/design/pre-docker-mockup.html, 2026-10-10)."""
from apihelpers import client, logged_in, make_app

SECRET = "https://discord.com/api/webhooks/1/very-secret"


async def seeded(tmp_path):
    app, ctx = make_app(tmp_path)
    s = ctx.store
    s.set_lists(["Palia", "Escape from Tarkov"], {"Fortnite"}, ["honeyxxo"])
    s.set_pins(["c7", "c3"])
    s.put_settings({"notify_weekly": True, "notify_weekly_tz": "Europe/London", "mine_badges": True})
    s.put_channel("ntfy", {"topic": "dropwatch-nick"})
    s.put_channel("discord", {"webhook_url": SECRET})
    return app, ctx, await logged_in(app)


async def test_backup_without_secrets_leaves_them_out(tmp_path):
    _, _, c = await seeded(tmp_path)
    r = await c.get("/api/backup")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith('attachment; filename="dropwatch-backup-')
    b = r.json()
    assert b["dropwatch_backup"] == 1
    assert b["lists"] == {"priority": ["Palia", "Escape from Tarkov"], "never": ["Fortnite"],
                          "favourites": ["honeyxxo"]}
    assert b["pins"] == ["c7", "c3"]
    assert b["settings"]["notify_weekly_tz"] == "Europe/London" and b["settings"]["mine_badges"] is True
    assert b["notify_channels"] == {"ntfy": {"topic": "dropwatch-nick"}, "discord": {}}
    assert SECRET not in r.text


async def test_backup_with_secrets_includes_them(tmp_path):
    _, _, c = await seeded(tmp_path)
    b = (await c.get("/api/backup?secrets=1")).json()
    assert b["notify_channels"]["discord"] == {"webhook_url": SECRET}


async def test_restore_replaces_lists_settings_and_channels(tmp_path):
    _, _, c = await seeded(tmp_path)
    backup = (await c.get("/api/backup?secrets=1")).json()
    other, octx = make_app(tmp_path / "other")
    # not in the backup: removed
    octx.store.put_channel("slack", {"webhook_url": "https://hooks.slack.com/x"})
    async with client(other) as c2:
        await c2.post("/api/login", json={"password": "correct horse"})
        r = await c2.post("/api/restore", json=backup)
        assert r.status_code == 200, r.text
    p = octx.store.get_prefs()
    assert p.priority == ("Palia", "Escape from Tarkov") and p.never == frozenset({"Fortnite"})
    assert p.favourites == ("honeyxxo",) and octx.store.get_pins() == ["c7", "c3"]
    assert octx.store.get_settings()["notify_weekly_tz"] == "Europe/London"
    assert octx.store.get_channels() == {"ntfy": {"topic": "dropwatch-nick"},
                                         "discord": {"webhook_url": SECRET}}


async def test_restoring_a_backup_without_secrets_keeps_the_ones_already_set(tmp_path):
    _, ctx, c = await seeded(tmp_path)
    backup = (await c.get("/api/backup")).json()
    ctx.store.set_lists([], set(), [])
    assert (await c.post("/api/restore", json=backup)).status_code == 200
    assert ctx.store.get_channels()["discord"] == {"webhook_url": SECRET}
    assert ctx.store.get_prefs().priority == ("Palia", "Escape from Tarkov")


async def test_a_newer_backups_unknown_settings_and_channels_are_skipped_and_named(tmp_path):
    _, ctx, c = await seeded(tmp_path)
    backup = (await c.get("/api/backup")).json()
    backup["settings"]["notify_future_thing"] = True
    backup["notify_channels"]["matrix"] = {"room": "!x"}
    r = await c.post("/api/restore", json=backup)
    assert r.status_code == 200
    assert set(r.json()["skipped"]) == {"setting notify_future_thing", "channel matrix"}
    assert "matrix" not in ctx.store.get_channels()


async def test_a_bad_file_changes_nothing(tmp_path):
    _, ctx, c = await seeded(tmp_path)
    good = (await c.get("/api/backup")).json()
    bad = [
        {"hello": "world"},
        {**good, "dropwatch_backup": 99},
        {**good, "lists": {**good["lists"], "never": ["Palia"]}},  # in Priority and Never at once
        {**good, "settings": {**good["settings"], "notify_unreachable_minutes": 1}},
        {**good, "notify_channels": {"discord": {"webhook_url": "x" * 600}}},
    ]
    ctx.store.set_lists(["Only this"], set(), [])
    for b in bad:
        assert (await c.post("/api/restore", json=b)).status_code == 422, b
    assert ctx.store.get_prefs().priority == ("Only this",)


async def test_backup_and_restore_need_the_page_password(tmp_path):
    app, _ = make_app(tmp_path)
    async with client(app) as c:
        assert (await c.get("/api/backup")).status_code == 401
        assert (await c.post("/api/restore", json={})).status_code == 401


async def test_restore_takes_only_a_json_body(tmp_path):
    # review fix: a text/plain POST needs no CORS preflight, so a sibling app on the same host could send one
    _, ctx, c = await seeded(tmp_path)
    backup = (await c.get("/api/backup")).json()
    import json
    r = await c.post("/api/restore", content=json.dumps(backup), headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
