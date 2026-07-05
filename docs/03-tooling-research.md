# Tooling research: how we fetch and extract

Research question: for a self-hosted, daily-cron scraping pipeline on a small VPS
(1–2 GB RAM), scaling from 2 indie theaters to ~50+ — Firecrawl vs Playwright vs
TLS-impersonating HTTP clients vs hybrids?

Researched 2026-07-05 via two parallel tracks: a search-corroboration sweep and a
deep-research harness with 3-vote adversarial verification per claim. The planning
sandbox could not fetch pages directly, so most claims come from search-index data,
project docs/issue trackers, and multiple independent write-ups; genuinely single-source
claims are flagged inline, and claims that passed adversarial verification (3-0 votes
against dedicated refuters) are marked **[verified]**. Verify live pricing/versions when
Phase 1 starts.

## Verdict

**Python + `curl_cffi` (Chrome TLS impersonation) + a fast HTML parser (selectolax or
BeautifulSoup), one deterministic adapter per ticketing platform, run as a short-lived
daily cron process.** Escalate per site only on evidence, per the ladder below.

This choice:
- already defeats our hardest known target — hollywoodtheatre.org's Cloudflare TLS
  fingerprinting falls to `curl_cffi impersonate="chrome"`, proven by the actively
  maintained open-source `dlowe/flicks` scraper against this exact site;
- handles Veezi's server-rendered HTML trivially;
- costs $0 and uses tens of MB of RAM — the whole nightly run fits the smallest VPS;
- is what every precedent indie-cinema aggregator independently converged on (see
  Precedents).

## The escalation ladder (per theater, cheapest tier that works)

| Tier | Mechanism | When |
|---|---|---|
| **0 — Structured endpoints** | Platform APIs and feeds via `curl_cffi`: Veezi official API (theater-issued token), WordPress REST API, JSON-LD, iCal/RSS feeds, Agile WebSales JSON feed | Always probe first — both initial targets have one |
| **1 — Impersonating HTTP + HTML parsing** | `curl_cffi` + selectolax/BeautifulSoup on server-rendered pages | The default; most indie theater sites |
| **2 — Headless browser** | **Patchright** (stealth-patched, Playwright-compatible, Python) launched as a fresh process per run, one site at a time, hard timeout + kill safety net | JS-rendered sites or active JS challenges; expect ~0.5–1 GB peak |
| **3 — Paid unblocking API** | ZenRows/Scrapfly/ScrapingBee-class or Firecrawl cloud stealth, pay-as-you-go, scoped to the problem site | Last resort; requires the written cost justification per requirement N3 |

Tier 0 deserves emphasis: for **Veezi theaters, ask the theater for an API token first**
(`api.us.veezi.com` returns clean JSON for films + sessions). Small nonprofits often
cooperate, and an official feed beats any scraper.

Two tier-0 routes passed adversarial verification against primary sources **[verified]**:

