import json
import pathlib
from datetime import datetime

from shutin.adapters import wordpress_gecko as wg

FIX = pathlib.Path(__file__).parent / "fixtures" / "hollywood-theatre"


def load_payload():
    events = json.loads((FIX / "events_p1.json").read_text(encoding="utf-8"))
    shows = {}
    for f in FIX.glob("show_*.json"):
        slug = f.stem.removeprefix("show_")
        data = json.loads(f.read_text(encoding="utf-8"))
        shows[slug] = data[0] if data else None
    return {"events": events, "shows": shows}


def test_parse_extracts_screenings():
    screenings = wg.parse(load_payload())
    assert len(screenings) > 0
    s = screenings[0]
    assert s.film_title
    assert isinstance(s.starts_at_local, datetime)
    assert s.starts_at_local.tzinfo is None  # adapters emit naive wall-clock


def test_parse_joins_show_metadata():
    screenings = wg.parse(load_payload())
    with_poster = [s for s in screenings if s.poster_url]
    assert with_poster, "no screening picked up a poster from its show fixture"


def test_title_datetime_regex_variants():
    # Extend with every MISS the Task 3 prototype surfaced.
    cases = {
        "Casablanca - 2026-08-03 7:30pm": ("Casablanca", datetime(2026, 8, 3, 19, 30)),
        "The Room - 2026-08-01 12:00pm": ("The Room", datetime(2026, 8, 1, 12, 0)),
        "Alien - 2026-08-02 12:15am": ("Alien", datetime(2026, 8, 2, 0, 15)),
        # Real fixture title: TWO en-dashes, entity-encoded; trailing one is the separator.
        "Severin Presents &#8211; DELICATESSEN &#8211; 2026-08-24 8:00pm": (
            "Severin Presents – DELICATESSEN",
            datetime(2026, 8, 24, 20, 0),
        ),
    }
    for raw, (title, dt) in cases.items():
        got = wg.split_title(raw)
        assert got == (title, dt), f"{raw!r} -> {got}"


def test_unparseable_title_is_skipped_not_fatal():
    payload = {"events": [{"title": {"rendered": "Members Only Mixer"}, "slug": "mixer", "link": ""}], "shows": {}}
    assert wg.parse(payload) == []


def test_parses_all_fixture_events():
    # Live-verified: Task 3 prototype regex matched 100/100 fixture events with 0 misses.
    payload = load_payload()
    screenings = wg.parse(payload)
    assert len(screenings) == len(payload["events"]) == 100


def test_posterless_show_yields_none_not_error():
    # 3 of 4 show fixtures are posterless (featured_media 0 / og_image null) - a genuine
    # content gap, not an adapter error. poster_url must flow through as None.
    payload = load_payload()
    screenings = wg.parse(payload)
    posterless = [s for s in screenings if s.poster_url is None]
    assert posterless, "expected some screenings with poster_url=None to survive parsing"
