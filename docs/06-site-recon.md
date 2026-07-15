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

### Live verification 2026-07-14

- robots.txt: **permits** our paths — `User-agent: *` / `Disallow:` (empty, Yoast block
  only adds a sitemap line). No path restrictions at all.
- Primary path: **confirmed**, with one correction. `GET /wp-json/wp/v2/event` and
  `GET /wp-json/wp/v2/show?slug=…` both return 200 with the documented shape;
  `X-WP-TotalPages`/`X-WP-Total` headers present (56 pages / 5579 events at
  `per_page=100`). **Correction:** the title separator is an HTML-entity-encoded en dash
  (`&#8211;`, decodes to `–`), not a literal hyphen — actual title looks like
  `"Severin Presents &#8211; DELICATESSEN &#8211; 2026-08-24 8:00pm"`. Don't split on
  `" - "`; `html.unescape()` the title then regex for the trailing
  `(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}[ap]m)$` instead. Slug de-suffixing
  (`-\d{4}-\d{2}-\d{2}.*$`) worked as documented.
- Fixtures: `tests/fixtures/hollywood-theatre/` (`events_p1.json`, `events_headers.json`,
  `robots.txt`, 4× `show_*.json`) @ commit (this task's commit).
- Poster source: **confirmed** `yoast_head_json.og_image[0].url`, but only populated when
  the show post has a WordPress featured image (`featured_media != 0`). **Quirk found
  live:** the first 3 shows sampled (all "label presents a reissue" screenings — Severin/
  Vinegar Syndrome/Oscilloscope) have `featured_media: 0` and empty ACF `thumb_image`/
  `main_image` — no poster at all, `og_image: null`. This isn't a fixture artifact, it's
  a real content gap some show posts have; adapters must treat missing poster as valid
  (None), not an error. Added a 4th sample (`show_the-odyssey-in-70mm.json`) which does
  have a featured image, confirming the `og_image` path works when populated.
- plain-curl 403 reproduced: **yes** (`curl -s -o /dev/null -w "%{http_code}"` →403).
- curl_cffi impersonation passes: **yes** (200 on every request, robots.txt included).

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

### Live verification 2026-07-14

- robots.txt: **permits** our paths — `Disallow: /ahoy`, `/graphql`, `/checkout`
  (+ trailing-slash and wildcard variants) only; `/now-showing/` and `/movie/{slug}/` are
  not covered.
- Primary path: **corrected — platform is not Veezi.** `tickets.thecinemagictheater.com`
  is a Quasar/Vue single-page app (`<div id="q-app">`), not server-rendered ASP.NET. No
  string "veezi" appears anywhere in any fetched page. The image CDN is
  `indy-systems.imgix.net` and in-page JS ids/messages ("Contacting Hollywood",
  "Negotiating Distribution Deals", `indy-load-delay-message`) point to a platform
  branded **Indy**, not Veezi — the recon's Veezi inference was wrong for this site.
  **However**, extraction is still easy without a headless browser: every page ships a
  hidden (`position:absolute; z-index:-1000`) SEO/accessibility div containing real
  content — on `/now-showing/`, plain `<h1>/<h2>/<p>/<a>` markup listing every film with
  its next showtime and a link to `/checkout/showing/{slug}/{sessionId}`; on
  `/movie/{slug}/`, full `schema.org/Movie` **microdata** (`itemprop="name"`,
  `description`, `genre`, `duration`, `dateCreated`, `actor`, `director`, `producer`,
  `thumbnailUrl`, `image`) plus every remaining showtime as `<a href="…/checkout/showing/
  {slug}/{id}">Month D, H:MM am/pm</a>`. Verified present and consistent across all 3
  sampled movies (Obsession: 7 showtimes, Hour of the Wolf: 1, The Furious: 3).
  **Note for Task 6:** the listing page alone carries one showtime per film — full
  per-film showtime lists still require the `/movie/{slug}/` fetch, but a plain HTML
  parse (regex or BeautifulSoup on `itemprop=`) is sufficient; no Veezi API, no
  headless browser, no JSON-LD needed.
- Fixtures: `tests/fixtures/cinemagic/` (`robots.txt`, `now_showing.html`, 3×
  `movie_*.html`) @ commit (this task's commit).
- Poster source: **corrected** — image at `itemprop="image"` / `itemprop="thumbnailUrl"`
  (both point to the same `indy-systems.imgix.net` URL in samples seen), inside the
  hidden microdata div — not a Veezi asset path.
- [Cinemagic] JSON-LD present: **no** (zero `<script type="application/ld+json">` blocks
  across `now_showing.html` + all 3 movie pages). Use the `schema.org` **microdata**
  (itemprop attributes) in the hidden div instead — same structured-data benefit, no
  JSON-LD parsing needed, and it's what's actually there.

---

## Strategic takeaway: platforms, not sites

Both targets sit on **shared ticketing platforms** (Agile Ticketing, Veezi) — and most US
indie theaters use one of a handful: **Veezi, Agile Ticketing, Filmbot, Eventive,
Prekindle**, or WordPress themes from a small set of cinema-focused agencies. So the
scalable unit of scraping work is the **platform adapter**, not the site scraper: the
second Veezi theater is a config row (base URL + token), not new code. This is the
foundational bet of `02-ingestion-architecture.md`.
