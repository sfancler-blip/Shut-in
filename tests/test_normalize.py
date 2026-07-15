from datetime import datetime

from shutin import normalize


def test_normalize_title():
    cases = {
        "The Godfather": "godfather",
        "Alien (35mm)": "alien",
        "  Casablanca (1942) ": "casablanca",
        "An American Werewolf in London": "american werewolf in london",
        "Akira in 70mm": "akira",
    }
    for raw, want in cases.items():
        assert normalize.normalize_title(raw) == want


def test_to_utc_applies_theater_timezone():
    utc, local = normalize.to_utc(datetime(2026, 7, 14, 19, 30), "America/Los_Angeles")
    assert utc == "2026-07-15T02:30:00Z"  # PDT is UTC-7
    assert local == "2026-07-14 19:30"


def test_to_utc_handles_dst_boundary():
    utc, _ = normalize.to_utc(datetime(2026, 12, 14, 19, 30), "America/Los_Angeles")
    assert utc == "2026-12-15T03:30:00Z"  # PST is UTC-8
