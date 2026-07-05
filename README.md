# Shut-in

A movie-showtimes aggregator: showtimes, posters, and descriptions for movies playing
nearby, scraped daily from each theater's own website and sorted by theater. Starting
with Portland, OR indie theaters; designed to roll out to any city.

**Status: Phase 0 — planning.** This repo currently contains the planning documentation
and the repeatable onboarding tooling (Claude Code skills). Pipeline code lands in
Phase 1.

## The design in one paragraph

Indie theaters cluster on a handful of ticketing platforms (Veezi, Agile Ticketing,
Filmbot, Eventive, Prekindle, a few WordPress cinema themes), so ingestion is built as
**platform adapters** rather than per-site scrapers — a new theater on a known platform
is a config row, not new code. Fetching uses an escalation ladder: structured
endpoints/APIs first, then `curl_cffi` browser-impersonation HTTP (defeats the Cloudflare
TLS fingerprinting on our hardest known target), then a stealth headless browser for the
rare JS-walled site. Python, SQLite (Postgres when user accounts arrive), daily cron on a
small VPS, TMDB metadata enrichment with a per-theater toggle, and failures alert via
both email and an auto-filed GitHub issue.

## Documentation

| Doc | Contents |
|---|---|
| [docs/01-requirements.md](docs/01-requirements.md) | Confirmed decisions, functional/non-functional requirements, scale posture |
| [docs/02-ingestion-architecture.md](docs/02-ingestion-architecture.md) | Adapter contract, fetch ladder, scheduling, storage decision, alerting |
| [docs/03-tooling-research.md](docs/03-tooling-research.md) | Firecrawl vs Playwright vs curl_cffi research, decision matrix, verdict |
| [docs/04-data-model.md](docs/04-data-model.md) | Schema: regions, theaters, films, screenings, scrape ledger |
| [docs/05-roadmap.md](docs/05-roadmap.md) | Phases: ingestion MVP → website → accounts → design → multi-city |
| [docs/06-site-recon.md](docs/06-site-recon.md) | Recon of hollywoodtheatre.org and thecinemagictheater.com |

## Skills (Claude Code)

| Skill | Use |
|---|---|
| [.claude/skills/add-theater](.claude/skills/add-theater/SKILL.md) | Onboard a new theater: recon → platform detection → fixtures → adapter → validation → registration |
| [.claude/skills/debug-theater-scraper](.claude/skills/debug-theater-scraper/SKILL.md) | Triage a failed refresh, zero-showtimes alert, or wrong data |

## Initial roster

| Theater | Platform | Path |
|---|---|---|
| [Hollywood Theatre](https://hollywoodtheatre.org/) | WordPress (gecko-theme) + Agile Ticketing, behind Cloudflare | WP REST API via curl_cffi |
| [Cinemagic](https://www.thecinemagictheater.com/) | Veezi Web (tickets subdomain) | Server-rendered HTML / Veezi API |

## Next step

Phase 1, step 1 (see [roadmap](docs/05-roadmap.md)): live verification of the recon
findings from an unrestricted network, then pipeline scaffolding.