- **Agile Ticketing's WebSales Event Feed** is officially documented for third-party
  developers: a plain HTTPS GET to `feed.ashx?guid=<guid>&showslist=true&format=json`
  (GUID comes from the venue's Entry Point config, visible in its ticket URLs), returning
  JSON/XML with name, duration, descriptions, thumbnail + poster images, info link, and a
  showtimes array — the pipeline's entire target schema, deterministically, no browser
  and no LLM. (Whether Hollywood Theatre's specific GUID is enabled remains to be probed
  live.)
- **WordPress "The Events Calendar"** (`/wp-json/tribe/events/v1/events`) is a proven
  adapter route: `dlowe/flicks` scrapes Clinton Street and PAM/Whitsell through it —
  giving us a third ready-made platform adapter for Portland expansion.

## Decision matrix

| | Cost | Cloudflare capability | Fits 1–2 GB VPS | Maintenance per new site | Daily-cron reliability | Long-term viability |
|---|---|---|---|---|---|---|
| **curl_cffi (HTTP + impersonation)** | $0 | Passes passive TLS/JA3 checks (proven on our target); cannot solve JS challenges/Turnstile | ✅ tens of MB | Low — platform adapter + config row | Excellent (plain process) | Strong — active releases into 2026; fingerprint updates ship decoupled from the package (`curl-cffi update`); `wreq`/rnet (Rust) is a healthy fallback |
| **Playwright + stealth (Patchright)** | $0 | Good with patched builds; vanilla Playwright fails modern Cloudflare; a datacenter VPS IP is itself a flag regardless of fingerprint | ⚠ feasible serially (~0.5–1 GB peak, +~500 MB disk) | Medium — browser scripts are more brittle; stealth forks need tracking | Fair — documented zombie-process/memory-growth issues in unattended use; mitigated by fresh-process-per-run + timeouts | Good core (Microsoft); stealth layer churns (Camoufox just exited a year-long hiatus, currently experimental) |
| **Firecrawl self-hosted** | $0 license; needs a 4–8 GB server (5+ Docker services: API, worker, browser service, Redis, RabbitMQ) | ❌ none — Fire-engine (the anti-bot layer) is closed-source, cloud-only | ❌ | Low for markdown dumps, but per-site parsing still needed; AGPL-3.0 | Moderate — you operate a queue + browser cluster | Weak — multiple reports of features migrating cloud-only |
| **Firecrawl cloud** | Free 1k credits/mo, then ~$16–83/mo; stealth (+4) and JSON/LLM extract (+4) stack to ~9 credits/page | Mediocre — Cloudflare failures documented in its own issue tracker (#495, #1363, #2257) even on cloud | ✅ (zero) | Lowest per site, but per-page LLM extraction is the wrong pattern for daily templated pages (below) | Good (their problem) | Vendor-dependent; widespread pricing complaints |

**Firecrawl is ruled out on the evidence, both variants:** self-hosted doesn't fit the VPS
*and* lacks exactly the anti-bot capability we need; cloud costs money to be mediocre at
our one hard problem. This is the written justification requirement N3 asks for — the free
option isn't just cheaper, it's better for this workload.

## LLM-assisted extraction: authoring-time yes, runtime no

Industry experience is consistent: for **stable, templated pages scraped daily**,
per-page LLM extraction (Firecrawl's JSON mode, or raw LLM calls at $0.001–$0.01/page)
adds cost and nondeterminism for nothing — one measured comparison found >100k tokens per
page for extract-every-page vs <10k tokens once per site to generate parser code.

Confirmed from Firecrawl's own docs **[verified]**: JSON-mode structured extraction is a
fixed 5 credits/page (1 base + 4 for the LLM step), and their guidance for known-URL
pages is `/scrape` JSON mode as the cheapest of their extraction endpoints — i.e., even
the cheapest Firecrawl path meters an LLM call on every daily fetch of every page.

Our policy:
- **LLM at adapter-authoring time** (which is exactly what the `add-theater` skill is —
  Claude reads a fixture, writes deterministic parser code and tests).
- **Deterministic parsers in the daily run.** The parser does what it says, every day.
- The "zero screenings from a healthy theater" alert (F6) is the drift detector; a broken
  adapter becomes a GitHub issue and a re-run of the skill, not a silent LLM guess.

## Why Python over TypeScript

**TLS impersonation is the decider.** `curl_cffi` is Python-only and first-class; the Node
story is weak (CycleTLS bridges a Go subprocess with an 81 MB package; `got-scraping` only
adjusts header order/H2 settings, not full JA3; Apify's Rust-based `impit` is promising
but young). Also:

- The parsing ecosystem is a wash at our scale (selectolax is among the fastest parsers
  anywhere; parsing will never be the bottleneck at 50 sites/day).
- Playwright is marginally better in Node, but that's the rare tier-2 path — don't
  optimize for the exception. Patchright ships for Python too.
- Every precedent project in this exact niche is Python.

The website phases (2+) are free to choose their own stack; the ingestion pipeline's
Python choice only meets the website at the database.

## Tool health notes (checked 2026-07)

- **`curl_cffi`** (lexiforest/curl_cffi): v0.15.0 April 2026; Chrome 145/146 + Firefox 147
  fingerprints; HTTP/3 fingerprints; `curl-cffi update` pulls new fingerprints without a
  package upgrade. Known limit: clears *passive* fingerprint checks only — a managed
  challenge/Turnstile page (tell: `cf-mitigated: challenge`, missing `cf_clearance`
  cookie) means escalate to tier 2.
- **Patchright**: patched Chromium removing the `Runtime.enable` CDP leak vanilla
  Playwright exposes; Python + Node. Alternatives: `nodriver`; **Camoufox** (Firefox
  fork) — resumed maintenance under Clover Labs late 2025 after a ~year hiatus, still
  marked experimental; re-evaluate before relying on it.
- **Avoid**: `Python-Tls-Client` (no release in 12+ months, community forks exist because
  it went stale).
- **Playwright on a small VPS**: run as a fresh short-lived process per cron run (never a
  daemon), Chromium only (`playwright install chromium`), `--disable-dev-shm-usage`,
  resource/image blocking, hard timeouts with a `pkill` safety net; documented
  zombie-process issues are all long-lived-daemon patterns.
- A **datacenter IP** (the VPS itself) can trigger challenges independent of any
  fingerprint — if a tier-1 site starts challenging the VPS but not a home connection,
  that's an IP-reputation problem; consider tier 3 for that site rather than fighting it.

## Precedents (independent convergence on this design)

| Project | City | Design |
|---|---|---|
| `dlowe/flicks` (active, 2026) | Portland | Python, curl_cffi, platform adapters keyed to common backends **[verified]**: Hollywood via WP custom `event` post type, Clinton Street + PAM/Whitsell via The Events Calendar REST endpoint |
| `BryantD/film-calendar` | Seattle | Python, per-theater scraper classes behind a common interface, TOML config, iCal/RSS out |
| `Joeboy/cinescrapers` | London | Python, one scraper module per cinema, SQLite, powers filmhose.uk |

Pattern: deterministic plain-HTTP parsers per site/platform; no headless browsers in the
daily path; no paid APIs. Our platform-adapter design is the same idea, one abstraction
level up.

## Flagged uncorroborated claims (from research; do not treat as fact)

- Firecrawl Hobby-tier credit count (sources conflict: 3,000 vs 5,000/mo).
- A separate ~$89/mo Firecrawl "Extract" subscription (single source).
- Specific benchmark figures: Firecrawl "33.69% success on protected sites" / "last of 10
  providers"; "nodriver: zero blocked targets" (single benchmarks; direction consistent
  with Firecrawl's own issue tracker, numbers unverified).
- Chromium per-instance RAM spans 300 MB–1 GB+ across sources depending on tuning.

Key sources: curl_cffi releases/PyPI · Playwright issue tracker (#15400, #6319,
playwright-python #984) · Firecrawl SELF_HOST.md + issues #495/#1363/#2257/#1964 ·
Firecrawl pricing page + third-party pricing analyses · Patchright/Camoufox/nodriver
docs and the ianlpaterson anti-detect benchmark · httptoolkit on Node TLS fingerprinting ·
Crawl4AI & Zyte LLM-extraction guides · Veezi API docs · precedent repos listed above.
