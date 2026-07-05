# Requirements

Captured 2026-07-05 during the initial planning session (requirements interview + site recon).
Items marked **(assumed)** were defaults adopted where no explicit preference was given —
override them by editing this doc.

## Product goal

A website that aggregates movie **showtimes, thumbnails (posters), and descriptions** for
movies playing in the user's area, **sorted by theater**. Data is scraped from each target
theater's own website and refreshed **daily**.

## Confirmed decisions

| Topic | Decision |
|---|---|
| Initial market | Portland, OR (Hollywood Theatre + Cinemagic first) |
| Future scale | Roll out to any city / anyone later — see [Scale posture](#scale-posture) |
| Ingestion runtime | User's own server/VPS, scheduled daily (cron/systemd timer) |
| Budget | Free-first; a paid option requires written cost justification |
| Metadata enrichment | TMDB API **on by default**, admin-toggleable **per theater** |
| Alerting on scraper failure | **Both** email and an auto-filed GitHub issue |
| Data window | Scrape **everything the theater has published** (often 2–6 weeks out) |
| History | **Keep past showtimes forever** (storage cost is negligible; enables "what played last month" features) |
| Stack language | No user preference — chosen by tooling research (see `03-tooling-research.md`) |
| Storage | Decided in planning (see `02-ingestion-architecture.md` § Storage) |

## Scale posture: stable contracts, simple infrastructure

The user asked: *start simple and refactor later, or design for large scale from the start?*

**Recommendation (adopted): make the parts that are expensive to change later scale-ready
now, and keep everything else as simple as possible.**

Cheap now, painful to retrofit — get right on day one:

- **The data model** — theaters, films, screenings, scrape runs — with globally unique IDs,
  per-theater timezones, and no Portland assumptions baked into schema or code.
- **The adapter contract** — every theater is ingested through the same interface
  (`fetch → parse → normalized screenings`), so theater #50 is added the same way as
  theater #2.
- **Idempotent, per-theater scrape jobs** — each theater refreshes independently; one broken
  site never blocks the others.

Genuinely deferrable — do NOT build yet:

- Job queues, worker fleets, Kubernetes, multi-region anything. A daily scrape of even 200
  theaters is a few minutes of sequential work on a small VPS.
- Multi-tenancy/admin UI for third parties adding their own cities.
- Postgres-scale storage (see Storage section for the migration trigger).

## Functional requirements — ingestion (this project phase)

1. **F1 — Per-theater daily refresh.** Every registered theater's showtimes are re-scraped
   at least once per day. Schedule is per-theater (default: early morning local time).
2. **F2 — Fields captured per screening:** film title, start date/time (with theater's
   timezone), ticket/purchase URL when available, screen/format info when available
   (35mm, 3D, etc.), and special-event flags (Q&A, marathon, series name) when available.
3. **F3 — Fields captured per film:** title, description/synopsis, poster/thumbnail URL,
   runtime when available, and the theater's own page URL for the film.
4. **F4 — TMDB enrichment (default on, per-theater toggle):** scraped titles are matched
   against TMDB for canonical posters, descriptions, runtimes, and release metadata.
   Theater-supplied data is preserved separately from enrichment so the toggle is
   reversible and repertory one-offs (e.g. 35mm prints, shorts programs) keep their
   theater-authored copy.
5. **F5 — Upsert semantics.** Re-scraping is idempotent: existing screenings update in
   place (keyed on theater + film + start time), removed screenings are marked cancelled
   rather than deleted, history is never destroyed.
6. **F6 — Scrape ledger.** Every run records: theater, started/finished timestamps, outcome,
   screening count, and error detail on failure. Zero-screenings-found on a previously
   healthy theater is treated as a failure signal (the most common symptom of a silent
   site redesign).
7. **F7 — Alerting.** A failed run (error, or suspicious zero-count) triggers **both** an
   email to the operator and an auto-filed/updated GitHub issue in this repo (one open
   issue per theater, updated on repeat failures, auto-closed on recovery).
8. **F8 — Adding a theater is a guided, repeatable process** driven by the repo's
   `add-theater` skill: recon → platform detection → adapter selection/authoring →
   validation → registration. Target effort: under an hour for a known platform, a few
   hours for a novel site.

## Non-functional requirements

- **N1 — Politeness.** One theater = at most a handful of requests per day. Respect
  robots.txt where feasible, set an honest-but-browserlike cadence (rate-limit ≥1s between
  requests to the same host), and never hammer a site on retry (exponential backoff, max
  3 attempts per run).
- **N2 — Resilience.** One theater's failure never affects another's refresh. Partial data
  (times but no poster) is stored, not discarded.
- **N3 — Free-first.** Prefer open-source, self-hosted tooling. TMDB's API is free for
  non-commercial use. Any paid dependency needs a written justification in
  `03-tooling-research.md`.
- **N4 — Small footprint.** The whole pipeline must run comfortably on a small VPS
  (1–2 GB RAM), including any headless-browser fallback.
- **N5 — Observability.** The scrape ledger (F6) is queryable enough to answer "when did
  theater X last succeed?" without reading logs.

## Legal / etiquette notes (to keep in mind, not legal advice)

- Showtimes are factual data (times, titles) — facts are generally not copyrightable, but
  descriptions and poster images are the theaters'/studios' content. Hotlink posters or use
  TMDB art rather than rehosting theater images wholesale where possible.
- Some theaters (both recon targets included) are community nonprofits; if the site becomes
  popular, reaching out for blessing — or an API token (Veezi theaters can issue one) — is
  both polite and more reliable than scraping.
- Keep scrape volume trivially low (daily, few pages). This is reading the public marquee,
  not bulk extraction.

## Out of scope for this session

Website build, frontend design, user accounts — planned as later phases in
`05-roadmap.md`, not designed here.
