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
