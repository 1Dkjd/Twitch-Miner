from datetime import UTC, datetime, timedelta

import pytest

from dropwatch.store import Store

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def test_claims_round_trip_newest_first(tmp_path):
    st = Store(tmp_path / "d.db")
    st.add_claim(NOW - timedelta(hours=2), "c1", "Frights", "Palia", [("Palcat Glasses", "u1")])
    st.add_claim(NOW, "c2", "Crimson", "Phasmophobia", [("T-Shirt", "u2"), ("Badge", "u3")])
    rows = st.claims_since(NOW - timedelta(days=1))
    assert [r["campaign"] for r in rows] == ["Crimson", "Frights"]
    assert rows[0]["rewards"] == [{"name": "T-Shirt", "image_url": "u2"},
                                  {"name": "Badge", "image_url": "u3"}]
    assert rows[0]["at"] == NOW
    assert st.claims_since(NOW - timedelta(minutes=1))[0]["campaign"] == "Crimson"
    assert len(st.claims_since(NOW - timedelta(minutes=1))) == 1


def test_password_set_check(tmp_path):
    st = Store(tmp_path / "d.db")
    assert not st.has_password()
    st.set_password("correct horse")
    assert st.has_password()
    assert st.check_password("correct horse")
    assert not st.check_password("wrong")
    assert "correct horse" not in (st.get_setting("page_password_hash") or "")


def test_password_minimum_length(tmp_path):
    with pytest.raises(ValueError):
        Store(tmp_path / "d.db").set_password("short")


def test_web_sessions_store_only_hash_and_expire(tmp_path):
    st = Store(tmp_path / "d.db")
    tok = st.create_web_session(NOW)
    assert st.valid_web_session(tok, NOW + timedelta(days=29))
    assert not st.valid_web_session(tok, NOW + timedelta(days=31))
    assert not st.valid_web_session("nope", NOW)
    assert not st.valid_web_session(None, NOW)
    raw = (tmp_path / "d.db").read_bytes()
    assert tok.encode() not in raw
    st.delete_web_session(tok)
    assert not st.valid_web_session(tok, NOW)


def test_settings_typed_defaults_and_validation(tmp_path):
    st = Store(tmp_path / "d.db")
    s = st.get_settings()
    assert s == {"mine_badges": False, "claim_points": True, "notify_target": "",
                 "notify_claimed": True, "notify_needs_you": True, "notify_signin": True}
    out = st.put_settings({"mine_badges": True, "notify_target": "https://ntfy.sh/x"})
    assert out["mine_badges"] is True and out["notify_target"] == "https://ntfy.sh/x"
    assert st.get_prefs().mine_badges is True
    with pytest.raises(ValueError):
        st.put_settings({"unknown": 1})
    with pytest.raises(ValueError):
        st.put_settings({"mine_badges": "yes"})


def test_lists_dedupe_and_lowercase_favourites(tmp_path):
    st = Store(tmp_path / "d.db")
    st.set_lists(["Palia", "Palia", "Phasmophobia"], {"AION 2"}, ["KernelPanic", "kernelpanic", "Other"])
    p = st.get_prefs()
    assert p.priority == ("Palia", "Phasmophobia")
    assert p.favourites == ("kernelpanic", "other")
