# WordPress + gecko-theme (+ Agile Ticketing) extraction recipe

From the Hollywood Theatre recon (`docs/06-site-recon.md`). Applies to WordPress cinema
sites built by Gecko Designs (`gecko-theme`), and generalizes to other WordPress cinema
themes with custom post types. Recon was reconstructed from an existing open-source
scraper of this exact site (`dlowe/flicks`, active 2026) — verify endpoint shapes live.

## Cloudflare first

These sites commonly sit behind Cloudflare **passive TLS fingerprinting**: plain
curl/requests → 403 with any headers; `curl_cffi` with `impersonate="chrome"` → 200.
Do not burn time on header spoofing (a prior scraper of this site died on exactly that);
do not escalate to a browser either — this is still tier 1.

## Source ranking

1. **WP REST API (tier 0/1, best)** — clean JSON, no HTML parsing:
   - Screenings: `GET /wp-json/wp/v2/event?search=YYYY-MM&per_page=100&page=N`
     - one `event` post per screening
     - **datetime is embedded in the post title**: `"FILM TITLE - 2026-08-03 7:30pm"` —
       regex it out; there is no usable datetime meta field
     - paginate until the `X-WP-TotalPages` response header is exhausted; iterate months
       via the `search` param to cover the full published window
   - Film details: `GET /wp-json/wp/v2/show?slug=<slug>` where slug = event slug minus
     its `-YYYY-MM-DD-N[ap]m` suffix → description, permalink,
     **poster at `yoast_head_json.og_image[0].url`**
2. **Theme AJAX endpoint (avoid)** — `/wp-json/gecko-theme/v1/calendar-events?...` needs a
   rotating `x-wp-nonce` harvested from page HTML. Strictly worse than wp/v2; use only if
   wp/v2 gets locked down.
3. **Homepage HTML (fallback)** — `.calendar__events__day[data-calendar-date]` →
   `.calendar__events__day__event` (title in `h3`, times in `.showtime-square`).
4. **Agile Ticketing feed (alternate tier 0)** — where Agile handles ticketing:
   `/websales/feed.ashx?guid=<guid>&showslist=true&format=json` (guid visible in ticket
   URLs, e.g. the `epguid` param). Documented by Agile, refreshed ~10 min. Unverified for
   this site — probe it.

## Field mapping

| RawScreening field | Source |
|---|---|
| film_title | `event` title before the ` - YYYY-MM-DD h:mmam/pm` suffix (HTML-unescape it) |
| starts_at_local | parsed from the `event` title suffix (venue wall-clock) |
| description | `show` post content |
| poster_url | `show` → `yoast_head_json.og_image[0].url` |
| ticket_url | on the `/show/<slug>/` page; `/booking/tickets/<id>` pattern on main domain |
| event_note | series/format info in title or show content when present |

## Known quirks (all observed on Hollywood Theatre)

- Some `show` posts exist in the API but their permalink 404s (series umbrella entries) —
  tolerate missing show pages, keep the screening.
- Some shows live on an affiliated second domain with the same `/show/<slug>/` path
  (moviemadness.org for Hollywood) — config option for an alternate show-page host.
- The Events Calendar plugin feed exists but contains member meetings, not screenings —
  ignore it.
- Titles are HTML-escaped in the API (`&amp;` etc.) — unescape before normalization.

## adapter_config shape (suggested)

```json
{
  "base_url": "https://example.org",
  "event_endpoint": "/wp-json/wp/v2/event",
  "show_endpoint": "/wp-json/wp/v2/show",
  "alt_show_hosts": ["https://moviemadness.org"],
  "impersonate": "chrome",
  "fetch_tier": 1
}
```
