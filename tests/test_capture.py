from dropsminer.twitch.capture import scrub


def test_scrub_replaces_secrets_everywhere():
    raw = {
        "user": {"id": "424242", "login": "kernelpanicattack"},
        "list": ["OAuth tok123", 424242, "x"],
        "url": "https://x/kernelpanicattack/y",
    }
    out = scrub(raw, {"tok123": "<TOKEN>", "424242": "<USER_ID>", "kernelpanicattack": "<LOGIN>"})
    assert out == {
        "user": {"id": "<USER_ID>", "login": "<LOGIN>"},
        "list": ["OAuth <TOKEN>", "<USER_ID>", "x"],
        "url": "https://x/<LOGIN>/y",
    }


def test_scrub_ignores_empty_secret():
    assert scrub({"a": "b"}, {"": "<X>"}) == {"a": "b"}
