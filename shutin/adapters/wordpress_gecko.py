"""WordPress + gecko-theme + Agile tickets (Hollywood Theatre pattern).

Screenings: /wp-json/wp/v2/event, one post per screening, datetime in the post title.
Film metadata: /wp-json/wp/v2/show?slug=<event slug minus date suffix>, poster via Yoast og_image.
"""
import html
import re
from datetime import date, datetime

from shutin import fetch as http
from shutin.adapters.base import RawScreening

TITLE_RE = re.compile(
    r"^(?P<title>.+?)\s*[-–]\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[ap])\.?m\.?\s*$",
    re.IGNORECASE,
)
SLUG_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}.*$")


def split_title(raw: str) -> tuple[str, datetime] | None:
    m = TITLE_RE.match(html.unescape(raw).strip())
    if not m:
        return None
    hour = int(m["h"]) % 12 + (12 if m["ap"].lower() == "p" else 0)
    d = datetime.strptime(m["date"], "%Y-%m-%d")
    return m["title"], d.replace(hour=hour, minute=int(m["m"]))


def _month_strings(months_ahead: int, today: date | None = None) -> list[str]:
    """['YYYY-MM', ...] for the current month through current+months_ahead inclusive."""
    start = today or date.today()
    out = []
    for i in range(months_ahead + 1):
        total = start.month - 1 + i
        year = start.year + total // 12
        month = total % 12 + 1
        out.append(f"{year:04d}-{month:02d}")
    return out


def _total_pages(r) -> int:
    # curl_cffi's Headers are case-insensitive, but tolerate a plain-dict stand-in too.
    return int(r.headers.get("X-WP-TotalPages") or r.headers.get("x-wp-totalpages", 1))


def fetch(config: dict) -> dict:
    """Fetch upcoming event pages (scoped by `months_ahead`) plus one /show/ lookup
    per unique underlying film slug.

    Scopes the /wp-json/wp/v2/event query to the current month through
    current+months_ahead (default 2) via the `search` param, instead of pulling the
    entire historical collection (production: ~56 pages, ~5.6k mostly-past events) -
    that would violate both the documented interface and the polite-fetch budget.
    """
    base = config["base_url"].rstrip("/")
    months_ahead = config.get("months_ahead", 2)
    events_by_id: dict = {}
    for month in _month_strings(months_ahead):
        page = 1
        while True:
            r = http.get(
                f"{base}/wp-json/wp/v2/event",
                params={"search": month, "per_page": 100, "page": page},
            )
            for e in r.json():
                events_by_id[e["id"]] = e  # dedupe: overlapping month searches can repeat hits
            if page >= _total_pages(r):
                break
            page += 1
    events = list(events_by_id.values())
    shows = {}
    for e in events:
        slug = SLUG_SUFFIX_RE.sub("", e["slug"])
        if slug in shows:
            continue
        r = http.get(f"{base}/wp-json/wp/v2/show", params={"slug": slug})
        data = r.json()
        shows[slug] = data[0] if data else None
    return {"events": events, "shows": shows}


def parse(payload: dict) -> list[RawScreening]:
    out = []
    for e in payload["events"]:
        split = split_title(e["title"]["rendered"])
        if split is None:
            continue  # non-screening event post (mixer, announcement)
        title, starts = split
        show = payload["shows"].get(SLUG_SUFFIX_RE.sub("", e["slug"]))
        poster = description = film_url = film_format = None
        if show:
            og = (show.get("yoast_head_json") or {}).get("og_image") or []
            poster = og[0].get("url") if og else None
            description = _strip_tags(show.get("content", {}).get("rendered", "")) or None
            film_url = show.get("link")
            film_format = (show.get("acf") or {}).get("format") or None
        out.append(
            RawScreening(
                film_title=title,
                starts_at_local=starts,
                description=description,
                poster_url=poster,
                ticket_url=e.get("link"),
                film_url=film_url,
                format=film_format,
            )
        )
    return out


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()
