import json
import pathlib
from datetime import datetime

from shutin.adapters import events_calendar as ec

FIX = pathlib.Path(__file__).parent / "fixtures" / "clinton-st-theater"


def load_payload():
    events = []
    for f in sorted(FIX.glob("events_p*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        events.extend(data["events"])
    return {"events": events}


def test_parse_extracts_all_fixture_events():
    # fixture: 99 upcoming events across events_p1.json (50) + events_p2.json (49)
    screenings = ec.parse(load_payload())
    assert len(screenings) == 99
    s = screenings[0]
    assert s.film_title
    assert isinstance(s.starts_at_local, datetime)
    assert s.starts_at_local.tzinfo is None  # adapters emit naive wall-clock


def test_earliest_and_latest_dates_found():
    # catches silent pagination truncation - both pages must be walked
    screenings = ec.parse(load_payload())
    starts = sorted(s.starts_at_local for s in screenings)
    assert starts[0] == datetime(2026, 7, 15, 19, 0)
    assert starts[-1] == datetime(2026, 12, 10, 19, 0)


def test_fully_populated_example_checked_field_by_field():
    # fixture event id 9720: "TERAYAMA: EMPEROR OF THE UNDERGROUND (Church of Film)"
    screenings = ec.parse(load_payload())
    s = next(s for s in screenings if "TERAYAMA" in s.film_title)
    assert s.film_title == "TERAYAMA: EMPEROR OF THE UNDERGROUND (Church of Film)"
    assert s.starts_at_local == datetime(2026, 7, 15, 19, 0)
    assert s.description == (
        "Shuji Terayama’s work spanned an incredible array of disciplines, all of which "
        "he graced with his powerful and anarchic visions. The collection includes many "
        "of the master’s greatest short film works which bridge theater, performance art, "
        "poetry, and photography to create haunting, strange and dreamlike worlds."
    )
    assert s.poster_url == "https://cstpdx.com/wp-content/uploads/2026/06/Terayama-Poster.png"
    assert s.ticket_url == (
        "https://cstpdxtickets.square.site/product/terayama-emperor-of-the-underground-"
        "church-of-film-wednesday-july-15th-at-7-00-pm/HHTN4OXRVZOITDZGQPCR2KDM"
    )
    assert s.film_url == "https://cstpdx.com/event/terayama-emperor-of-the-underground-church-of-film-2/"
    assert s.format is None  # no format-shaped tag on this event


def test_missing_ticket_link_flows_through_as_none_not_error():
    # fixture: "The Elements of Mutual Aid" has no `website` field - partial data, not fatal
    screenings = ec.parse(load_payload())
    s = next(s for s in screenings if s.film_title == "The Elements of Mutual Aid")
    assert s.ticket_url is None


def test_format_extracted_from_mm_tag():
    # fixture: two events tagged "16mm"; everything else has no format-shaped tag
    screenings = ec.parse(load_payload())
    mm_titles = [s.film_title for s in screenings if s.format == "16mm"]
    assert len(mm_titles) == 2
    assert all(s.format is None for s in screenings if s.format != "16mm")


def test_title_html_entities_are_unescaped():
    screenings = ec.parse(load_payload())
    titles = [s.film_title for s in screenings]
    assert any("Dorsky’s" in t for t in titles)  # &#8217; decodes to a curly apostrophe
    assert not any("&#8217;" in t or "&#8220;" in t for t in titles)


def test_description_has_no_html_tags():
    screenings = ec.parse(load_payload())
    described = [s for s in screenings if s.description]
    assert described
    assert all("<" not in s.description for s in described)


def test_recurring_series_yield_distinct_screenings_not_deduped():
    # fixture: "The Rocky Horror Picture Show with the Clinton Street Cabaret" is a
    # recurring series the API already expands into one event object per showtime -
    # parse() must not collapse those into one screening.
    screenings = ec.parse(load_payload())
    rocky = [s for s in screenings if "Clinton Street Cabaret" in s.film_title]
    assert len(rocky) == 6
    assert len({s.starts_at_local for s in rocky}) == 6


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_fetch_paginates_through_total_pages_and_merges_events(monkeypatch):
    calls = []

    def fake_get(url, *, params=None, **kw):
        calls.append((url, dict(params or {})))
        assert url.endswith("/wp-json/tribe/events/v1/events")
        if params["page"] == 1:
            return _FakeResponse({"total": 3, "total_pages": 2, "events": [{"id": 1}, {"id": 2}]})
        return _FakeResponse({"total": 3, "total_pages": 2, "events": [{"id": 3}]})

    monkeypatch.setattr(ec.http, "get", fake_get)
    payload = ec.fetch({"base_url": "https://cstpdx.com"})

    assert [e["id"] for e in payload["events"]] == [1, 2, 3]
    pages = sorted(p["page"] for _, p in calls)
    assert pages == [1, 2]
    assert all(p["per_page"] == 50 for _, p in calls)


def test_fetch_does_not_pass_start_date_filter(monkeypatch):
    # Deliberate: the endpoint defaults to upcoming-only when start_date is omitted
    # (verified live - see fixtures README). Passing our own start_date would risk
    # accidentally requesting the full historical archive if the param is ever wrong.
    def fake_get(url, *, params=None, **kw):
        assert "start_date" not in params
        return _FakeResponse({"total": 0, "total_pages": 1, "events": []})

    monkeypatch.setattr(ec.http, "get", fake_get)
    ec.fetch({"base_url": "https://cstpdx.com"})
