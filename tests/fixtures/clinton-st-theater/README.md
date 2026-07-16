# Clinton St Theater fixtures

Captured 2026-07-16 from the live site via `shutin.fetch.get` (curl_cffi, `impersonate="chrome"`,
plain 200s — no Cloudflare challenge observed).

- Source: `GET https://cstpdx.com/wp-json/tribe/events/v1/events?per_page=50&page=1` and
  `...&page=2` (WordPress "The Events Calendar" plugin REST API). No `start_date` param
  passed — the endpoint defaults to upcoming events only (verified: omitting it returns
  99 events starting from "now"; passing `start_date=2020-01-01` returns 1766, i.e. the
  full historical archive — the default-scoped query is what `fetch()` must rely on to
  avoid a `wordpress_gecko`-style full-history pull).
- `events_p1.json` / `events_p2.json`: full raw API envelope (`total`, `total_pages`,
  `events`) for the 2 pages covering all 99 upcoming events at capture time
  (2026-07-15 through 2026-08-21).
- `robots.txt`: `GET https://cstpdx.com/robots.txt`. Only disallows
  `/*tribe-bar-date` (a calendar-view query-string filter); no disallow on `/wp-json/`
  or `/event/` paths.

Notable content in this fixture set (drove adapter + test design):
- `image`, `website` (ticket purchase link, a Square Site checkout page), `url` (the
  cstpdx.com event/film page) present on effectively every event; one event
  ("The Elements of Mutual Aid") has no `website` ticket link — partial data, must not
  break parsing.
- `description` embeds Tribe's schedule/organizer HTML boilerplate around the real copy;
  `excerpt` is the clean paragraph text — adapter uses `excerpt` for `description`.
- No structured "format" field. A `35mm`/`16mm`-style tag is the only format signal
  (`16mm` appears on one event in this fixture set); everything else has no format tag.
- Recurring series (e.g. "The Rocky Horror Picture Show...") are already expanded into
  one event object per showtime by the API — no client-side recurrence expansion needed.
- Titles carry HTML entities (`&#8217;`, `&#8220;` etc.) that must be unescaped.
