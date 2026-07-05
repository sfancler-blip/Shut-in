---
name: debug-theater-scraper
description: Diagnose and fix a broken or suspicious theater scrape — failed daily refresh, zero-screenings alert, scraper-broken GitHub issue, stale showtimes, missing posters/descriptions, or wrong times on the site. Use this whenever the user reports any theater's data looking wrong or a scrape failing ("Hollywood hasn't updated since Tuesday", "why are there no showtimes for Cinemagic", "this alert email fired") — even if they don't call it a scraper problem. Also use it when a scrape_run ledger row shows outcome error or zero_screenings.
---

# Debug a theater scraper

Goal: a green `scrape_run` for the affected theater, the auto-filed GitHub issue closed by
that green run, and — when the cause was site drift — refreshed fixtures checked in so the
fix is locked by tests.

## Step 1 — Read the evidence before touching anything

- The `scrape_run` ledger for this theater: last green run, first red run, `outcome`
  (`error` vs `zero_screenings`), `error_detail`, and the found/new/updated counts trend.
- The open `scraper-broken` GitHub issue for repeat-failure history.
- The theater's `adapter`, `adapter_config`, and current fetch tier.

`error` and `zero_screenings` are different beasts: an exception points at fetch or code;
zero screenings with a "successful" fetch almost always means **the site changed shape
and the parser is silently matching nothing**.

## Step 2 — Classify by reproducing the fetch

Fetch the theater's source URL(s) exactly as the adapter does (same tier, same
impersonation) and compare against the checked-in fixtures:

| Symptom | Diagnosis | Go to |
|---|---|---|
| HTTP 403/503, challenge page, `cf-mitigated: challenge` header, Turnstile markup | Bot protection changed or IP reputation | Step 3A |
| 200 but body differs structurally from fixture (new markup/renamed endpoints) | Site redesign / platform migration | Step 3B |
| 200, body matches fixture shape, parser still returns nothing/garbage | Parser bug or subtle drift (class rename, date format change) | Step 3B |
| 200 and genuinely no screenings listed on the real site | Not a bug (seasonal closure, renovation) | Step 3C |
| Fetch+parse fine; posters/descriptions wrong or missing | Enrichment problem, not scraping | Step 3D |
| DNS failure / domain parked | Theater changed domains or closed | Step 3B (re-recon) |

## Step 3 — Fix by class

**A. Blocking/protection changed.** Confirm fingerprints are current (`curl-cffi update`
pulls new browser fingerprints without upgrading the package), try a newer impersonation
target, and test the same fetch from a non-VPS network — if home succeeds where the VPS
403s, it's **IP reputation**, not fingerprint: consider tier escalation for this theater
only (per the ladder in `docs/02-ingestion-architecture.md`), never globally. An
interactive JS challenge means tier 2 (Patchright). A paid tier 3 requires the N3 cost
justification and user sign-off.

**B. Site changed.** This is re-onboarding with history: re-run the recon and platform
detection steps of the `add-theater` skill (the platform may have changed — theaters
migrate ticketing providers), re-record fixtures, fix or swap the adapter, and keep the
old fixtures in git history (delete, don't overwrite-in-place silently — the diff
documents what changed). Update parse tests for the new shape.

**C. Legitimately dark.** Verify on the theater's site/socials (closures get announced).
Mark expectation accordingly (e.g. a `dark_until` note in `adapter_config` or disable the
theater) so the zero-screenings alert stops crying wolf, and say so in the GitHub issue
before closing it.

**D. Enrichment issues.** Check `film.enrichment_status` and match confidence for the
affected titles. Repertory one-offs that mismatch to wrong TMDB films: hand-set
`film.tmdb_id` or lower the theater to scraped-only via its `tmdb_enrichment` toggle.
TMDB API errors: check key validity/rate limits; enrichment failures must never block
storing scraped data — if they did, that's the actual bug to fix.

## Step 4 — Prove the fix

1. Parse tests green against the (possibly re-recorded) fixtures.
2. Print the human-readable screening table and eyeball it against the live site.
3. Run a real single-theater refresh; confirm a green ledger row with plausible counts
   (compare against the last historically green run, not just "nonzero").
4. Confirm the GitHub issue auto-closed (or close it with a one-line cause summary —
   future-you triaging the next breakage reads these).

## Step 5 — Capture the lesson

If the root cause was a pattern that will recur (platform-wide markup change, new
Cloudflare behavior, a new platform fingerprint), fold it into the relevant
`add-theater` reference file — the platform recipes are living documents, and the next
onboarding should benefit from this outage.
