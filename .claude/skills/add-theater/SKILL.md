---
name: add-theater
description: Onboard a new movie theater website into the showtimes scraper roster, end to end — recon, platform detection, fetch-tier probing, fixture capture, adapter selection or authoring, validation, and registration with daily refresh. Use this whenever the user wants to add a theater, cinema, or venue to the aggregator, pastes a theater URL and asks to ingest/scrape it, asks to expand to a new city, or says something like "can we get the Laurelhurst in here?" — even if they never use the words "add" or "onboard". Also use it when re-onboarding a theater whose site was redesigned.
---

# Add a theater to the scraper roster

The end state: a `theater` row with a working adapter, checked-in fixtures with passing
parse tests, at least one green `scrape_run` in the ledger, and alerting verified. A new
theater on a **known platform should be a config row, not new code** — always look for
that outcome first.

Authoritative contracts live in the docs; consult them rather than guessing:
`docs/02-ingestion-architecture.md` (adapter contract, fetch ladder, onboarding pipeline),
`docs/04-data-model.md` (schema, natural keys, timezone policy),
`docs/01-requirements.md` (politeness rules N1, free-first rule N3).

## Step 1 — Recon: find where the showtimes actually live

The marketing homepage is frequently NOT the data source. Many indie theaters split into a
brochure site (Squarespace/Wix/WordPress) and a ticketing site on a subdomain
(`tickets.…`, `ticketing.…`, or a platform domain). Follow the "Buy tickets" / "Showtimes"
links to the terminal page and work from there.

Collect, in order:

1. **The showtimes URL(s)** — the page(s) listing every upcoming screening.
2. **View source** on that page and look for structure before assuming HTML-scraping:
   - `application/ld+json` blocks (schema.org `ScreeningEvent` = jackpot)
   - `/wp-json/` references (WordPress REST API available)
   - `__NEXT_DATA__` / framework state blobs with embedded showtime JSON
   - XHR/fetch endpoints in inline JS; iframe embeds pointing at a ticketing platform
3. **Platform fingerprint** — match against `references/platform-detection.md`. This is
   the highest-leverage moment in the whole process: a match usually collapses the
   remaining work to configuration.
4. **robots.txt** for both marketing and ticketing hosts — record what it says in the
   onboarding notes (requirement N1). A disallow on showtimes paths is a decision point
   to raise with the user, not something to silently ignore or silently obey.
5. **Timezone** of the venue (IANA name) and which region row it belongs to.

## Step 2 — Pick the path

- **Known platform** (adapter exists in the library): skip to Step 3, then onboard as
  configuration — new `theater` row with `adapter` + `adapter_config`, fixtures, tests.
- **Known platform, no adapter yet** (it's in `references/platform-detection.md` but
  unbuilt): read that platform's reference file for the extraction recipe, then author
  the adapter as below — it will serve every future theater on that platform, so keep
  site-specific values in config, not code.
- **Novel/custom site**: author a site-specific adapter, but structure it like a platform
  adapter anyway (config-driven selectors) — custom sites from the same web agency often
  recur.

## Step 3 — Probe the fetch ladder (cheapest tier that works)

Try tiers in order; record the winning tier and evidence in `adapter_config`:

- **Tier 0 — structured endpoints**: platform API (Veezi w/ theater-issued token, Agile
  feed), WP REST API, JSON-LD, iCal/RSS. Always probe before parsing HTML.
- **Tier 1 — `curl_cffi` with `impersonate="chrome"`** (the default). A plain-curl 403
  that turns 200 under impersonation = passive TLS fingerprinting, tier 1 still wins.
- **Tier 2 — Patchright headless browser**: only if the showtimes markup genuinely isn't
  in the tier-1 response (JS-rendered) or you get an interactive challenge page (tell:
  `cf-mitigated: challenge` header, Turnstile widget, no `cf_clearance` cookie).
- **Tier 3 — paid API**: stop and write the cost justification required by N3; confirm
  with the user before adding any paid dependency.

Politeness while probing: ≥1s between requests to the same host, and keep total probe
volume to a handful of requests — this is someone's small nonprofit web server.

**Stuck on a hard site?** When tiers 0–1 fail and the extraction path is unclear, a
self-healing browser harness (e.g. `browser-use/browser-harness`) is a good *exploration*
aid: let it self-heal its way to the showtimes on the live site, watch how it does it,
then **codify that path into a deterministic adapter** (or a fixed Patchright tier-2
script). This is an authoring-time aid only — what you commit is the deterministic
adapter, never the harness. It must not end up in the daily cron (browser-heavy,
nondeterministic — violates N2/N4). See `docs/02-ingestion-architecture.md` §
"Authoring-time aid for hard sites".

## Step 4 — Capture fixtures

