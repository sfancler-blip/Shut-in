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

    # Claim: show post by de-suffixed slug, poster in yoast og_image.
    # Sample the first 3 unique show slugs unconditionally. Some shows (e.g.
    # reissue "label presents" screenings) have no featured image at all, so
    # to guarantee the fixture set includes a poster-bearing sample, keep
    # scanning (bounded to 10 extra attempts) for the first additional slug
    # whose show actually has one. Cap: 4 fixtures, <=13 show requests total.
    import re
    seen = set()
    have_poster = False
    extra_attempts = 0
    max_extra_attempts = 10
    for e in events:
        slug = re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", e["slug"])
        if slug in seen:
            continue
        if len(seen) >= 3:
            if have_poster or extra_attempts >= max_extra_attempts:
                break
            extra_attempts += 1
        seen.add(slug)
        r = get(f"{base}/wp-json/wp/v2/show", params={"slug": slug})
        shows = r.json()
        og = (shows[0].get("yoast_head_json", {}).get("og_image") if shows else None)
        print(f"  show '{slug}': {'HIT' if shows else 'MISS'}, poster: {bool(og)}")
        # Save unconditionally for the first 3; beyond that, only save the
        # first poster-bearing hit (that's the 4th, deterministic, fixture).
        if len(seen) <= 3 or og:
            save("hollywood-theatre", f"show_{slug}.json", r.text)
        if og:
            have_poster = True


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
