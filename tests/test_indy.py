import pathlib
from datetime import datetime

from shutin.adapters import indy

FIX = pathlib.Path(__file__).parent / "fixtures" / "cinemagic"


def load_payload():
    movies = {
        f.stem.removeprefix("movie_"): f.read_text(encoding="utf-8")
        for f in FIX.glob("movie_*.html")
    }
    return {
        "now_showing": (FIX / "now_showing.html").read_text(encoding="utf-8"),
        "movies": movies,
        "fetched_on": "2026-07-14",  # fixtures captured this day; keeps parse deterministic
    }


def test_parse_extracts_screenings():
    screenings = indy.parse(load_payload())
    # fixtures: Obsession 7 showtimes, Hour of the Wolf 1, The Furious 3
    assert len(screenings) == 11
    s = screenings[0]
    assert s.film_title
    assert isinstance(s.starts_at_local, datetime) and s.starts_at_local.tzinfo is None


def test_screenings_carry_jsonld_film_metadata():
    screenings = indy.parse(load_payload())
    assert all(s.description for s in screenings)
    assert all(s.poster_url for s in screenings)
    assert any(s.runtime_minutes for s in screenings)  # JSON-LD Movie duration


def test_ticket_urls_are_checkout_links():
    screenings = indy.parse(load_payload())
    assert all(s.ticket_url and "/checkout/showing/" in s.ticket_url for s in screenings)


def test_year_inference_rolls_forward():
    # "January 5" fetched on 2026-12-20 must resolve to 2027, not 2026
    assert indy.resolve_year("January 5, 7:30 pm", "2026-12-20") == datetime(2027, 1, 5, 19, 30)
    # same-month date stays in the fetch year
    assert indy.resolve_year("December 21, 7:30 pm", "2026-12-20") == datetime(2026, 12, 21, 19, 30)


def test_year_inference_handles_feb29_rollover_into_non_leap_year():
    # 2028 is a leap year (Feb 29 exists); rolling forward lands on 2029, which is not -
    # a naive dt.replace(year=...) would raise ValueError. Must shift to Mar 1 instead.
    assert indy.resolve_year("February 29, 7:00 pm", "2028-06-20") == datetime(2029, 3, 1, 19, 0)


class _FakeResp:
    def __init__(self, text):
        self.text = text


def test_fetch_scopes_movie_fetches_to_now_showing_section(monkeypatch):
    # now_showing.html's hidden div lists "Now Showing" (3 films) followed by a much
    # longer "Coming Soon" section that also links /movie/{slug}/ pages with no
    # bookable showtimes - fetch() must not pull all of those.
    now_showing_html = (FIX / "now_showing.html").read_text(encoding="utf-8")
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if url.endswith("/now-showing/"):
            return _FakeResp(now_showing_html)
        return _FakeResp("<html></html>")

    monkeypatch.setattr(indy.http, "get", fake_get)
    payload = indy.fetch({"base_url": "https://tickets.thecinemagictheater.com"})

    assert set(payload["movies"]) == {"obsession", "hour-of-the-wolf", "the-furious"}
    movie_calls = [c for c in calls if "/movie/" in c]
    assert len(movie_calls) == 3, f"expected 3 Now-Showing movie fetches, got {movie_calls}"
