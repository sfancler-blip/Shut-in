r"""WordPress + The Events Calendar plugin (Clinton St Theater pattern).

Screenings: /wp-json/tribe/events/v1/events, one event object per screening.
Unlike wordpress_gecko there is no separate "show"/film post type to join - each
event embeds its own poster (`image.url`), local start/end wall-clock
(`start_date`/`end_date`), ticket link (`website`, a Square Site checkout page in
Clinton St's case) and event page (`url`). Recurring series (e.g. a weekly Rocky
Horror screening) already arrive as one expanded event object per showtime, so no
client-side recurrence handling is needed.

No structured "format" field exists on this platform; the only signal is a
`\d+mm`-shaped tag (e.g. "16mm"), which we match opportunistically - most events
carry no such tag and format stays None.

fetch() deliberately omits the `start_date` filter: the endpoint defaults to
upcoming-only when it's absent (verified live on Clinton St - omitting it returned
99 events starting from "now"; passing start_date=2020-01-01 returned 1766, the
full historical archive). Relying on that default keeps fetch() from ever pulling
years of past events, the same failure mode wordpress_gecko guards against
explicitly via month-scoped search.
"""
import html
import re
from datetime import datetime

from shutin import fetch as http
from shutin.adapters.base import RawScreening

FORMAT_TAG_RE = re.compile(r"^\d+mm$", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def fetch(config: dict) -> dict:
    base = config["base_url"].rstrip("/")
    per_page = config.get("per_page", 50)
    events = []
    page = 1
    while True:
        r = http.get(
            f"{base}/wp-json/tribe/events/v1/events",
            params={"per_page": per_page, "page": page},
        )
        data = r.json()
        events.extend(data.get("events", []))
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return {"events": events}


def parse(payload: dict) -> list[RawScreening]:
    out = []
    for e in payload["events"]:
        out.append(
            RawScreening(
                film_title=html.unescape(e["title"]),
                starts_at_local=datetime.strptime(e["start_date"], "%Y-%m-%d %H:%M:%S"),
                description=_clean_html(e.get("excerpt")),
                poster_url=(e.get("image") or {}).get("url"),
                ticket_url=e.get("website") or None,
                film_url=e.get("url") or None,
                format=_format_from_tags(e.get("tags") or []),
            )
        )
    return out


def _clean_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = html.unescape(_TAG_RE.sub(" ", text))
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _format_from_tags(tags: list[dict]) -> str | None:
    for tag in tags:
        name = tag.get("name", "")
        if FORMAT_TAG_RE.match(name):
            return name
    return None
