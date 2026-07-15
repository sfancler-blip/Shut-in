"""WordPress + gecko-theme + Agile tickets (Hollywood Theatre pattern).

Screenings: /wp-json/wp/v2/event, one post per screening, datetime in the post title.
Film metadata: /wp-json/wp/v2/show?slug=<event slug minus date suffix>, poster via Yoast og_image.
"""
import html
import re
from datetime import datetime

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


def fetch(config: dict) -> dict:
    """Fetch all event pages plus one /show/ lookup per unique underlying film slug.

    Paginates the full /wp-json/wp/v2/event collection (production: ~56 pages, ~5.6k
    events) - do not point this at the live site outside of controlled runs.
    """
    base = config["base_url"].rstrip("/")
    events, page = [], 1
    while True:
        r = http.get(f"{base}/wp-json/wp/v2/event", params={"per_page": 100, "page": page})
        events.extend(r.json())
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
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
        poster = description = film_url = None
        if show:
            og = (show.get("yoast_head_json") or {}).get("og_image") or []
            poster = og[0].get("url") if og else None
            description = _strip_tags(show.get("content", {}).get("rendered", "")) or None
            film_url = show.get("link")
        out.append(
            RawScreening(
                film_title=title,
                starts_at_local=starts,
                description=description,
                poster_url=poster,
                ticket_url=e.get("link"),
                film_url=film_url,
            )
        )
    return out


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()
