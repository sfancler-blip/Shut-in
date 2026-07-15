# Ingestion architecture

The design bet (from `06-site-recon.md`): indie theaters cluster on a handful of ticketing
platforms, so we build **platform adapters**, not per-site scrapers. Theater #2 on a known
platform is a config row; only a genuinely novel platform costs code.

```
        ┌────────────────────────── per theater, daily ──────────────────────────┐
        │                                                                        │
config ─┤  FETCH            PARSE                NORMALIZE          ENRICH       │  STORE
theater ├─ platform  ──►  platform HTML/JSON ──► RawScreening ──►  TMDB match ──►├─ upsert
row     │  adapter's       → raw records          → canonical      (per-theater  │  + ledger
        │  fetch tier                              Screening/Film   toggle)      │  + alerts
        └────────────────────────────────────────────────────────────────────────┘
```

## The adapter contract

Every theater is ingested through the same interface. An adapter implements exactly two
responsibilities; everything else (storage, enrichment, alerting, scheduling) is shared
pipeline code that adapters never reimplement.

```
Adapter:
    fetch(config)  -> RawPayload     # bytes/JSON from the site, via the fetch ladder
    parse(payload) -> [RawScreening] # platform-specific extraction, no I/O

RawScreening (adapter output — the normalization boundary):
    film_title          str          # as printed by the theater
    starts_at_local     datetime     # theater wall-clock, NO timezone math in adapters
    description         str | None
    poster_url          str | None
    ticket_url          str | None
    runtime_minutes     int | None
    format              str | None   # "35mm", "3D", …
    event_note          str | None   # series, Q&A, …
```

Rules that keep adapters cheap to write and review:

- **`parse` is pure** (payload in, records out, no network) so every adapter is testable
  against checked-in fixtures — a site redesign shows up as a failing fixture test, and
  new fixtures can be recorded with one command.
- Adapters emit **local wall-clock times only**; the shared normalizer applies the
  theater's IANA timezone and converts to UTC. Timezone bugs are pipeline bugs, never
  adapter bugs.
- Adapters take **all site-specific parameters from `theater.adapter_config`** (base URL,
  site token, slug quirks) — one adapter class serves every theater on that platform.
- Partial data is fine (N2): a screening with no poster still flows through.

## Planned adapter library

| Adapter | Platform | Initial theaters | Path (from recon) |
|---|---|---|---|
| `wordpress_gecko` | WordPress + gecko-theme + Agile tickets | Hollywood Theatre | WP REST API (`/wp-json/wp/v2/event`, `show`), Yoast og:image posters |
| `indy` | Indy platform (Quasar/Vue SPA, indy-systems.imgix.net CDN) | Cinemagic | `/now-showing/`, `/movie/{slug}/` — JSON-LD `Movie` block for metadata + `/checkout/showing/{slug}/{sessionId}` anchors for sessions |
| (future) `veezi_web` | Veezi Web ticketing sites | none onboarded yet | `/now-showing/`, `/movie/{slug}/` HTML; optional official API w/ theater-issued token; still serves 200+ cinemas, just not Cinemagic |
| (future) `events_calendar` | WordPress "The Events Calendar" plugin | Clinton Street, PAM/Whitsell | `/wp-json/tribe/events/v1/events` (proven by `dlowe/flicks` on these theaters) |
| (future) `agile_feed` | Agile Ticketing WebSales feed | fallback for Agile theaters | officially documented JSON/XML feed (`feed.ashx?guid=…&showslist=true`) with titles, descriptions, poster images, and showtimes array |
| (future) `filmbot`, `eventive`, `prekindle` | other common indie platforms | as onboarded | authored via the `add-theater` skill |
| (escape hatch) `generic_html` | one-off custom sites | rare | per-site selectors in `adapter_config` |

## The fetch ladder

Site protection varies wildly (Cinemagic: plain HTML; Hollywood: Cloudflare TLS
fingerprinting), so fetching is a per-theater **escalation ladder** — every theater is
served by the *cheapest tier that works*, recorded in its `adapter_config`:

0. **Tier 0 — structured endpoints** (probe first): platform APIs and feeds — Veezi's
   official API (theater-issued token), WordPress REST API, JSON-LD, iCal/RSS, Agile's
   WebSales JSON feed. Both initial targets have one.
1. **Tier 1 — impersonating HTTP client** (default): `curl_cffi` with Chrome TLS/JA3
   impersonation + selectolax/BeautifulSoup parsing. Handles both initial targets,
   including Cloudflare-fronted WordPress. Milliseconds and ~0 RAM per fetch.
2. **Tier 2 — headless browser**: stealth-patched Chromium (Patchright,
   Playwright-compatible) for JS-rendered sites or JS challenges, launched as a fresh
   process per run with hard timeouts. ~0.5–1 GB peak — acceptable because it runs for
   *specific theaters, once a day*, never as the default path.
