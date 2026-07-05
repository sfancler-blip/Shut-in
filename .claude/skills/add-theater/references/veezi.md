# Veezi Web extraction recipe

From the Cinemagic recon (`docs/06-site-recon.md`). Applies to any theater whose ticketing
runs on Veezi Web. Recon was search-index based — verify each URL shape live before
writing selectors.

## Source ranking

1. **Official Veezi API (tier 0, best)** — `api.<region>.veezi.com/v1/session` and
   `/v1/film`, header `VeeziAccessToken: <token>`. The *theater* must issue the token —
   ask them; small venues often say yes. Clean JSON: films, sessions, screens, times.
2. **Session grid (tier 1)** — `ticketing.<region>.veezi.com/sessions/?siteToken=<token>`.
   One server-rendered page containing every session. Extract the `siteToken` from any
   "Buy" link on the theater's pages; confirm venue name on the grid page before trusting
   a token found anywhere else.
3. **Theater's Veezi Web pages (tier 1)** —
   - `/now-showing/` — currently scheduled films with per-film session times
   - `/show-calendar/` — date-grid view
   - `/movie/<slug>/` — synopsis, poster, that film's sessions
4. Do NOT scrape the marketing site (often Squarespace) — curated series pages there are
   incomplete and unmaintained relative to the ticketing pages.

## Field mapping

| RawScreening field | Source |
|---|---|
| film_title | `/now-showing/` listing or `/movie/<slug>/` h1 |
| starts_at_local | session times on listing/movie pages (theater wall-clock — pass through as-is) |
| description | `/movie/<slug>/` synopsis (also usually in meta description) |
| poster_url | film artwork `<img>` on `/movie/<slug>/` (confirm CDN host live) |
| ticket_url | the session's Buy link (`ticketing.<region>.veezi.com/purchase/...`) |
| format / event_note | session attribute badges when present (e.g. 35mm, subtitled) |

## adapter_config shape (suggested)

```json
{
  "tickets_base_url": "https://tickets.example.com",
  "veezi_region": "uswest",
  "site_token": "<extracted-or-null>",
  "api_token": "<theater-issued-or-null>",
  "fetch_tier": 1
}
```

## Gotchas

- JSON-LD is not typical on Veezi Web — plan for HTML selectors; treat JSON-LD as a bonus.
- Session times on the pages are venue-local wall clock; do not add timezone math here.
- The purchase URLs contain per-session IDs — they make good stable `ticket_url`s but are
  NOT stable dedup keys across re-scrapes; dedup stays on (theater, film, starts_at).
