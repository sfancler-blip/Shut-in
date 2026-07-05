# Roadmap

Phase 0 is this session's deliverable. Ordering after Phase 1 reflects dependency, not
calendar commitment — each phase should ship something usable on its own.

## Phase 0 — Planning & scaffolding ✅ (this session)

- Requirements, architecture, data model, tooling research docs (this `docs/` set)
- Repo skills: `add-theater`, `debug-theater-scraper`
- Open item carried forward: the sandbox used for planning could not reach the theater
  sites directly (egress policy), so **Phase 1 starts with a live verification pass** of
  the recon findings (API endpoints, robots.txt, poster CDNs) from the VPS or a dev machine.

## Phase 1 — Ingestion MVP (the current focus)

Goal: two theaters refreshing daily on the VPS, with alerting, for at least a week of
unattended operation.

1. Project scaffolding per `02-ingestion-architecture.md` (package layout, migrations,
   config, CI lint/test).
2. Verify recon findings live; capture HTML/JSON fixtures for both sites into
   `tests/fixtures/` (adapters are developed against fixtures, not live sites).
3. `hollywood-theatre` adapter (WordPress REST API + TLS impersonation) and
   `cinemagic` adapter (Veezi Web HTML).
4. TMDB enrichment with per-theater toggle + match-confidence flagging.
5. Scrape ledger, upsert/cancellation semantics, per-theater cron on the VPS.
6. Alerting: failure email + auto-filed GitHub issue (one open issue per theater,
   auto-close on recovery).
7. Exercise the `add-theater` skill on a **third** Portland theater (e.g. Laurelhurst,
   Academy, Cinema 21, or Clinton St) to prove the onboarding loop, and iterate the skill
   with real feedback (the skill-creator eval loop deferred from Phase 0).

Exit criteria: 3 theaters, 7 consecutive green daily runs, one deliberately induced
failure produces both alert channels.

## Phase 2 — Read-only website

Goal: the public product — showtimes by theater, by day, in the browser.

- Small read API or direct-read layer over the ingestion DB (SQLite is fine at this stage;
  see storage decision).
- Pages: today/this-week by theater (the primary sort per requirements), film detail
  (poster, description, all upcoming screenings across theaters), calendar view.
- Server-rendered, fast, cache-friendly; deploy alongside the scraper on the same VPS.
- SEO basics: schema.org `ScreeningEvent` markup (become the well-structured data source
  we wished the theaters were), per-theater pages with stable URLs.

## Phase 3 — User accounts

Goal: personalization. **This is the storage migration trigger — move SQLite → Postgres
here** (concurrent web writes, sessions, credentials).

- Authentication: pick per stack at the time — self-hosted first (e.g. Auth.js/Lucia-style
  session auth with email magic links or OAuth via Google/GitHub); a hosted provider
  (Clerk/Auth0) only with cost justification, per the free-first rule.
- Features: favorite theaters, watchlist films, "notify me" — a weekly/daily email digest
  of showtimes matching the user's favorites (reuses the alerting mail plumbing).
- Admin role: the per-theater TMDB toggle, adapter config editing, ledger dashboard, and
  manual TMDB match fixing — the "admin" surface referenced in requirements.

## Phase 4 — Frontend design pass

Goal: make it feel like a product, not a database dump.

- Design system: typography/color/poster-grid language, dark mode, mobile-first layouts
  (checking showtimes is a phone activity).
- Accessibility audit (WCAG AA), performance budget (poster image lazy-loading, LCP).
- Nice-to-haves: trailer embeds via TMDB videos, format badges (35mm/70mm), series pages
  (repertory programming is these theaters' identity).

## Phase 5 — Multi-city rollout & scale-out

Goal: "anyone / any city." Only now does the deferred infrastructure get built, and only
as measurements demand.

- Region pages and region-scoped browsing (schema already supports it).
- Onboarding at volume: the `add-theater` skill plus a growing adapter library per
  ticketing platform (Veezi, Agile, Filmbot, Eventive, Prekindle cover a large share of
  US indie theaters).
- Operational upgrades as needed: job parallelism, request-cache layer, status page,
  possibly community-contributed adapter configs.
- Revisit theater partnerships: official Veezi/Agile API tokens where theaters will grant
  them — more reliable than scraping and drops the bot-evasion burden.

## Cross-cutting (starts in Phase 1, never ends)

- Nightly DB backup off the VPS (a single SQLite file makes this trivial early).
- Fixture-based adapter tests in CI so site-format changes are caught by a failing test,
  not a user-facing outage.
- Dependency updates and scrape-etiquette review as targets change their terms.
