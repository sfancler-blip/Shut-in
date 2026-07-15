"""Live recon verification + fixture capture. Run from a dev machine, not CI.

Usage: python scripts/probe.py [hollywood|cinemagic|all]
"""
import json
import pathlib
import sys
import time

from curl_cffi import requests

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def get(url, **kw):
    time.sleep(1.2)  # politeness even during recon
    r = requests.get(url, impersonate="chrome", timeout=30, **kw)
    print(f"{r.status_code}  {url}")
    return r


def save(theater, name, content):
    d = FIXTURES / theater
    d.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(d / name, mode, encoding=None if mode == "wb" else "utf-8") as f:
        f.write(content)
    print(f"  saved {theater}/{name}")


def probe_hollywood():
    base = "https://hollywoodtheatre.org"
    save("hollywood-theatre", "robots.txt", get(f"{base}/robots.txt").text)

    # Claim: WP REST event endpoint, datetime encoded in post title, pagination header
    r = get(f"{base}/wp-json/wp/v2/event", params={"per_page": 100, "page": 1})
    save("hollywood-theatre", "events_p1.json", r.text)
    save("hollywood-theatre", "events_headers.json",
         json.dumps({k.lower(): v for k, v in r.headers.items()
                     if k.lower().startswith("x-wp")}))

    events = r.json()
    print(f"  {len(events)} events; sample titles:")
    for e in events[:5]:
        print("   ", e["title"]["rendered"])

    # Claim: show post by de-suffixed slug, poster in yoast og_image
    import re
    seen = set()
    for e in events:
        slug = re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", e["slug"])
        if slug in seen or len(seen) >= 3:
            continue
        seen.add(slug)
        r = get(f"{base}/wp-json/wp/v2/show", params={"slug": slug})
        save("hollywood-theatre", f"show_{slug}.json", r.text)
        shows = r.json()
        og = (shows[0].get("yoast_head_json", {}).get("og_image") if shows else None)
        print(f"  show '{slug}': {'HIT' if shows else 'MISS'}, poster: {bool(og)}")


def probe_cinemagic():
    base = "https://tickets.thecinemagictheater.com"
    save("cinemagic", "robots.txt", get(f"{base}/robots.txt").text)

    r = get(f"{base}/now-showing/")
    save("cinemagic", "now_showing.html", r.text)

    # Pull up to 3 /movie/{slug}/ links straight out of the listing
    import re
    slugs = list(dict.fromkeys(re.findall(r'href="[^"]*/movie/([^/"]+)/?"', r.text)))[:3]
    print(f"  movie slugs found: {slugs}")
    for slug in slugs:
        r = get(f"{base}/movie/{slug}/")
        save("cinemagic", f"movie_{slug}.html", r.text)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("hollywood", "all"):
        probe_hollywood()
    if which in ("cinemagic", "all"):
        probe_cinemagic()
