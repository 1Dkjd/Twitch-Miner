from dropwatch.models import Prefs


def test_priority_ignores_case():
    p = Prefs(priority=("Hollow Knight", "Wardogs"))
    assert p.priority_rank("WARDOGS") == 1
    assert p.in_priority("hollow knight")
    assert not p.in_priority("Warframe")


def test_never_ignores_case():
    p = Prefs(never=frozenset({"wardogs"}))
    assert p.in_never("WARDOGS")
    assert not p.in_never("Rust")
