import json
import pathlib
from datetime import date, datetime

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

    # show_the-odyssey-in-70mm.json carries acf.format="70mm" (F2: capture format when available).
    odyssey = [s for s in screenings if s.film_title == "THE ODYSSEY in 70mm"]
    assert odyssey, "expected THE ODYSSEY in 70mm screenings to parse"
    assert all(s.format == "70mm" for s in odyssey)

    # The other 3 show fixtures have acf.format="" (empty) -> RawScreening.format stays None,
    # never an empty string.
    no_format = [s for s in screenings if s.poster_url is None]
    assert no_format and all(s.format is None for s in no_format)


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


def test_month_strings_computed_from_frozen_today():
    assert wg._month_strings(2, today=date(2026, 7, 14)) == ["2026-07", "2026-08", "2026-09"]
    assert wg._month_strings(0, today=date(2026, 12, 1)) == ["2026-12"]
    # cross-year rollover
    assert wg._month_strings(2, today=date(2026, 11, 20)) == ["2026-11", "2026-12", "2027-01"]


class _FakeResponse:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    def json(self):
        return self._body


def test_fetch_scopes_to_months_ahead_paginates_and_dedupes(monkeypatch):
    monkeypatch.setattr(wg, "date", type("FrozenDate", (date,), {"today": classmethod(lambda cls: date(2026, 7, 14))}))

    calls = []

    def fake_get(url, *, params=None, **kw):
        calls.append((url, dict(params or {})))
        if url.endswith("/wp-json/wp/v2/event"):
            month = params["search"]
            page = params["page"]
            if month == "2026-07":
                # two pages; event id 1 appears in both this month's search AND next month's,
                # to exercise cross-month dedupe.
                if page == 1:
                    return _FakeResponse(
                        [{"id": 1, "slug": "film-a-2026-07-20-700pm", "title": {"rendered": "Film A - 2026-07-20 7:00pm"}}],
                        headers={"X-WP-TotalPages": "2"},
                    )
                return _FakeResponse(
                    [{"id": 2, "slug": "film-b-2026-07-25-700pm", "title": {"rendered": "Film B - 2026-07-25 7:00pm"}}],
                    headers={"X-WP-TotalPages": "2"},
                )
            if month == "2026-08":
                return _FakeResponse(
                    [{"id": 1, "slug": "film-a-2026-07-20-700pm", "title": {"rendered": "Film A - 2026-07-20 7:00pm"}}],
                    headers={"x-wp-totalpages": "1"},  # lowercase header, case-tolerant lookup
                )
            if month == "2026-09":
                return _FakeResponse([], headers={"X-WP-TotalPages": "1"})
            raise AssertionError(f"unexpected month {month!r}")
        if url.endswith("/wp-json/wp/v2/show"):
            return _FakeResponse([])  # no show fixture needed for this test
        raise AssertionError(f"unexpected url {url!r}")

    monkeypatch.setattr(wg.http, "get", fake_get)

    payload = wg.fetch({"base_url": "https://hollywoodtheatre.org"})

    event_calls = [(url, p) for url, p in calls if url.endswith("/wp-json/wp/v2/event")]
    months_searched = {p["search"] for _, p in event_calls}
    assert months_searched == {"2026-07", "2026-08", "2026-09"}, "must scope to current+months_ahead, not the full collection"
    assert all(p["per_page"] == 100 for _, p in event_calls)

    # page 1 and page 2 both requested for the month whose X-WP-TotalPages said 2
    july_pages = sorted(p["page"] for _, p in event_calls if p["search"] == "2026-07")
    assert july_pages == [1, 2]

    # deduped by id across months: event id 1 was returned by both July and August searches
    assert len(payload["events"]) == 2
    assert {e["id"] for e in payload["events"]} == {1, 2}
