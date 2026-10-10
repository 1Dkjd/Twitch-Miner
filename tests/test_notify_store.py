"""Notification settings and channels in the store (feat/notifications, approved 2026-10-10)."""
import pytest

from dropwatch.store import Store


def test_notification_defaults(tmp_path):
    s = Store(tmp_path / "d.db").get_settings()
    failures = ("notify_signin", "notify_unreachable", "notify_not_earning", "notify_claim_failed",
                "notify_stopped")
    assert {k: s[k] for k in failures} == dict.fromkeys(failures, True)
    assert s["notify_needs_you"] is False  # Nick: off by default
    assert (s["notify_unreachable_minutes"], s["notify_not_earning_minutes"]) == (15, 30)
    assert "notify_target" not in s  # the old single-URL design is gone
    assert s["notify_claimed"] is False  # back as an opt-in summary (2026-10-10), off by default


def test_minutes_are_numbers(tmp_path):
    st = Store(tmp_path / "d.db")
    assert st.put_settings({"notify_unreachable_minutes": 45})["notify_unreachable_minutes"] == 45
    assert Store(tmp_path / "d.db").get_settings()["notify_unreachable_minutes"] == 45
    with pytest.raises(ValueError):
        st.put_settings({"notify_unreachable_minutes": "45"})
    with pytest.raises(ValueError):
        st.put_settings({"notify_unreachable_minutes": True})  # bool is an int subclass: still refused


def test_channels_keep_order_update_partially_and_remove(tmp_path):
    st = Store(tmp_path / "d.db")
    assert st.get_channels() == {}
    st.put_channel("telegram", {"token": "t0k"})
    st.put_channel("ntfy", {"topic": "dw-nick"})
    st.put_channel("telegram", {"chat_id": "123"})  # the token stays
    assert st.get_channels() == {"telegram": {"token": "t0k", "chat_id": "123"}, "ntfy": {"topic": "dw-nick"}}
    st.put_channel("telegram", {"token": ""})  # an empty value clears that field
    assert st.get_channels()["telegram"] == {"token": "", "chat_id": "123"}
    st.delete_channel("telegram")
    assert list(Store(tmp_path / "d.db").get_channels()) == ["ntfy"]
