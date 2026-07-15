"""Indy cinema platform (indy-systems.imgix.net CDN; Cinemagic pattern).

Quasar/Vue SPA whose raw HTML ships a hidden SSR div. Film metadata comes from the
JSON-LD Movie block (<script type="application/ld+json" data-test-id="schema-org-data">);
showtimes exist ONLY as hidden-div anchors:
    <a href=".../checkout/showing/{slug}/{sessionId}">Month D, H:MM am/pm</a>
JSON-LD has no sessions; anchor text has no year (see resolve_year).
"""
import json
import re
from datetime import date, datetime, timedelta

from selectolax.parser import HTMLParser

from shutin import fetch as http
from shutin.adapters.base import RawScreening

SLUG_RE = re.compile(r'/movie/([^/"?#]+)/?$')
SHOWTIME_TEXT_RE = re.compile(r"^([A-Z][a-z]+ \d{1,2}), (\d{1,2}:\d{2}) ([ap])m$", re.IGNORECASE)
NOW_SHOWING_HEADING = "Now Showing"


def fetch(config: dict) -> dict:
    base = config["base_url"].rstrip("/")
    now_showing = http.get(f"{base}/now-showing/").text
    movies = {}
    for slug in _now_showing_slugs(now_showing):
        movies[slug] = http.get(f"{base}/movie/{slug}/").text
    return {"now_showing": now_showing, "movies": movies,
            "fetched_on": date.today().isoformat()}


def _now_showing_slugs(now_showing_html: str) -> list[str]:
    """Movie slugs from the "Now Showing" section only.

    The hidden div also lists a much longer "Coming Soon" section with the same
    /movie/{slug}/ link shape for films that aren't bookable yet - unscoped matching
    turned every fetch() call into ~24 movie-page GETs (~25s at the >=1s/host politeness
    floor) instead of ~3. Scope to the <p> that immediately follows the "Now Showing" <h2>.
    """
    tree = HTMLParser(now_showing_html)
    for h2 in tree.css("h2"):
        if h2.text(strip=True) != NOW_SHOWING_HEADING:
            continue
        section = h2.next
        if section is None:
            break
        slugs = []
        for a in section.css('a[href*="/movie/"]'):
            m = SLUG_RE.search(a.attributes.get("href") or "")
            if m:
                slugs.append(m.group(1))
        return list(dict.fromkeys(slugs))
    return []


def resolve_year(text: str, fetched_on: str) -> datetime | None:
    """'August 24, 8:00 pm' + fetch date -> naive datetime, rolling into next year
    when the month/day already passed (>30 days before fetch)."""
    m = SHOWTIME_TEXT_RE.match(text.strip())
    if not m:
        return None
    ref = date.fromisoformat(fetched_on)
    md, hm, ap = m.groups()
    hour, minute = (int(x) for x in hm.split(":"))
    hour = hour % 12 + (12 if ap.lower() == "p" else 0)
    dt = datetime.strptime(f"{md} {ref.year}", "%B %d %Y").replace(hour=hour, minute=minute)
    if dt.date() < ref - timedelta(days=30):
        try:
            dt = dt.replace(year=ref.year + 1)
        except ValueError:
            # ponytail: Feb 29 rolling into a non-leap year - shift to Mar 1 rather than
            # pulling in a calendar library for a once-every-few-years edge case.
            dt = dt.replace(month=3, day=1, year=ref.year + 1)
    return dt


def parse(payload: dict) -> list[RawScreening]:
    out = []
    for html_text in payload["movies"].values():
        out.extend(_parse_movie_page(html_text, payload["fetched_on"]))
    return out


def _parse_movie_page(html_text: str, fetched_on: str) -> list[RawScreening]:
    tree = HTMLParser(html_text)
    movie = _jsonld_movie(tree)
    title = movie.get("name", "")
    description = movie.get("description")
    poster = movie.get("image") or movie.get("thumbnailUrl")
    runtime = _iso_duration_minutes(movie.get("duration"))

    out = []
    for a in tree.css('a[href*="/checkout/showing/"]'):
        dt = resolve_year(a.text(strip=True), fetched_on)
        if dt:
            out.append(RawScreening(
                film_title=title,
                starts_at_local=dt,
                description=description,
                poster_url=poster,
                runtime_minutes=runtime,
                ticket_url=a.attributes.get("href"),
            ))
    return out


def _jsonld_movie(tree) -> dict:
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if item.get("@type") == "Movie":
                return item
    return {}


def _iso_duration_minutes(duration: str | None) -> int | None:
    """'PT1H38M' -> 98; None/unparseable -> None."""
    if not duration:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration)
    if not m or not any(m.groups()):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