Record the real responses (HTML/JSON) for every URL the adapter will touch into
`tests/fixtures/<theater-id>/`, with a `README.md` noting capture date, exact source
URLs/params, and anything about the response shape that shaped a design decision (a
missing field, an entity-encoding surprise, a query-scoping default worth relying on).
Actually write this file — the two theaters onboarded before Clinton St skipped it, and
the only way to recover "why does this fixture look like this" later is to re-derive it
from the adapter code, which defeats the point of checking fixtures in at all. Adapters
are developed and tested against fixtures, never against the live site — this keeps
tests fast, deterministic, and polite, and makes future site redesigns show up as a
fixture-test failure with a diffable artifact.

## Step 5 — Adapter work

Honor the adapter contract (`docs/02-ingestion-architecture.md`) — the review checklist:

- `parse()` is **pure**: fixture bytes in, `RawScreening` records out, zero network.
- Emit **theater-local wall-clock times only**. Never convert timezones in an adapter;
  the shared normalizer owns that.
- Every site-specific value (base URL, site token, slug quirks, selectors) comes from
  `adapter_config`, so the next theater on this platform is config-only.
- Partial data flows through (a screening without a poster is still a screening).
- Write parse tests against the fixtures asserting: screening count, one fully-populated
  example checked field-by-field, and the earliest/latest dates found (catches silent
  pagination truncation).

## Step 6 — Validate before registering

1. Parse the fixtures and print a **human-readable screening table** (title, local time,
   format, ticket URL) — eyeball it against the theater's website side by side. Wrong
   AM/PM, missing late shows, and duplicated series entries are all caught here, cheaply.
2. Dry-run against the live site (fetch + parse, no DB writes) and compare counts with
   the fixture run.
3. Check the TMDB match rate. There is no separate report-only mode — `enrich.py` only
   runs for real, inside `refresh`, when `TMDB_API_KEY` is set and the theater's toggle is
   on. That's fine to run as the actual validation step: enrichment failures never block
   storage (F4/N2) and matched films are cached, so it's safe and cheap to just do the
   real run and then query `SELECT enrichment_status, COUNT(*) FROM film GROUP BY
   enrichment_status` (and `tmdb_match_confidence` for the borderline ones) afterward.
   If validating locally without a key, this step is a no-op (`enrichment_status` stays
   `pending` for every film) — the real match-rate check happens on the box where the key
   is configured, as part of Step 7's first real run, not before it.
   Repertory programs ("Shorts Night", "Movie + Q&A") legitimately won't match — that's
   what `enrichment_status = no_match` and the theater-level toggle are for.

## Step 7 — Register and go live

1. Insert the `theater` row (id slug, region, timezone, adapter, config, robots notes,
   `tmdb_enrichment` default true unless the user says otherwise).
2. Run a real refresh for just this theater; confirm a green `scrape_run` ledger row and
   correct row counts in `screening`/`film`.
3. Verify alert wiring by intent, not hope: temporarily point the adapter at a bogus URL
   (or use the failure-injection flag if the pipeline has one), confirm email + GitHub
   issue fire, restore, and confirm the issue auto-closes on the next green run.
4. Confirm the theater is included in the nightly cron scope.

## Definition of done

- [ ] Fixtures + passing parse tests checked in
- [ ] Adapter config-driven; no site literals in shared code
- [ ] Screening table eyeballed against the live site
- [ ] TMDB match report reviewed; toggle set per user preference
- [ ] Green ledger row from a real run; alert round-trip verified
- [ ] robots.txt findings and winning fetch tier recorded in onboarding notes

## References (read when relevant, not preemptively)

- `references/platform-detection.md` — fingerprints for Veezi, Agile, Filmbot, Eventive,
  Prekindle, WordPress cinema themes, and marketing-shell tells (Squarespace/Wix)
- `references/veezi.md` — Veezi Web extraction recipe (from Cinemagic recon)
- `references/wordpress-gecko.md` — WordPress/gecko-theme + Agile recipe (from Hollywood
  Theatre recon), including the Cloudflare TLS story and known API quirks
- `references/events-calendar.md` — WordPress "The Events Calendar" plugin recipe (from
  Clinton St Theater recon): `/wp-json/tribe/events/v1/events` field mapping and the
  default-query upcoming-only scoping gotcha. Applies to Clinton Street now; PAM/Whitsell
  is the next theater expected on this platform (`docs/02-ingestion-architecture.md`).

If you author a new platform adapter and this list doesn't have a matching reference file
yet, write one before moving on (see `events-calendar.md` for the shape) — a fingerprint
in `platform-detection.md` alone isn't enough to make the *next* theater on that platform
config-only; the extraction recipe and quirks need to live somewhere too.
