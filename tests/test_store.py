import logging
import os
import stat

from dropsminer.models import Prefs
from dropsminer.redact import RedactFilter
from dropsminer.store import Store
from dropsminer.twitch.session import TwitchSession

S = TwitchSession("tok123", 42, "someone", "dev1", "kd1unb4b3q4t58fwlpcbzcbnm76a8fp", "abcd")


def test_session_round_trip_and_clear(tmp_path):
    st = Store(tmp_path / "drops.db")
    assert st.get_session() is None
    st.set_session(S)
    assert Store(tmp_path / "drops.db").get_session() == S
    st.clear_session()
    assert st.get_session() is None


def test_session_repr_hides_token():
    assert "tok123" not in repr(S)


def test_lists_round_trip_and_order(tmp_path):
    st = Store(tmp_path / "drops.db")
    assert st.get_prefs() == Prefs()
    st.set_lists(["Palia", "Phasmophobia"], {"AION 2"}, ["fav_b", "fav_a"])
    p = st.get_prefs()
    assert p.priority == ("Palia", "Phasmophobia")
    assert p.never == frozenset({"AION 2"})
    assert p.favourites == ("fav_b", "fav_a")
    st.set_lists(["Phasmophobia"], set(), [])
    assert st.get_prefs().priority == ("Phasmophobia",)


def test_mine_badges_setting(tmp_path):
    st = Store(tmp_path / "drops.db")
    st.set_setting("mine_badges", "1")
    assert st.get_prefs().mine_badges is True


def test_events(tmp_path):
    st = Store(tmp_path / "drops.db")
    st.log_event("claimed", {"reward": "Palcat Glasses"})
    kind, _, data = st.recent_events()[0]
    assert (kind, data) == ("claimed", {"reward": "Palcat Glasses"})


def test_db_file_not_world_readable(tmp_path):
    Store(tmp_path / "drops.db")
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(tmp_path / "drops.db").st_mode) == 0o600


def test_redact_filter_hides_token():
    rec = logging.LogRecord("x", logging.INFO, "", 0, "sent OAuth %s", ("tok123",), None)
    assert RedactFilter(lambda: ["tok123"]).filter(rec)
    assert "tok123" not in rec.getMessage()
