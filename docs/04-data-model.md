# Data model

The schema is deliberately scale-ready (no Portland assumptions, per-theater timezones,
stable natural keys) while the storage engine stays simple — see
`02-ingestion-architecture.md` § Storage for the SQLite decision and the Postgres
migration trigger.

## Entity overview

```
region 1──* theater 1──* screening *──1 film ──? tmdb enrichment
                 │
                 └──* scrape_run (ledger)
```

## Tables

### `region`

Cities/metros. Day-one rows: just `portland-or`. Exists so nothing else has to change when
a second city is added.

| column | type | notes |
|---|---|---|
| id | text PK | slug, e.g. `portland-or` |
| name | text | "Portland, OR" |
| timezone | text | IANA, e.g. `America/Los_Angeles` (default for theaters in region) |

### `theater`

| column | type | notes |
|---|---|---|
| id | text PK | slug, e.g. `hollywood-theatre` |
| region_id | text FK | |
| name | text | display name |
| website_url | text | canonical public URL |
| timezone | text | IANA; overrides region default |
| adapter | text | adapter module name, e.g. `wordpress_gecko`, `veezi_web` |
| adapter_config | json | per-site parameters (base URLs, tokens, selectors) |
| tmdb_enrichment | boolean | default `true` — the per-theater admin toggle (F4) |
| enabled | boolean | pause a theater without deleting it |
| created_at / updated_at | timestamp | |

`adapter` + `adapter_config` is what makes onboarding scalable: a new theater on a known
platform is **a config row, not new code**.

### `film`

One row per distinct film/program *as titled by a theater*, deduplicated by normalized
title. Repertory quirks (shorts programs, "Movie + Q&A") stay as their own rows.

| column | type | notes |
|---|---|---|
| id | integer PK | |
| title | text | canonical display title |
| normalized_title | text unique-ish | lowercased, articles/year stripped — dedup key |
| scraped_description | text | theater-authored synopsis (kept verbatim) |
| scraped_poster_url | text | theater/CDN image URL |
| runtime_minutes | int nullable | |
| tmdb_id | int nullable | set by enrichment |
| tmdb_description | text nullable | |
| tmdb_poster_path | text nullable | TMDB image path (render via TMDB image CDN) |
| tmdb_match_confidence | real | 0–1; low-confidence matches flagged for review |
| enrichment_status | text | `pending` / `matched` / `no_match` / `skipped` |

**Display rule** (implemented website-side later): if the theater's `tmdb_enrichment` is on
and match confidence is adequate → TMDB description/poster, else scraped fields. Scraped
and enriched fields are stored side by side so the toggle is reversible (F4).

### `screening`

The core fact table. **Natural key: `(theater_id, film_id, starts_at)`** — this is the
upsert key that makes daily re-scrapes idempotent (F5).

| column | type | notes |
|---|---|---|
| id | integer PK | |
| theater_id | text FK | |
| film_id | integer FK | |
| starts_at | timestamp (UTC) | converted from theater-local at parse time |
| starts_at_local | text | original wall-clock string, e.g. `2026-07-05 19:30` — audit + display |
| ticket_url | text nullable | |
| format | text nullable | `35mm`, `70mm`, `3D`, `open-caption`… |
| event_note | text nullable | series name, Q&A, host, etc. |
| status | text | `scheduled` / `cancelled` / `past` |
| first_seen_run_id | int FK | provenance |
| last_seen_run_id | int FK | screenings absent from the latest successful run get marked `cancelled` if still future — never deleted (F5, history requirement) |

### `scrape_run` (the ledger, F6/N5)

| column | type | notes |
|---|---|---|
| id | integer PK | |
| theater_id | text FK | |
| started_at / finished_at | timestamp | |
| outcome | text | `ok` / `error` / `zero_screenings` |
| screenings_found | int | |
| screenings_new / updated / cancelled | int | change summary for the alert email |
| error_detail | text nullable | truncated traceback / HTTP status |
| alerted | boolean | whether email + GitHub issue fired |

## Timezone policy

All comparisons and storage in UTC; `starts_at_local` preserves what the theater actually
printed. Every conversion uses the **theater's** IANA timezone, never the server's. This is
one of the "cheap now, painful later" scale decisions — multi-city support (and even a
single theater across a DST boundary) falls out for free.

## TMDB matching sketch

1. Normalize scraped title (strip year suffixes, format tags like "(35mm)", series prefixes).
2. `GET /search/movie` with title (+ year when the theater provides one).
3. Score candidates: exact normalized-title match > popularity-weighted fuzzy match.
4. Store `tmdb_match_confidence`; below threshold ⇒ `no_match`, keep scraped fields, flag
   in the run summary for optional manual mapping (`film.tmdb_id` can be hand-set).
5. Cache: a film row that already has `enrichment_status = matched` is not re-queried —
   keeps daily TMDB traffic near zero (free-tier friendly).