3. **Tier 3 — paid scraping API** (ZenRows/Scrapfly-class, per problem site): only if
   some future site defeats tiers 0–2, and only with written cost justification per the
   free-first rule (N3).

Tool selection, benchmarks, and the Python-vs-TypeScript decision: see
`03-tooling-research.md`.

### Authoring-time aid for hard sites (not a runtime tier)

When a theater defeats tiers 0–1 and the extraction path is genuinely unclear, a
**self-healing browser harness** (e.g. [browser-use/browser-harness](https://github.com/browser-use/browser-harness)
— a thin CDP-direct harness whose agent writes missing capabilities at runtime) is a
useful *exploration* tool: point it at the stubborn site, let it self-heal its way to the
showtimes, observe how it got there, then **codify that path into a deterministic
adapter** (or a fixed Patchright tier-2 script if a browser is truly required).

This is strictly an **adapter-authoring-time** aid, consistent with the pipeline's core
policy of *LLM at authoring time, deterministic code at runtime* (`03-tooling-research.md`).
It must **never run in the daily cron** — it is browser-heavy and nondeterministic, which
violates the resilience and small-footprint requirements (N2, N4). What ships to
production is the deterministic adapter it helped you discover, not the harness itself.

## Scheduling & execution model

- **One process, sequential theaters** (deliberately boring): a `refresh` command iterates
  enabled theaters, each in its own try/except so one failure never blocks the rest (N2).
  Even at 200 theaters this is minutes of daily work; parallelism is a Phase 5 concern.
- Invoked by **cron/systemd timer on the VPS**, daily in the early morning
  (theater-local), plus `refresh --theater <id>` for manual runs and onboarding.
- **Politeness (N1):** ≥1s spacing between requests to the same host, honest daily
  cadence, exponential backoff with max 3 attempts, and a robots.txt check recorded at
  onboarding time.
- Idempotent by construction: re-running any day's refresh converges to the same state
  (upsert on the natural key, see `04-data-model.md`).

## Storage decision: SQLite now, Postgres at Phase 3

**Decision: SQLite** (WAL mode) for the ingestion MVP and the read-only website phase.

Why: single file on the VPS (backup = copy the file), zero administration, and the write
pattern — one daily batch writer, many readers — is SQLite's happy path. Dozens of
theaters × dozens of screenings × years of history is a few hundred MB at most.

**Migration trigger (decided now so it's not relitigated):** Phase 3 (user accounts)
moves to **Postgres** — concurrent web writes, sessions, and credentials are where SQLite
stops being the right tool. To keep that migration boring:

- All schema changes go through migration files from day one.
- Application code uses portable SQL / a query layer, avoiding SQLite-only features.
- The scrape ledger and screening history migrate as plain rows — nothing exotic.

## TMDB enrichment

Runs as a pipeline stage after normalization, **default on, toggleable per theater**
(`theater.tmdb_enrichment`, F4). Matching + confidence scoring per `04-data-model.md`.
Enrichment failures never block storage of scraped data; matched films are cached so daily
TMDB traffic stays near zero (free-tier friendly). Scraped and TMDB fields are stored side
by side, so flipping the toggle is instant and lossless either direction — repertory
houses whose hand-written program notes beat TMDB boilerplate can opt out per theater.

## Failure detection & alerting (F6, F7)

Every run writes a `scrape_run` ledger row. Two conditions alert:

1. **Hard failure** — unhandled exception, HTTP errors after retries.
2. **Suspicious zero** — a previously healthy theater returns zero screenings. (The classic
   symptom of a silent redesign: the scraper "succeeds" while finding nothing.)

Both fire **two channels**, per requirements:

- **Email** to the operator: theater, error detail, last-good timestamp, run diff summary.
- **GitHub issue** in this repo via API token: one open issue per theater
  (labeled `scraper-broken`, deduped by title), updated with a comment on repeat failures,
  auto-closed with a comment on the next green run. The issue body links the exact
  fixture-recording command and the `debug-theater-scraper` skill, so the repair loop
  starts from the issue itself.

A theater that keeps failing stays enabled but alert-throttled (one issue comment per day,
email only on state change) — no 3 a.m. pager storms over a mom-and-pop marquee.

## Onboarding pipeline (what the `add-theater` skill automates)

1. **Recon**: identify the showtimes source (often a ticketing subdomain, not the
   marketing site), platform, rendering mode, robots.txt.
2. **Platform detection**: match against the adapter library; known platform ⇒ config-only
   onboarding.
3. **Fetch-tier probe**: try tier 1; escalate only on evidence.
4. **Fixture capture**: record live responses into `tests/fixtures/<theater>/`.
5. **Adapter work**: config row for known platforms; new adapter + fixture tests for novel
   ones.
6. **Validation**: parse fixtures → human-readable screening table for eyeball review;
   dry-run against live site; TMDB match-rate report.
7. **Registration**: insert `theater` row, enable, first real run, confirm ledger + alert
   wiring.

Details live in the skill itself: `.claude/skills/add-theater/`.
