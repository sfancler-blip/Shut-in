# Platform detection fingerprints

Match the theater's *showtimes/ticketing* pages (not the marketing shell) against these
tells. A confident match usually turns onboarding into configuration.

## Veezi (Vista Group) — very common among US indie cinemas

- Ticketing subdomain pages titled `"<Cinema> | <Cinema> | <Page>"` with paths
  `/now-showing/`, `/show-calendar/`, `/movie/<slug>/`
- Purchase links → `ticketing.<region>.veezi.com/purchase/<sessionId>?siteToken=<token>`
  (regions: `uswest`, `useast`, etc.) — the `siteToken` in any Buy link identifies the venue
- Canonical session grid: `ticketing.<region>.veezi.com/sessions/?siteToken=<token>`
- **Official API**: `api.<region>.veezi.com/v1/...` (docs at `/help/Sessions`, `/help/Film`)
  — requires a `VeeziAccessToken` the *cinema* can issue. Ask the theater; this is tier 0.
- Server-rendered ASP.NET; expect tier 1 HTML parsing to work.

## Agile Ticketing Solutions (AgileTix)

- Ticket URLs like `.../websales/pages/info.aspx?evtinfo=...&epguid=<guid>` or
  `prod<N>.agileticketing.net/websales/...`; often white-labeled on a `tickets.` subdomain
- Documented WebSales JSON feed: `/websales/feed.ashx?guid=<guid>&showslist=true&format=json`
  (guid appears in ticket URLs) — probe as tier 0
- Common pairing: a WordPress marketing site holds the actual showtimes calendar and Agile
  only handles purchase (see `wordpress-gecko.md`)

## WordPress cinema sites

- `/wp-json/` in page source; probe `GET /wp-json/wp/v2/types` for custom post types like
  `event`, `show`, `screening`, `film` — a cinema-agency theme usually models showtimes
  as one of these (tier 0: the REST API beats HTML parsing)
- The Events Calendar plugin (`/wp-json/tribe/events/v1/events`) sometimes holds
  screenings — proven route on Clinton Street and PAM/Whitsell (per `dlowe/flicks`),
  but verify it isn't just meetings/private events (on Hollywood Theatre it holds only
  member meetings)
- Known agency themes: `gecko-theme` (Gecko Designs — Hollywood Theatre and other indie
  cinemas). Theme name is visible in asset URLs (`/wp-content/themes/<name>/`)
- Cloudflare in front of WordPress is common: plain curl 403 + browser 200 ⇒ passive TLS
  fingerprinting ⇒ `curl_cffi impersonate="chrome"` (still tier 1)

## Filmbot

- Ticketing pages on `<cinema>.filmbot.com` or embedded Filmbot widgets; JSON API behind
  the widget (inspect XHR). Popular with US microcinemas.

## Eventive

- `<org>.eventive.org` pages; common for festivals and festival-adjacent venues; has a
  real JSON API behind the site (inspect XHR for `api.eventive.org`).

## Prekindle

- Event pages on `prekindle.com` or embeds; JSON often available via the embed endpoints.

## Marketing-shell tells (data is elsewhere — keep following links)

- **Squarespace**: `images.squarespace-cdn.com` assets, `"Page — Site Title"` title
  pattern. Showtimes are almost never natively in Squarespace; find the ticketing link.
- **Wix**: `wixstatic.com` assets, `warmupData` blobs. Same story.
- If showtimes appear only inside an `<iframe>`, scrape the iframe's `src` site directly —
  that's the real platform.

## No match?

Treat as custom: view source for JSON-LD / state blobs / XHR endpoints first, HTML
selectors last. Note which web agency built it (footer credit) — agencies reuse templates,
so today's one-off may be tomorrow's platform adapter.
