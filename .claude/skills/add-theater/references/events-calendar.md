# WordPress "The Events Calendar" plugin extraction recipe

From the Clinton St Theater onboarding (Task 13), the adapter this platform maps to is
`events_calendar` (`shutin/adapters/events_calendar.py`). `docs/02-ingestion-architecture.md`
names Clinton Street and PAM/Whitsell as the two theaters expected on this platform (per
`dlowe/flicks`) — PAM/Whitsell should be config-only against the same adapter once its
`/wp-json/tribe/events/v1/events` shape is confirmed live.

## Cloudflare / fetch tier

Clinton St's `cstpdx.com` returned plain 200s under `curl_cffi impersonate="chrome"` (the
project default tier-1 client) — no challenge page, no TLS-fingerprint 403. Tier 1, same
as the other two theaters. Don't assume this holds for every site on this plugin; recheck
per theater.

## Source: the REST endpoint, not the calendar page

`GET /wp-json/tribe/events/v1/events` — one flat JSON object per screening, no separate
"show"/film post type to join (unlike `wordpress_gecko`). Confirmed live on Clinton St:
`total`/`total_pages`/`events` envelope, max `per_page` is capped server-side at 50
regardless of what's requested.

**Critical gotcha — the default query is already scoped to upcoming events.** Omitting
`start_date` entirely returned 99 events starting from "now"; passing
`start_date=2020-01-01` returned 1766 (the full historical archive, back to 2022).
`fetch()` must paginate the *default* (no date filter) query rather than inventing its
own `start_date`/`end_date` window — passing a wrong window is easy to get wrong and
would either truncate or (worse) silently re-widen to the full archive. This is the
`events_calendar` equivalent of `wordpress_gecko`'s month-scoped `search` param, but
simpler: rely on the plugin's own default instead of re-deriving scoping.

## Field mapping

| RawScreening field | Source |
|---|---|
| film_title | `title` (HTML-unescape — entities like `&#8217;` are common) |
| starts_at_local | `start_date`, format `"YYYY-MM-DD HH:MM:SS"`, already theater wall-clock (matches the `timezone` field on the same object) |
| description | `excerpt`, HTML-tag-stripped — **not** `description`, which embeds Tribe's schedule/organizer template markup around the real copy |
| poster_url | `image.url` (absent on some events — flows through as `None`, not an error) |
| ticket_url | `website` — the actual purchase link (a Square Site page on Clinton St); can be empty/missing (one fixture event had none) |
| film_url | `url` — the theater's own event page, distinct from `ticket_url` |
| format | no structured field exists; best-effort match a `\d+mm`-shaped `tags[].name` (e.g. `"16mm"`) — most events have no such tag, and `format` stays `None` |

## Known quirks (observed on Clinton St)

- Recurring series (e.g. a weekly Rocky Horror screening with different hosts) are
  already expanded by the API into one event object per showtime — no client-side
  recurrence handling needed, and don't dedupe by title.
- `robots.txt` disallows only `/*tribe-bar-date` (a calendar-view query-string filter) —
  does not touch `/wp-json/` or `/event/` paths.
- `categories`/`organizer`/`venue` were empty arrays on every fixture event; don't rely on
  them without reverifying on the next theater.

## adapter_config shape

```json
{
  "base_url": "https://example.org",
  "per_page": 50
}
```

`per_page` is optional (defaults to 50, the plugin's own cap); kept configurable only in
case a future theater's install caps it lower.
