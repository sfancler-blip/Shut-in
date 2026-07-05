# Site recon — initial targets

Findings from the planning-session recon (2026-07-05). **Caveat:** the planning sandbox's
egress policy blocked direct fetches to the targets, so these findings come from search
indexes, platform documentation, and existing open-source scrapers of these exact sites —
not first-hand HTML inspection. Phase 1 begins with a live verification pass (robots.txt,
endpoint shapes, poster CDNs) before any selector is written.

---

## Hollywood Theatre — hollywoodtheatre.org

**Stack:** WordPress, custom `gecko-theme` (Gecko Designs). Ticketing by **Agile Ticketing
Solutions** white-labeled at `tickets.hollywoodtheatre.org`.

**Bot protection:** Cloudflare TLS-fingerprint challenge. Plain `curl`/`requests` get 403
regardless of headers. Known to work: `curl_cffi` with `impersonate="chrome"` (JA3/TLS
impersonation). This single fact drives the tooling requirement that our HTTP layer must
do browser TLS impersonation.

**Best extraction path — WordPress REST API (clean JSON, no HTML parsing):**

- Screenings: `GET /wp-json/wp/v2/event?search=YYYY-MM&per_page=100&page=N`
  - One `event` post per screening; **datetime is encoded in the post title**
    (`"FILM TITLE - 2026-08-03 7:30pm"`) — parse with regex; paginate via
    `X-WP-TotalPages` header.
- Film pages: `GET /wp-json/wp/v2/show?slug={slug}` (slug = event slug minus the
  `-YYYY-MM-DD-N[ap]m` suffix) → description, permalink, **poster via
  `yoast_head_json.og_image[0].url`**.
- Known quirks: some `show` posts 404 on their permalink (series umbrellas); some shows
  live on affiliated `moviemadness.org` with the same `/show/{slug}/` path.

**Fallbacks, in order:** theme AJAX endpoint `/wp-json/gecko-theme/v1/calendar-events`
(needs a rotating `x-wp-nonce` harvested from page HTML — fragile); homepage HTML
selectors (`.calendar__events__day[data-calendar-date]` → `.calendar__events__day__event`,
times in `.showtime-square`); Agile Ticketing's documented WebSales JSON feed
(`/websales/feed.ashx?guid=…&format=json`, GUID visible in ticket URLs — unverified).

**Reference implementations (open source, same site):**
- `dlowe/flicks` — `flicks/adapters/hollywood.py`: curl_cffi + wp/v2 event/show join +
  Yoast poster extraction. Actively maintained (2026). **Best template.**
- `harrisi/pdxtheaters` — HTML-selector approach (SvelteKit/TS).
- `jasonandmonte/aggregator` — cautionary example: stuck on the 403 using plain requests.

**Difficulty: Medium** (clean data, but TLS impersonation required; datetime-in-title
parsing; event→show join).

---

## Cinemagic — thecinemagictheater.com

**Stack:** two-domain split.
- `www.thecinemagictheater.com` — marketing site (very likely Squarespace); curated series
  pages only, **not** the showtimes source.
- `tickets.thecinemagictheater.com` — the real showtimes site, powered by **Veezi Web**
  (Vista Group's cinema-management platform, used by 200+ independent cinemas):
  - `/now-showing/` and `/show-calendar/` — full listings
  - `/movie/{slug}/` — per-film description, poster, sessions
  - Purchase flow → `ticketing.uswest.veezi.com/purchase/{sessionId}?siteToken=…`

**Rendering:** film titles/synopses appear in search-engine snippets ⇒ server-rendered (at
least in meta tags). Veezi Web pages are historically server-rendered ASP.NET — expect
plain-HTML scraping, no headless browser. JSON-LD presence unknown; plan for HTML
selectors, treat JSON-LD as a bonus.

**Bonus paths:**
- The canonical Veezi session grid `ticketing.uswest.veezi.com/sessions/?siteToken={token}`
  — one page, all sessions; extract the real `siteToken` from any "Buy" link.
- **Veezi official REST API** (`api.us.veezi.com/v1/…`, docs at `/help/Sessions`,
  `/help/Film`): clean JSON but requires a `VeeziAccessToken` issued to the cinema —
  worth *asking the theater for* (small nonprofit, may cooperate).

**Difficulty: Easy–Medium** (small, likely server-rendered, stable Veezi URL structure).

---

## Strategic takeaway: platforms, not sites

Both targets sit on **shared ticketing platforms** (Agile Ticketing, Veezi) — and most US
indie theaters use one of a handful: **Veezi, Agile Ticketing, Filmbot, Eventive,
Prekindle**, or WordPress themes from a small set of cinema-focused agencies. So the
scalable unit of scraping work is the **platform adapter**, not the site scraper: the
second Veezi theater is a config row (base URL + token), not new code. This is the
foundational bet of `02-ingestion-architecture.md`.
