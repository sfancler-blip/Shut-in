# Phase 1 — Ingestion MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two Portland theaters (Hollywood Theatre, Cinemagic) refreshing daily on the VPS with TMDB enrichment, a scrape ledger, and dual-channel alerting — then a third theater onboarded via the `add-theater` skill to prove the loop.

**Architecture:** Platform adapters (`fetch → parse → RawScreening[]`) feed a shared pipeline (normalize → TMDB enrich → SQLite upsert + ledger → alerts). Adapters emit theater-local wall-clock times only; `parse` is pure and tested against checked-in fixtures. Fetching uses the escalation ladder — tier 0/1 via `curl_cffi` Chrome impersonation covers both initial targets. See `docs/02-ingestion-architecture.md`.

**Tech Stack:** Python ≥3.12, `curl_cffi`, `selectolax`, stdlib `sqlite3`/`zoneinfo`/`smtplib`, `pytest`, `ruff`. No ORM, no framework, no queue.

## Global Constraints

- Python ≥ 3.12 (needed for modern `zoneinfo` + `sqlite3` behavior; it's what the VPS will run).
- Runtime dependencies: **only** `curl_cffi>=0.15` and `selectolax>=0.3`. Dev: `pytest>=8`, `ruff>=0.5`. Anything else needs written justification (requirement N3, free-first).
- Politeness (N1): ≥1s spacing between requests to the same host, exponential backoff, **max 3 attempts** per request, per run.
- Storage: SQLite, WAL mode, foreign keys ON. **All schema changes via numbered files in `migrations/`.** Portable SQL only (Postgres arrives Phase 3).
- Adapters: `parse` is **pure** (no I/O); adapters emit **naive local wall-clock datetimes** — timezone math happens only in the shared normalizer, using the theater's IANA timezone, never the server's.
- All comparisons/storage in UTC; `starts_at_local` preserves the theater's printed wall-clock string.
- Screenings are **never deleted**: absent-from-latest-run future screenings get `status='cancelled'` (F5).
- LLM at adapter-authoring time only; the daily cron path is 100% deterministic code.
- Secrets/config via environment variables: `SHUTIN_DB`, `TMDB_API_KEY`, `GITHUB_TOKEN`, `GITHUB_REPO` (`owner/name`), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL`.
- Recon caveat: endpoint shapes in `docs/06-site-recon.md` came from search indexes, not live inspection. **Task 2's live-captured fixtures are authoritative** — where fixture reality differs from code written from recon, the fixture wins and the code changes.
- Commit style: conventional commits (`feat:`, `test:`, `chore:`, `docs:`), frequent, per plan steps.

## File structure (locked in here)

```
shutin/                      # package
  __init__.py
  db.py                      # connect(), migrate()
  fetch.py                   # polite impersonating GET (tiers 0/1)
  adapters/
    __init__.py              # ADAPTERS registry
    base.py                  # RawScreening dataclass, Adapter protocol
    wordpress_gecko.py       # Hollywood Theatre
    indy.py                  # Cinemagic (Indy platform — Task 2 corrected the recon's Veezi guess)
  normalize.py               # wall-clock→UTC, title normalization
  store.py                   # film/screening upserts, ledger
  enrich.py                  # TMDB matching
  alerts.py                  # email + GitHub issue
  cli.py                     # refresh / migrate / record-fixtures
migrations/
  001_init.sql               # full schema from docs/04-data-model.md
  002_seed_portland.sql      # region + two theater rows
scripts/
  probe.py                   # Task 2 live-verification probe (kept for re-recon)
prototypes/                  # Task 3 /prototype output (throwaway, gitignored)
tests/
  fixtures/hollywood-theatre/   # events_p1.json, show_<slug>.json, robots.txt
  fixtures/cinemagic/           # now_showing.html, movie_<slug>.html, robots.txt
  test_db.py
  test_fetch.py
  test_wordpress_gecko.py
  test_indy.py
  test_normalize.py
  test_store.py
  test_enrich.py
  test_alerts.py
  test_cli.py
pyproject.toml
.github/workflows/ci.yml
```

---

### Task 1: Project scaffolding, DB layer, migrations, CI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `shutin/__init__.py`, `shutin/db.py`, `migrations/001_init.sql`, `tests/test_db.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `shutin.db.connect(path: str | Path) -> sqlite3.Connection` (Row factory, WAL, FKs on) and `shutin.db.migrate(conn) -> list[str]` (applies pending `migrations/*.sql` in name order, returns applied ids). Every later task gets a DB via `connect(":memory:")` + `migrate()` in tests.

- [ ] **Step 1: Write `pyproject.toml`, `.gitignore`**

```toml
[project]
name = "shutin"
version = "0.1.0"
description = "Movie showtimes aggregator - ingestion pipeline"
requires-python = ">=3.12"
dependencies = [
    "curl_cffi>=0.15",
    "selectolax>=0.3",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.5"]

[project.scripts]
shutin = "shutin.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["shutin", "shutin.adapters"]

[tool.ruff]
line-length = 100
```

`.gitignore`:

```
__pycache__/
*.egg-info/
.venv/
*.db
*.db-wal
*.db-shm
prototypes/
```

Create the venv and install: `python -m venv .venv && .venv/Scripts/pip install -e .[dev]` (Windows dev; on the VPS it's `.venv/bin/pip`).

- [ ] **Step 2: Write the failing DB test**

`tests/test_db.py`:

```python
from shutin import db


def test_migrate_applies_schema_and_is_idempotent():
    conn = db.connect(":memory:")
    applied = db.migrate(conn)
    assert "001_init" in applied

    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"region", "theater", "film", "screening", "scrape_run"} <= tables

    # second run applies nothing
    assert db.migrate(conn) == []


def test_screening_natural_key_is_unique():
    conn = db.connect(":memory:")
    db.migrate(conn)
    conn.execute("INSERT INTO region VALUES ('portland-or', 'Portland, OR', 'America/Los_Angeles')")
    conn.execute(
        "INSERT INTO theater (id, region_id, name, website_url, timezone, adapter, adapter_config)"
        " VALUES ('t1', 'portland-or', 'T1', 'http://x', 'America/Los_Angeles', 'veezi_web', '{}')"
    )
    conn.execute("INSERT INTO film (title, normalized_title) VALUES ('A', 'a')")
    ins = (
        "INSERT INTO screening (theater_id, film_id, starts_at, starts_at_local, status)"
        " VALUES ('t1', 1, '2026-07-15T02:30:00Z', '2026-07-14 19:30', 'scheduled')"
    )
    conn.execute(ins)
    import sqlite3, pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shutin'` (or `AttributeError` once the package exists).

- [ ] **Step 4: Write `shutin/db.py` and `migrations/001_init.sql`**

`shutin/db.py`:

```python
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migration (id TEXT PRIMARY KEY)")
    done = {r["id"] for r in conn.execute("SELECT id FROM schema_migration")}
    applied = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if f.stem not in done:
            conn.executescript(f.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migration VALUES (?)", (f.stem,))
            applied.append(f.stem)
    conn.commit()
    return applied
```

`migrations/001_init.sql` (schema verbatim from `docs/04-data-model.md`):

```sql
CREATE TABLE region (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    timezone TEXT NOT NULL
);

CREATE TABLE theater (
    id              TEXT PRIMARY KEY,
    region_id       TEXT NOT NULL REFERENCES region(id),
    name            TEXT NOT NULL,
    website_url     TEXT NOT NULL,
    timezone        TEXT NOT NULL,
    adapter         TEXT NOT NULL,
    adapter_config  TEXT NOT NULL DEFAULT '{}',
    tmdb_enrichment INTEGER NOT NULL DEFAULT 1,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE film (
    id                    INTEGER PRIMARY KEY,
    title                 TEXT NOT NULL,
    normalized_title      TEXT NOT NULL UNIQUE,
    scraped_description   TEXT,
    scraped_poster_url    TEXT,
    runtime_minutes       INTEGER,
    tmdb_id               INTEGER,
    tmdb_description      TEXT,
    tmdb_poster_path      TEXT,
    tmdb_match_confidence REAL,
    enrichment_status     TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE scrape_run (
    id                   INTEGER PRIMARY KEY,
    theater_id           TEXT NOT NULL REFERENCES theater(id),
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    outcome              TEXT,
    screenings_found     INTEGER NOT NULL DEFAULT 0,
    screenings_new       INTEGER NOT NULL DEFAULT 0,
    screenings_updated   INTEGER NOT NULL DEFAULT 0,
    screenings_cancelled INTEGER NOT NULL DEFAULT 0,
    error_detail         TEXT,
    alerted              INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE screening (
    id                INTEGER PRIMARY KEY,
    theater_id        TEXT NOT NULL REFERENCES theater(id),
    film_id           INTEGER NOT NULL REFERENCES film(id),
    starts_at         TEXT NOT NULL,
    starts_at_local   TEXT NOT NULL,
    ticket_url        TEXT,
    format            TEXT,
    event_note        TEXT,
    status            TEXT NOT NULL DEFAULT 'scheduled',
    first_seen_run_id INTEGER REFERENCES scrape_run(id),
    last_seen_run_id  INTEGER REFERENCES scrape_run(id),
    UNIQUE (theater_id, film_id, starts_at)
);

CREATE INDEX idx_screening_theater_time ON screening (theater_id, starts_at);
CREATE INDEX idx_scrape_run_theater ON scrape_run (theater_id, started_at);
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Add CI**

`.github/workflows/ci.yml`:

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .[dev]
      - run: ruff check .
      - run: python -m pytest -v
```

- [ ] **Step 7: Lint, commit**

Run: `.venv/Scripts/ruff check .` — expected: no errors.

```bash
git add pyproject.toml .gitignore shutin/ migrations/ tests/ .github/
git commit -m "feat: scaffolding, sqlite schema, migration runner, CI"
```

---

### Task 2: Live verification & fixture capture (roadmap step 2 — the "Hollywood verified" gate)

Phase 0's recon was written blind (sandbox egress was blocked). This task probes both sites **live from this dev machine**, confirms or corrects `docs/06-site-recon.md`, and checks in the fixtures every adapter test depends on. **No adapter code is written until this task's fixtures exist.**

**Files:**
- Create: `scripts/probe.py`, `tests/fixtures/hollywood-theatre/*`, `tests/fixtures/cinemagic/*`
- Modify: `docs/06-site-recon.md` (append a "Live verification YYYY-MM-DD" section per site)

**Interfaces:**
- Produces: `tests/fixtures/hollywood-theatre/events_p1.json` (raw WP `event` page-1 body), `events_headers.json` (`{"x-wp-totalpages": ...}`), `show_<slug>.json` (3+ samples incl. one poster-bearing show), `robots.txt`; `tests/fixtures/cinemagic/now_showing.html`, `movie_<slug>.html` (3+ samples), `robots.txt`. Tasks 3, 5, 6 consume these exact filenames.

- [ ] **Step 1: Write `scripts/probe.py`**

```python
"""Live recon verification + fixture capture. Run from a dev machine, not CI.

Usage: python scripts/probe.py [hollywood|cinemagic|all]
"""
import json
import pathlib
import sys
import time

from curl_cffi import requests

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def get(url, **kw):
    time.sleep(1.2)  # politeness even during recon
    r = requests.get(url, impersonate="chrome", timeout=30, **kw)
    print(f"{r.status_code}  {url}")
    return r


def save(theater, name, content):
    d = FIXTURES / theater
    d.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(d / name, mode, encoding=None if mode == "wb" else "utf-8") as f:
        f.write(content)
    print(f"  saved {theater}/{name}")


def probe_hollywood():
    base = "https://hollywoodtheatre.org"
    save("hollywood-theatre", "robots.txt", get(f"{base}/robots.txt").text)

    # Claim: WP REST event endpoint, datetime encoded in post title, pagination header
    r = get(f"{base}/wp-json/wp/v2/event", params={"per_page": 100, "page": 1})
    save("hollywood-theatre", "events_p1.json", r.text)
    save("hollywood-theatre", "events_headers.json",
         json.dumps({k.lower(): v for k, v in r.headers.items()
                     if k.lower().startswith("x-wp")}))

    events = r.json()
    print(f"  {len(events)} events; sample titles:")
    for e in events[:5]:
        print("   ", e["title"]["rendered"])

    # Claim: show post by de-suffixed slug, poster in yoast og_image
    import re
    seen = set()
    for e in events:
        slug = re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", e["slug"])
        if slug in seen or len(seen) >= 3:
            continue
        seen.add(slug)
        r = get(f"{base}/wp-json/wp/v2/show", params={"slug": slug})
        save("hollywood-theatre", f"show_{slug}.json", r.text)
        shows = r.json()
        og = (shows[0].get("yoast_head_json", {}).get("og_image") if shows else None)
        print(f"  show '{slug}': {'HIT' if shows else 'MISS'}, poster: {bool(og)}")


def probe_cinemagic():
    base = "https://tickets.thecinemagictheater.com"
    save("cinemagic", "robots.txt", get(f"{base}/robots.txt").text)

    r = get(f"{base}/now-showing/")
    save("cinemagic", "now_showing.html", r.text)

    # Pull up to 3 /movie/{slug}/ links straight out of the listing
    import re
    slugs = list(dict.fromkeys(re.findall(r'href="[^"]*/movie/([^/"]+)/?"', r.text)))[:3]
    print(f"  movie slugs found: {slugs}")
    for slug in slugs:
        r = get(f"{base}/movie/{slug}/")
        save("cinemagic", f"movie_{slug}.html", r.text)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("hollywood", "all"):
        probe_hollywood()
    if which in ("cinemagic", "all"):
        probe_cinemagic()
```

- [ ] **Step 2: Run the Hollywood probe**

Run: `.venv/Scripts/python scripts/probe.py hollywood`
Expected: HTTP 200s (the 403-without-impersonation claim can be spot-checked with plain `curl -s -o /dev/null -w "%{http_code}" https://hollywoodtheatre.org/wp-json/wp/v2/event` — expect 403), ≥1 page of events, titles matching `"FILM TITLE - YYYY-MM-DD H:MMpm"`, ≥1 show with a Yoast poster.

**If reality differs from recon** (endpoint 404s, title format differs, posters elsewhere): capture whatever the real shape is into fixtures, and record the correction in `docs/06-site-recon.md`. The fallback order from recon: gecko-theme AJAX endpoint → homepage HTML selectors → Agile WebSales feed. Probe fallbacks only if the primary path fails.

- [ ] **Step 3: Run the Cinemagic probe**

Run: `.venv/Scripts/python scripts/probe.py cinemagic`
Expected: 200s, server-rendered HTML with film titles visible in `now_showing.html`, ≥1 movie page with description/poster/session times. Also note whether JSON-LD (`application/ld+json`) is present — if so, record it; it may beat HTML selectors in Task 6.

- [ ] **Step 4: Verify robots.txt permits us**

Read both saved `robots.txt` files. Expected: no `Disallow` covering our paths for `*`. If disallowed: STOP, flag to the user — etiquette policy (N1) says respect it; the theater-partnership route (docs/03 tier 0) becomes the path.

- [ ] **Step 5: Update `docs/06-site-recon.md`**

Append to each site's section:

```markdown
### Live verification 2026-07-14

- robots.txt: [permits/denies] our paths
- Primary path: [confirmed as recon described / corrected: <what changed>]
- Fixtures: tests/fixtures/<theater>/ @ <commit>
- Poster source: [confirmed yoast og_image / actual location]
- [Hollywood] plain-curl 403 reproduced: [yes/no]; curl_cffi impersonation passes: [yes/no]
- [Cinemagic] JSON-LD present: [yes/no]
```

- [ ] **Step 6: Commit**

```bash
git add scripts/probe.py tests/fixtures/ docs/06-site-recon.md
git commit -m "feat: live recon verification + checked-in fixtures for both theaters"
```

---

### Task 3: /prototype — ingestion demo on verified Hollywood data (user-requested gate)

**Only after Task 2 confirms Hollywood.** Invoke the `prototype` skill (`/prototype`). Design question the prototype answers: **"Does the recon extraction path — event list → datetime-in-title regex → de-suffixed slug → show join → Yoast poster — actually produce a correct, complete screening table from real data?"** This de-risks Task 5's adapter before any production code is written.

**Files:**
- Create: `prototypes/hollywood-ingest-demo/demo.py` (throwaway — `prototypes/` is gitignored; the *learnings* land in Task 5 and, if the recon story changed, in `docs/06-site-recon.md`)

**Interfaces:**
- Consumes: `tests/fixtures/hollywood-theatre/*` from Task 2.
- Produces: nothing durable — a printed screening table and a verdict. Task 5 may crib parsing snippets from it but writes its code fresh, test-first.

- [ ] **Step 1: Invoke the prototype skill** with the design question above. The prototype (guideline, not spec — it's throwaway):

```python
"""Throwaway demo: fixtures -> screening table for Hollywood Theatre."""
import json
import pathlib
import re

FIX = pathlib.Path(__file__).resolve().parents[2] / "tests/fixtures/hollywood-theatre"
TITLE_RE = re.compile(
    r"^(?P<title>.+?)\s*[-–]\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[ap])\.?m\.?$",
    re.IGNORECASE,
)

events = json.loads((FIX / "events_p1.json").read_text(encoding="utf-8"))
rows, misses = [], []
for e in events:
    title = e["title"]["rendered"]
    m = TITLE_RE.match(title)
    if not m:
        misses.append(title)
        continue
    h = int(m["h"]) % 12 + (12 if m["ap"].lower() == "p" else 0)
    slug = re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", e["slug"])
    rows.append((m["date"], f"{h:02d}:{m['m']}", m["title"], slug))

for r in sorted(rows):
    print(f"{r[0]}  {r[1]}  {r[2]:<45} [{r[3]}]")
print(f"\n{len(rows)} parsed, {len(misses)} unparsed")
for t in misses:
    print("  MISS:", t)

# join demo: poster + description for the first 3 distinct slugs with a saved show fixture
for f in sorted(FIX.glob("show_*.json"))[:3]:
    shows = json.loads(f.read_text(encoding="utf-8"))
    if shows:
        s = shows[0]
        og = s.get("yoast_head_json", {}).get("og_image", [])
        print(f"\n{f.stem}: poster={'yes' if og else 'NO'} desc={'yes' if s.get('content') else 'NO'}")
```

- [ ] **Step 2: Run it and eyeball the output against the real site**

Run: `.venv/Scripts/python prototypes/hollywood-ingest-demo/demo.py`
Verify: the printed table matches hollywoodtheatre.org's public calendar for the same dates (titles, dates, times). Unparsed-title count should be near zero; each MISS is a title format the Task 5 regex must also handle (multi-line events, "Movie + Q&A", series prefixes) — list them in the demo output and carry them into Task 5's test cases.

- [ ] **Step 3: Show the user the screening table** and record the verdict (extraction path holds / adjusted how). **This is the gate for Task 5.** No commit — the prototype is throwaway.

---

### Task 4: Adapter contract + polite fetch layer

**Files:**
- Create: `shutin/adapters/__init__.py`, `shutin/adapters/base.py`, `shutin/fetch.py`, `tests/test_fetch.py`

**Interfaces:**
- Produces:
  - `shutin.adapters.base.RawScreening` — frozen dataclass: `film_title: str`, `starts_at_local: datetime` (naive), `description: str | None = None`, `poster_url: str | None = None`, `ticket_url: str | None = None`, `runtime_minutes: int | None = None`, `format: str | None = None`, `event_note: str | None = None`, `film_url: str | None = None`.
  - `shutin.adapters.ADAPTERS: dict[str, module]` — registry keyed by `theater.adapter` value.
  - `shutin.fetch.get(url, *, params=None, min_gap=1.0, attempts=3) -> Response` — curl_cffi Chrome-impersonated GET with ≥`min_gap`s per-host spacing, exponential backoff on 5xx/network errors, immediate raise on 4xx, 30s timeout.

- [ ] **Step 1: Write the failing fetch test**

`tests/test_fetch.py` (monkeypatch the transport — no network in CI):

```python
import time

import pytest

from shutin import fetch


class FakeResp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_retries_on_5xx_then_succeeds(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResp(500 if len(calls) < 3 else 200)

    monkeypatch.setattr(fetch.requests, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    r = fetch.get("https://example.com/a")
    assert r.status_code == 200
    assert len(calls) == 3


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(fetch.requests, "get", lambda url, **kw: FakeResp(500))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        fetch.get("https://example.com/a", attempts=3)


def test_4xx_raises_immediately(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResp(403)

    monkeypatch.setattr(fetch.requests, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    fetch._last_hit.clear()  # isolate from prior tests' per-host state
    with pytest.raises(RuntimeError):
        fetch.get("https://example.com/a")
    assert len(calls) == 1


def test_same_host_spacing(monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetch.requests, "get", lambda url, **kw: FakeResp(200))
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    fetch._last_hit.clear()
    fetch.get("https://example.com/a")
    fetch.get("https://example.com/b")
    assert sum(sleeps) >= 0.5  # second same-host call waited
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_fetch.py -v`
Expected: FAIL — `shutin.fetch` doesn't exist.

- [ ] **Step 3: Implement**

`shutin/fetch.py`:

```python
import time
from urllib.parse import urlparse

from curl_cffi import requests

_last_hit: dict[str, float] = {}


def get(url, *, params=None, min_gap=1.0, attempts=3, **kw):
    """Polite impersonating GET: >=min_gap s per host, backoff on 5xx, raise fast on 4xx."""
    host = urlparse(url).netloc
    last_err = None
    for attempt in range(attempts):
        gap = _last_hit.get(host, -min_gap) + min_gap - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        _last_hit[host] = time.monotonic()
        try:
            r = requests.get(url, params=params, impersonate="chrome", timeout=30, **kw)
        except Exception as e:  # network-level failure -> retryable
            last_err = e
        else:
            if r.status_code < 500:
                r.raise_for_status()  # 4xx raises here, no retry
                return r
            last_err = RuntimeError(f"HTTP {r.status_code} from {url}")
        if attempt < attempts - 1:  # no dead sleep before the terminal raise
            time.sleep(2**attempt)
    raise last_err
```

`shutin/adapters/base.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RawScreening:
    """Adapter output. starts_at_local is NAIVE theater wall-clock - no tz math in adapters."""

    film_title: str
    starts_at_local: datetime
    description: str | None = None
    poster_url: str | None = None
    ticket_url: str | None = None
    runtime_minutes: int | None = None
    format: str | None = None
    event_note: str | None = None
    film_url: str | None = None


class Adapter(Protocol):
    def fetch(self, config: dict) -> Any: ...
    def parse(self, payload: Any) -> list[RawScreening]: ...
```

`shutin/adapters/__init__.py`:

```python
from shutin.adapters import indy, wordpress_gecko

ADAPTERS = {
    "wordpress_gecko": wordpress_gecko,
    "indy": indy,
}
```

(Temporarily create empty `shutin/adapters/wordpress_gecko.py` and `shutin/adapters/indy.py` stubs — filled by Tasks 5–6.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_fetch.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Lint + commit**

```bash
git add shutin/ tests/test_fetch.py
git commit -m "feat: adapter contract (RawScreening) and polite impersonating fetch layer"
```

---

### Task 5: `wordpress_gecko` adapter (Hollywood Theatre)

Written against Task 2's fixtures, informed by Task 3's prototype (title-regex misses become test cases here). If fixture shapes contradicted recon, follow the fixtures.

> **Amended after task review (2026-07-14):** the Step 3 template below has two gaps vs this plan's own contract, fixed in implementation: (1) `fetch` must honor `months_ahead` (default 2) by iterating `?search=YYYY-MM` month filters instead of paginating the entire historical event collection (~56 pages) — required by the documented interface and politeness (N1); (2) `parse` must map `show["acf"]["format"]` → `RawScreening.format` when present (F2 "when available"; the Odyssey fixture proves the field exists). The committed adapter is authoritative over the template below.

**Files:**
- Create: `shutin/adapters/wordpress_gecko.py` (replace stub), `tests/test_wordpress_gecko.py`

**Interfaces:**
- Consumes: `fetch.get` (Task 4), fixtures `tests/fixtures/hollywood-theatre/*`.
- Produces: module with `fetch(config: dict) -> dict` returning `{"events": [<wp event json>...], "shows": {slug: <wp show json or None>}}`, and `parse(payload: dict) -> list[RawScreening]`. `config` keys: `base_url` (e.g. `"https://hollywoodtheatre.org"`), optional `months_ahead` (int, default 2).

- [ ] **Step 1: Write the failing parse test against fixtures**

`tests/test_wordpress_gecko.py`:

```python
import json
import pathlib
from datetime import datetime

from shutin.adapters import wordpress_gecko as wg

FIX = pathlib.Path(__file__).parent / "fixtures" / "hollywood-theatre"


def load_payload():
    events = json.loads((FIX / "events_p1.json").read_text(encoding="utf-8"))
    shows = {}
    for f in FIX.glob("show_*.json"):
        slug = f.stem.removeprefix("show_")
        data = json.loads(f.read_text(encoding="utf-8"))
        shows[slug] = data[0] if data else None
    return {"events": events, "shows": shows}


def test_parse_extracts_screenings():
    screenings = wg.parse(load_payload())
    assert len(screenings) > 0
    s = screenings[0]
    assert s.film_title
    assert isinstance(s.starts_at_local, datetime)
    assert s.starts_at_local.tzinfo is None  # adapters emit naive wall-clock


def test_parse_joins_show_metadata():
    screenings = wg.parse(load_payload())
    with_poster = [s for s in screenings if s.poster_url]
    assert with_poster, "no screening picked up a poster from its show fixture"


def test_title_datetime_regex_variants():
    # Extend with every MISS the Task 3 prototype surfaced.
    cases = {
        "Casablanca - 2026-08-03 7:30pm": ("Casablanca", datetime(2026, 8, 3, 19, 30)),
        "The Room - 2026-08-01 12:00pm": ("The Room", datetime(2026, 8, 1, 12, 0)),
        "Alien - 2026-08-02 12:15am": ("Alien", datetime(2026, 8, 2, 0, 15)),
    }
    for raw, (title, dt) in cases.items():
        got = wg.split_title(raw)
        assert got == (title, dt), f"{raw!r} -> {got}"


def test_unparseable_title_is_skipped_not_fatal():
    payload = {"events": [{"title": {"rendered": "Members Only Mixer"}, "slug": "mixer", "link": ""}], "shows": {}}
    assert wg.parse(payload) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_wordpress_gecko.py -v`
Expected: FAIL — stub module has no `parse`.

- [ ] **Step 3: Implement**

`shutin/adapters/wordpress_gecko.py`:

```python
"""WordPress + gecko-theme + Agile tickets (Hollywood Theatre pattern).

Screenings: /wp-json/wp/v2/event, one post per screening, datetime in the post title.
Film metadata: /wp-json/wp/v2/show?slug=<event slug minus date suffix>, poster via Yoast og_image.
"""
import html
import re
from datetime import datetime

from shutin import fetch
from shutin.adapters.base import RawScreening

TITLE_RE = re.compile(
    r"^(?P<title>.+?)\s*[-–]\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?P<ap>[ap])\.?m\.?\s*$",
    re.IGNORECASE,
)
SLUG_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}.*$")


def split_title(raw: str) -> tuple[str, datetime] | None:
    m = TITLE_RE.match(html.unescape(raw).strip())
    if not m:
        return None
    hour = int(m["h"]) % 12 + (12 if m["ap"].lower() == "p" else 0)
    d = datetime.strptime(m["date"], "%Y-%m-%d")
    return m["title"], d.replace(hour=hour, minute=int(m["m"]))


def fetch_payload(config: dict) -> dict:
    base = config["base_url"].rstrip("/")
    events, page = [], 1
    while True:
        r = fetch.get(f"{base}/wp-json/wp/v2/event", params={"per_page": 100, "page": page})
        events.extend(r.json())
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
    shows = {}
    for e in events:
        slug = SLUG_SUFFIX_RE.sub("", e["slug"])
        if slug in shows:
            continue
        r = fetch.get(f"{base}/wp-json/wp/v2/show", params={"slug": slug})
        data = r.json()
        shows[slug] = data[0] if data else None
    return {"events": events, "shows": shows}


fetch_ = fetch_payload  # keep module-level name `fetch` free for the shutin.fetch import


def parse(payload: dict) -> list[RawScreening]:
    out = []
    for e in payload["events"]:
        split = split_title(e["title"]["rendered"])
        if split is None:
            continue  # non-screening event post (mixer, announcement)
        title, starts = split
        show = payload["shows"].get(SLUG_SUFFIX_RE.sub("", e["slug"]))
        poster = description = film_url = None
        if show:
            og = show.get("yoast_head_json", {}).get("og_image") or []
            poster = og[0].get("url") if og else None
            description = _strip_tags(show.get("content", {}).get("rendered", "")) or None
            film_url = show.get("link")
        out.append(
            RawScreening(
                film_title=title,
                starts_at_local=starts,
                description=description,
                poster_url=poster,
                ticket_url=e.get("link"),
                film_url=film_url,
            )
        )
    return out


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()
```

Note the registry (Task 4) calls `module.fetch` / `module.parse`; expose them:

```python
def __getattr__(name):
    if name == "fetch":
        return fetch_payload
    raise AttributeError(name)
```

*(Simpler alternative if `__getattr__` reads too clever: rename the import — `from shutin import fetch as http` — and define plain module functions `fetch(config)` / `parse(payload)`. Prefer that; it's the boring option: implementer's choice, keep the registry contract `module.fetch(config)` / `module.parse(payload)`.)*

- [ ] **Step 4: Run tests, iterate selectors/regex against the real fixtures until green**

Run: `.venv/Scripts/python -m pytest tests/test_wordpress_gecko.py -v`
Expected: 4 PASS. Any fixture title that fails `split_title` is either a new regex variant (add to the test table) or a legitimately non-screening post (assert it's skipped).

- [ ] **Step 5: Commit**

```bash
git add shutin/adapters/wordpress_gecko.py tests/test_wordpress_gecko.py
git commit -m "feat: wordpress_gecko adapter (Hollywood Theatre) with fixture tests"
```

---

### Task 6: `indy` adapter (Cinemagic)

**Amended after Task 2 live verification (2026-07-14):** Cinemagic is NOT on Veezi — it runs an "Indy"-branded Quasar/Vue SPA (CDN `indy-systems.imgix.net`) whose raw HTML ships a hidden SSR div. Structured data facts (from checked-in fixtures, authoritative):
- Every page has `<script type="application/ld+json" data-test-id="schema-org-data">` blocks: `MovieTheater` (all pages) and `Movie` (movie pages: name, description, genre, duration, cast/director/producer, poster/image, trailer `VideoObject`). **No showtimes/sessions/offers in JSON-LD.**
- Showtimes exist ONLY as hidden-div anchors: `<a href=".../checkout/showing/{slug}/{sessionId}">Month D, H:MM am/pm</a>` — note **no year** in the text; the adapter needs a year-inference rule.
- Microdata (`itemprop=`) duplicates the JSON-LD — redundant, ignore it.

Parse strategy: JSON-LD `Movie` for film metadata + regex/selector over checkout anchors for sessions. Year inference must not make `parse` impure: `fetch` stamps `payload["fetched_on"] = date.today().isoformat()`, and `parse` resolves each Month-Day against that reference (use the reference year; if the resulting date lands more than ~30 days before `fetched_on`, roll to the next year). Fixture tests pass a fixed `fetched_on`.

**Files:**
- Create: `shutin/adapters/indy.py` (replace stub), `tests/test_indy.py`

**Interfaces:**
- Consumes: `fetch.get`, fixtures `tests/fixtures/cinemagic/*`.
- Produces: module with `fetch(config: dict) -> dict` returning `{"now_showing": <html str>, "movies": {slug: <html str>}, "fetched_on": "YYYY-MM-DD"}` and `parse(payload) -> list[RawScreening]`. `config` keys: `base_url` (e.g. `"https://tickets.thecinemagictheater.com"`).

- [ ] **Step 1: Write the failing fixture test**

`tests/test_indy.py`:

```python
import pathlib
from datetime import datetime

from shutin.adapters import indy

FIX = pathlib.Path(__file__).parent / "fixtures" / "cinemagic"


def load_payload():
    movies = {
        f.stem.removeprefix("movie_"): f.read_text(encoding="utf-8")
        for f in FIX.glob("movie_*.html")
    }
    return {
        "now_showing": (FIX / "now_showing.html").read_text(encoding="utf-8"),
        "movies": movies,
        "fetched_on": "2026-07-14",  # fixtures captured this day; keeps parse deterministic
    }


def test_parse_extracts_screenings():
    screenings = indy.parse(load_payload())
    # fixtures: Obsession 7 showtimes, Hour of the Wolf 1, The Furious 3
    assert len(screenings) == 11
    s = screenings[0]
    assert s.film_title
    assert isinstance(s.starts_at_local, datetime) and s.starts_at_local.tzinfo is None


def test_screenings_carry_jsonld_film_metadata():
    screenings = indy.parse(load_payload())
    assert all(s.description for s in screenings)
    assert all(s.poster_url for s in screenings)
    assert any(s.runtime_minutes for s in screenings)  # JSON-LD Movie duration


def test_ticket_urls_are_checkout_links():
    screenings = indy.parse(load_payload())
    assert all(s.ticket_url and "/checkout/showing/" in s.ticket_url for s in screenings)


def test_year_inference_rolls_forward():
    # "January 5" fetched on 2026-12-20 must resolve to 2027, not 2026
    assert indy.resolve_year("January 5, 7:30 pm", "2026-12-20") == datetime(2027, 1, 5, 19, 30)
    # same-month date stays in the fetch year
    assert indy.resolve_year("December 21, 7:30 pm", "2026-12-20") == datetime(2026, 12, 21, 19, 30)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_indy.py -v`
Expected: FAIL — stub has no `parse`.

- [ ] **Step 3: Implement**

`shutin/adapters/indy.py` (starting point — Step 4 reconciles exact regexes/anchors with fixtures):

```python
"""Indy cinema platform (indy-systems.imgix.net CDN; Cinemagic pattern).

Quasar/Vue SPA whose raw HTML ships a hidden SSR div. Film metadata comes from the
JSON-LD Movie block (<script type="application/ld+json" data-test-id="schema-org-data">);
showtimes exist ONLY as hidden-div anchors:
    <a href=".../checkout/showing/{slug}/{sessionId}">Month D, H:MM am/pm</a>
JSON-LD has no sessions; anchor text has no year (see resolve_year).
"""
import json
import re
from datetime import date, datetime, timedelta

from selectolax.parser import HTMLParser

from shutin import fetch as http
from shutin.adapters.base import RawScreening

SLUG_RE = re.compile(r'href="[^"]*/movie/([^/"]+)/?"')
SHOWTIME_TEXT_RE = re.compile(r"^([A-Z][a-z]+ \d{1,2}), (\d{1,2}:\d{2}) ([ap])m$", re.IGNORECASE)


def fetch(config: dict) -> dict:
    base = config["base_url"].rstrip("/")
    now_showing = http.get(f"{base}/now-showing/").text
    movies = {}
    for slug in dict.fromkeys(SLUG_RE.findall(now_showing)):
        movies[slug] = http.get(f"{base}/movie/{slug}/").text
    return {"now_showing": now_showing, "movies": movies,
            "fetched_on": date.today().isoformat()}


def resolve_year(text: str, fetched_on: str) -> datetime | None:
    """'August 24, 8:00 pm' + fetch date -> naive datetime, rolling into next year
    when the month/day already passed (>30 days before fetch)."""
    m = SHOWTIME_TEXT_RE.match(text.strip())
    if not m:
        return None
    ref = date.fromisoformat(fetched_on)
    md, hm, ap = m.groups()
    hour, minute = (int(x) for x in hm.split(":"))
    hour = hour % 12 + (12 if ap.lower() == "p" else 0)
    dt = datetime.strptime(f"{md} {ref.year}", "%B %d %Y").replace(hour=hour, minute=minute)
    if dt.date() < ref - timedelta(days=30):
        dt = dt.replace(year=ref.year + 1)
    return dt


def parse(payload: dict) -> list[RawScreening]:
    out = []
    for slug, html_text in payload["movies"].items():
        out.extend(_parse_movie_page(html_text, payload["fetched_on"]))
    return out


def _parse_movie_page(html_text: str, fetched_on: str) -> list[RawScreening]:
    tree = HTMLParser(html_text)
    movie = _jsonld_movie(tree)
    title = movie.get("name", "")
    description = movie.get("description")
    poster = movie.get("image") or movie.get("thumbnailUrl")
    runtime = _iso_duration_minutes(movie.get("duration"))

    out = []
    for a in tree.css('a[href*="/checkout/showing/"]'):
        dt = resolve_year(a.text(strip=True), fetched_on)
        if dt:
            out.append(RawScreening(
                film_title=title,
                starts_at_local=dt,
                description=description,
                poster_url=poster,
                runtime_minutes=runtime,
                ticket_url=a.attributes.get("href"),
            ))
    return out


def _jsonld_movie(tree) -> dict:
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if item.get("@type") == "Movie":
                return item
    return {}


def _iso_duration_minutes(duration: str | None) -> int | None:
    """'PT1H38M' -> 98; None/unparseable -> None."""
    if not duration:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration)
    if not m or not any(m.groups()):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
```

- [ ] **Step 4: Reconcile with fixtures until green**

The fixtures are the truth for: exact showtime anchor text format (spacing, am/pm case, comma placement), JSON-LD structure (single object vs list, image field name), duration format. Adjust `SHOWTIME_TEXT_RE`, `_jsonld_movie`, and the expected screening count (11) to what the fixtures actually contain — if the count differs, recount from the fixtures by hand before changing the assertion.

Run: `.venv/Scripts/python -m pytest tests/test_indy.py -v` — iterate until 4 PASS.

- [ ] **Step 5: Record what was true**

One-line update to `docs/06-site-recon.md` Cinemagic section (adapter named `indy`, parse source = JSON-LD + checkout anchors), and correct the `docs/02-ingestion-architecture.md` adapter-library table row: Cinemagic's adapter is `indy`, not `veezi_web` (keep the `veezi_web` row as a future adapter — the platform still serves 200+ cinemas, just not this one).

- [ ] **Step 6: Commit**

```bash
git add shutin/adapters/indy.py tests/test_indy.py docs/06-site-recon.md docs/02-ingestion-architecture.md
git commit -m "feat: indy adapter (Cinemagic) with fixture tests"
```

---

### Task 7: Normalizer + store (upsert, cancellation, ledger)

**Files:**
- Create: `shutin/normalize.py`, `shutin/store.py`, `tests/test_normalize.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `RawScreening` (Task 4), `db.connect/migrate` (Task 1).
- Produces:
  - `normalize.normalize_title(title: str) -> str` — lowercase, strip leading articles (a/an/the), strip format tags (`(35mm)`, `in 70mm`, `3d`), year suffixes (`(1979)`), collapse whitespace.
  - `normalize.to_utc(local: datetime, tz: str) -> tuple[str, str]` — returns `(starts_at_utc_iso, starts_at_local_str)` where local string is `"YYYY-MM-DD HH:MM"`.
  - `store.start_run(conn, theater_id: str) -> int` (run id) and `store.finish_run(conn, run_id, outcome: str, counts: dict, error_detail: str | None = None)`.
  - `store.record_screenings(conn, theater_id: str, run_id: int, tz: str, raw: list[RawScreening]) -> dict` — full upsert pass; returns `{"found": n, "new": n, "updated": n, "cancelled": n}`.
  - `store.was_previously_healthy(conn, theater_id: str) -> bool` — any prior run with outcome `ok` and `screenings_found > 0`.

- [ ] **Step 1: Write failing normalize tests**

`tests/test_normalize.py`:

```python
from datetime import datetime

from shutin import normalize


def test_normalize_title():
    cases = {
        "The Godfather": "godfather",
        "Alien (35mm)": "alien",
        "  Casablanca (1942) ": "casablanca",
        "An American Werewolf in London": "american werewolf in london",
        "Akira in 70mm": "akira",
    }
    for raw, want in cases.items():
        assert normalize.normalize_title(raw) == want


def test_to_utc_applies_theater_timezone():
    utc, local = normalize.to_utc(datetime(2026, 7, 14, 19, 30), "America/Los_Angeles")
    assert utc == "2026-07-15T02:30:00Z"  # PDT is UTC-7
    assert local == "2026-07-14 19:30"


def test_to_utc_handles_dst_boundary():
    utc, _ = normalize.to_utc(datetime(2026, 12, 14, 19, 30), "America/Los_Angeles")
    assert utc == "2026-12-15T03:30:00Z"  # PST is UTC-8
```

- [ ] **Step 2: Write failing store tests**

`tests/test_store.py`:

```python
from datetime import datetime

from shutin import db, store
from shutin.adapters.base import RawScreening

TZ = "America/Los_Angeles"


def setup_conn():
    conn = db.connect(":memory:")
    db.migrate(conn)
    conn.execute("INSERT INTO region VALUES ('portland-or', 'Portland, OR', ?)", (TZ,))
    conn.execute(
        "INSERT INTO theater (id, region_id, name, website_url, timezone, adapter, adapter_config)"
        " VALUES ('t1', 'portland-or', 'T1', 'http://x', ?, 'veezi_web', '{}')",
        (TZ,),
    )
    return conn


def raw(title="Alien", day=20, hour=19):
    return RawScreening(film_title=title, starts_at_local=datetime(2026, 7, day, hour, 30))


def test_upsert_is_idempotent():
    conn = setup_conn()
    r1 = store.start_run(conn, "t1")
    counts = store.record_screenings(conn, "t1", r1, TZ, [raw()])
    assert counts == {"found": 1, "new": 1, "updated": 0, "cancelled": 0}
    store.finish_run(conn, r1, "ok", counts)

    r2 = store.start_run(conn, "t1")
    counts = store.record_screenings(conn, "t1", r2, TZ, [raw()])
    assert counts["new"] == 0 and counts["updated"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM screening").fetchone()["c"] == 1


def test_missing_future_screening_marked_cancelled_not_deleted():
    conn = setup_conn()
    r1 = store.start_run(conn, "t1")
    store.finish_run(conn, r1, "ok", store.record_screenings(conn, "t1", r1, TZ, [raw(day=20), raw(day=21)]))

    r2 = store.start_run(conn, "t1")
    counts = store.record_screenings(conn, "t1", r2, TZ, [raw(day=20)])
    assert counts["cancelled"] == 1
    rows = conn.execute("SELECT status FROM screening ORDER BY starts_at").fetchall()
    assert [r["status"] for r in rows] == ["scheduled", "cancelled"]


def test_cancelled_screening_reappearing_is_rescheduled():
    conn = setup_conn()
    r1 = store.start_run(conn, "t1")
    store.record_screenings(conn, "t1", r1, TZ, [raw()])
    r2 = store.start_run(conn, "t1")
    store.record_screenings(conn, "t1", r2, TZ, [])  # vanishes -> cancelled
    r3 = store.start_run(conn, "t1")
    store.record_screenings(conn, "t1", r3, TZ, [raw()])  # back -> scheduled
    assert conn.execute("SELECT status FROM screening").fetchone()["status"] == "scheduled"


def test_films_dedupe_on_normalized_title():
    conn = setup_conn()
    r1 = store.start_run(conn, "t1")
    store.record_screenings(conn, "t1", r1, TZ, [raw("Alien (35mm)", day=20), raw("Alien", day=21)])
    assert conn.execute("SELECT COUNT(*) c FROM film").fetchone()["c"] == 1


def test_was_previously_healthy():
    conn = setup_conn()
    assert not store.was_previously_healthy(conn, "t1")
    r1 = store.start_run(conn, "t1")
    store.finish_run(conn, r1, "ok", {"found": 5, "new": 5, "updated": 0, "cancelled": 0})
    assert store.was_previously_healthy(conn, "t1")
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_normalize.py tests/test_store.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 4: Implement**

`shutin/normalize.py`:

```python
import re
from datetime import datetime
from zoneinfo import ZoneInfo

_ARTICLES = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
_NOISE = re.compile(
    r"\s*(\((?:19|20)\d{2}\)|\(\d+mm\)|in \d+mm|\(3-?d\)|3-?d)\s*$", re.IGNORECASE
)


def normalize_title(title: str) -> str:
    t = title.strip()
    while True:
        t2 = _NOISE.sub("", t)
        if t2 == t:
            break
        t = t2
    t = _ARTICLES.sub("", t)
    return re.sub(r"\s+", " ", t).lower().strip()


def to_utc(local: datetime, tz: str) -> tuple[str, str]:
    aware = local.replace(tzinfo=ZoneInfo(tz))
    utc = aware.astimezone(ZoneInfo("UTC"))
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ"), local.strftime("%Y-%m-%d %H:%M")
```

`shutin/store.py`:

```python
from datetime import datetime, timezone

from shutin.adapters.base import RawScreening
from shutin.normalize import normalize_title, to_utc


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def start_run(conn, theater_id: str) -> int:
    cur = conn.execute(
        "INSERT INTO scrape_run (theater_id, started_at) VALUES (?, ?)", (theater_id, _now())
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, outcome: str, counts: dict, error_detail=None):
    conn.execute(
        "UPDATE scrape_run SET finished_at=?, outcome=?, screenings_found=?,"
        " screenings_new=?, screenings_updated=?, screenings_cancelled=?, error_detail=?"
        " WHERE id=?",
        (_now(), outcome, counts.get("found", 0), counts.get("new", 0),
         counts.get("updated", 0), counts.get("cancelled", 0), error_detail, run_id),
    )
    conn.commit()


def was_previously_healthy(conn, theater_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM scrape_run WHERE theater_id=? AND outcome='ok' AND screenings_found>0 LIMIT 1",
        (theater_id,),
    ).fetchone()
    return row is not None


def _get_or_create_film(conn, s: RawScreening) -> int:
    norm = normalize_title(s.film_title)
    row = conn.execute("SELECT id FROM film WHERE normalized_title=?", (norm,)).fetchone()
    if row:
        # backfill metadata a later scrape provides (partial data welcome, N2)
        conn.execute(
            "UPDATE film SET scraped_description=COALESCE(scraped_description, ?),"
            " scraped_poster_url=COALESCE(scraped_poster_url, ?),"
            " runtime_minutes=COALESCE(runtime_minutes, ?) WHERE id=?",
            (s.description, s.poster_url, s.runtime_minutes, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO film (title, normalized_title, scraped_description, scraped_poster_url,"
        " runtime_minutes) VALUES (?, ?, ?, ?, ?)",
        (s.film_title, norm, s.description, s.poster_url, s.runtime_minutes),
    )
    return cur.lastrowid


def record_screenings(conn, theater_id: str, run_id: int, tz: str, raw: list[RawScreening]) -> dict:
    counts = {"found": len(raw), "new": 0, "updated": 0, "cancelled": 0}
    for s in raw:
        film_id = _get_or_create_film(conn, s)
        starts_at, starts_at_local = to_utc(s.starts_at_local, tz)
        existing = conn.execute(
            "SELECT id FROM screening WHERE theater_id=? AND film_id=? AND starts_at=?",
            (theater_id, film_id, starts_at),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE screening SET ticket_url=?, format=?, event_note=?,"
                " status='scheduled', last_seen_run_id=? WHERE id=?",
                (s.ticket_url, s.format, s.event_note, run_id, existing["id"]),
            )
            counts["updated"] += 1
        else:
            conn.execute(
                "INSERT INTO screening (theater_id, film_id, starts_at, starts_at_local,"
                " ticket_url, format, event_note, status, first_seen_run_id, last_seen_run_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)",
                (theater_id, film_id, starts_at, starts_at_local, s.ticket_url,
                 s.format, s.event_note, run_id, run_id),
            )
            counts["new"] += 1

    # F5: future screenings not seen this run -> cancelled, never deleted
    cur = conn.execute(
        "UPDATE screening SET status='cancelled'"
        " WHERE theater_id=? AND status='scheduled' AND starts_at > ?"
        " AND (last_seen_run_id IS NULL OR last_seen_run_id != ?)",
        (theater_id, _now(), run_id),
    )
    counts["cancelled"] = cur.rowcount
    conn.commit()
    return counts
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_normalize.py tests/test_store.py -v`
Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add shutin/normalize.py shutin/store.py tests/test_normalize.py tests/test_store.py
git commit -m "feat: normalizer (tz, titles) and store (upsert/cancel/ledger)"
```

---

### Task 8: TMDB enrichment

**Files:**
- Create: `shutin/enrich.py`, `tests/test_enrich.py`

**Interfaces:**
- Consumes: `fetch.get`, `normalize.normalize_title`, film rows from Task 7.
- Produces: `enrich.enrich_pending_films(conn, api_key: str) -> dict` — for every film with `enrichment_status='pending'`: TMDB `/search/movie`, score candidates, write `tmdb_id/tmdb_description/tmdb_poster_path/tmdb_match_confidence`, set status `matched` (confidence ≥ 0.75) or `no_match`; returns `{"matched": n, "no_match": n}`. Also `enrich.score(scraped_title: str, candidate: dict) -> float`. Films already `matched`/`no_match`/`skipped` are never re-queried (cache rule from docs/04). Enrichment exceptions never propagate — caller stores scraped data regardless (F4/N2).

- [ ] **Step 1: Write failing tests**

`tests/test_enrich.py`:

```python
from shutin import db, enrich


def seeded_conn():
    conn = db.connect(":memory:")
    db.migrate(conn)
    conn.execute("INSERT INTO film (title, normalized_title) VALUES ('Alien (35mm)', 'alien')")
    return conn


def test_score_exact_normalized_match_beats_fuzzy():
    exact = enrich.score("Alien (35mm)", {"title": "Alien", "popularity": 50})
    fuzzy = enrich.score("Alien (35mm)", {"title": "Aliens", "popularity": 90})
    assert exact > fuzzy
    assert exact >= 0.9


def test_enrich_writes_match(monkeypatch):
    conn = seeded_conn()

    class FakeResp:
        def json(self):
            return {"results": [
                {"id": 348, "title": "Alien", "overview": "In space...",
                 "poster_path": "/alien.jpg", "popularity": 60},
            ]}

    monkeypatch.setattr(enrich.fetch, "get", lambda *a, **k: FakeResp())
    result = enrich.enrich_pending_films(conn, api_key="x")
    assert result["matched"] == 1
    row = conn.execute("SELECT * FROM film").fetchone()
    assert row["tmdb_id"] == 348
    assert row["enrichment_status"] == "matched"
    assert row["tmdb_match_confidence"] >= 0.75


def test_no_results_marks_no_match(monkeypatch):
    conn = seeded_conn()

    class FakeResp:
        def json(self):
            return {"results": []}

    monkeypatch.setattr(enrich.fetch, "get", lambda *a, **k: FakeResp())
    enrich.enrich_pending_films(conn, api_key="x")
    assert conn.execute("SELECT enrichment_status s FROM film").fetchone()["s"] == "no_match"


def test_matched_film_not_requeried(monkeypatch):
    conn = seeded_conn()
    conn.execute("UPDATE film SET enrichment_status='matched'")
    calls = []
    monkeypatch.setattr(enrich.fetch, "get", lambda *a, **k: calls.append(a))
    enrich.enrich_pending_films(conn, api_key="x")
    assert calls == []


def test_api_error_leaves_film_pending(monkeypatch):
    conn = seeded_conn()

    def boom(*a, **k):
        raise RuntimeError("TMDB down")

    monkeypatch.setattr(enrich.fetch, "get", boom)
    result = enrich.enrich_pending_films(conn, api_key="x")  # must not raise
    assert result == {"matched": 0, "no_match": 0}
    assert conn.execute("SELECT enrichment_status s FROM film").fetchone()["s"] == "pending"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_enrich.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

`shutin/enrich.py`:

```python
"""TMDB enrichment: default on, per-theater toggle honored by the caller (cli.py)."""
import difflib

from shutin import fetch
from shutin.normalize import normalize_title

SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
MATCH_THRESHOLD = 0.75


def score(scraped_title: str, candidate: dict) -> float:
    a = normalize_title(scraped_title)
    b = normalize_title(candidate.get("title", ""))
    if a == b:
        return 0.95 + min(candidate.get("popularity", 0), 100) / 2000  # exact: 0.95-1.0
    return difflib.SequenceMatcher(None, a, b).ratio() * 0.9  # fuzzy caps below exact


def enrich_pending_films(conn, api_key: str) -> dict:
    result = {"matched": 0, "no_match": 0}
    pending = conn.execute("SELECT * FROM film WHERE enrichment_status='pending'").fetchall()
    for film in pending:
        try:
            r = fetch.get(SEARCH_URL, params={"api_key": api_key, "query": film["normalized_title"]})
            candidates = r.json().get("results", [])
        except Exception:
            continue  # F4/N2: enrichment failure never blocks anything; retry next run
        best = max(candidates, key=lambda c: score(film["title"], c), default=None)
        conf = score(film["title"], best) if best else 0.0
        if best and conf >= MATCH_THRESHOLD:
            conn.execute(
                "UPDATE film SET tmdb_id=?, tmdb_description=?, tmdb_poster_path=?,"
                " tmdb_match_confidence=?, enrichment_status='matched' WHERE id=?",
                (best["id"], best.get("overview"), best.get("poster_path"), conf, film["id"]),
            )
            result["matched"] += 1
        else:
            conn.execute(
                "UPDATE film SET tmdb_match_confidence=?, enrichment_status='no_match' WHERE id=?",
                (conf, film["id"]),
            )
            result["no_match"] += 1
    conn.commit()
    return result
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_enrich.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add shutin/enrich.py tests/test_enrich.py
git commit -m "feat: TMDB enrichment with confidence scoring and pending-only cache"
```

---

### Task 9: Alerting (email + GitHub issue)

**Files:**
- Create: `shutin/alerts.py`, `tests/test_alerts.py`

**Interfaces:**
- Consumes: env config (Global Constraints), `scrape_run` rows.
- Produces:
  - `alerts.notify_failure(theater: dict, run: dict, cfg: dict) -> None` — sends the email AND files/updates the GitHub issue.
  - `alerts.notify_recovery(theater: dict, cfg: dict) -> None` — closes the open issue with a comment; no email (throttling: email only on state change is satisfied because caller invokes these only on state transitions or repeat failures once per daily run).
  - `alerts.config_from_env() -> dict` — reads the env vars; missing GitHub/SMTP config disables that channel with a printed warning (dev machines), never an exception.
  - Issue convention: title `[scraper-broken] <theater_id>`, label `scraper-broken`, one open issue per theater (search-first, comment on existing), body links `shutin record-fixtures --theater <id>` and `.claude/skills/debug-theater-scraper`.

- [ ] **Step 1: Write failing tests**

`tests/test_alerts.py`:

```python
import json

from shutin import alerts

THEATER = {"id": "hollywood-theatre", "name": "Hollywood Theatre"}
RUN = {"id": 7, "outcome": "error", "error_detail": "HTTP 500", "screenings_found": 0,
       "screenings_new": 0, "screenings_updated": 0, "screenings_cancelled": 0}
CFG = {"github_token": "t", "github_repo": "user/shut-in", "smtp": None, "alert_email": None}


def test_failure_creates_issue_when_none_open(monkeypatch):
    calls = []

    def fake_api(method, url, cfg, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return []  # no open issue
        return {"number": 12}

    monkeypatch.setattr(alerts, "_github_api", fake_api)
    alerts.notify_failure(THEATER, RUN, CFG)
    methods = [c[0] for c in calls]
    assert methods == ["GET", "POST"]
    assert "[scraper-broken] hollywood-theatre" in json.dumps(calls[1][2])


def test_repeat_failure_comments_on_existing_issue(monkeypatch):
    calls = []

    def fake_api(method, url, cfg, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return [{"number": 12, "title": "[scraper-broken] hollywood-theatre"}]
        return {}

    monkeypatch.setattr(alerts, "_github_api", fake_api)
    alerts.notify_failure(THEATER, RUN, CFG)
    assert any("/issues/12/comments" in c[1] for c in calls if c[0] == "POST")


def test_recovery_closes_issue(monkeypatch):
    calls = []

    def fake_api(method, url, cfg, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return [{"number": 12, "title": "[scraper-broken] hollywood-theatre"}]
        return {}

    monkeypatch.setattr(alerts, "_github_api", fake_api)
    alerts.notify_recovery(THEATER, CFG)
    assert any(c[0] == "PATCH" and c[2] == {"state": "closed"} for c in calls)


def test_missing_channel_config_is_nonfatal(monkeypatch, capsys):
    alerts.notify_failure(THEATER, RUN, {"github_token": None, "github_repo": None,
                                         "smtp": None, "alert_email": None})
    # nothing raised; warning printed
    assert "disabled" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_alerts.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`shutin/alerts.py`:

```python
"""Dual-channel alerting (F7): operator email + one GitHub issue per broken theater."""
import json
import os
import smtplib
from email.message import EmailMessage

from curl_cffi import requests

LABEL = "scraper-broken"


def config_from_env() -> dict:
    smtp = None
    if os.environ.get("SMTP_HOST"):
        smtp = {
            "host": os.environ["SMTP_HOST"],
            "port": int(os.environ.get("SMTP_PORT", "587")),
            "user": os.environ.get("SMTP_USER"),
            "password": os.environ.get("SMTP_PASS"),
        }
    return {
        "github_token": os.environ.get("GITHUB_TOKEN"),
        "github_repo": os.environ.get("GITHUB_REPO"),
        "smtp": smtp,
        "alert_email": os.environ.get("ALERT_EMAIL"),
    }


def _issue_title(theater_id: str) -> str:
    return f"[scraper-broken] {theater_id}"


def _github_api(method: str, url: str, cfg: dict, body: dict | None = None):
    r = requests.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {cfg['github_token']}",
            "Accept": "application/vnd.github+json",
        },
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json() if r.content else {}


def _find_open_issue(theater: dict, cfg: dict):
    issues = _github_api(
        "GET",
        f"https://api.github.com/repos/{cfg['github_repo']}/issues?labels={LABEL}&state=open",
        cfg,
    )
    want = _issue_title(theater["id"])
    return next((i for i in issues if i["title"] == want), None)


def _failure_body(theater: dict, run: dict) -> str:
    return (
        f"Run {run['id']} for **{theater['name']}** failed: `{run['outcome']}`\n\n"
        f"```\n{run.get('error_detail') or 'zero screenings from a previously healthy theater'}\n```\n\n"
        f"Repair loop:\n"
        f"1. `shutin record-fixtures --theater {theater['id']}`\n"
        f"2. Follow `.claude/skills/debug-theater-scraper`\n"
    )


def notify_failure(theater: dict, run: dict, cfg: dict) -> None:
    if cfg.get("github_token") and cfg.get("github_repo"):
        base = f"https://api.github.com/repos/{cfg['github_repo']}/issues"
        existing = _find_open_issue(theater, cfg)
        if existing:
            _github_api("POST", f"{base}/{existing['number']}/comments", cfg,
                        {"body": _failure_body(theater, run)})
        else:
            _github_api("POST", base, cfg, {
                "title": _issue_title(theater["id"]),
                "labels": [LABEL],
                "body": _failure_body(theater, run),
            })
    else:
        print("alerts: github channel disabled (GITHUB_TOKEN/GITHUB_REPO unset)")

    if cfg.get("smtp") and cfg.get("alert_email"):
        msg = EmailMessage()
        msg["Subject"] = f"[shut-in] {theater['id']} scrape {run['outcome']}"
        msg["From"] = cfg["smtp"]["user"] or "shutin@localhost"
        msg["To"] = cfg["alert_email"]
        msg.set_content(_failure_body(theater, run))
        with smtplib.SMTP(cfg["smtp"]["host"], cfg["smtp"]["port"]) as s:
            s.starttls()
            if cfg["smtp"]["user"]:
                s.login(cfg["smtp"]["user"], cfg["smtp"]["password"])
            s.send_message(msg)
    else:
        print("alerts: email channel disabled (SMTP_*/ALERT_EMAIL unset)")


def notify_recovery(theater: dict, cfg: dict) -> None:
    if not (cfg.get("github_token") and cfg.get("github_repo")):
        print("alerts: github channel disabled (GITHUB_TOKEN/GITHUB_REPO unset)")
        return
    existing = _find_open_issue(theater, cfg)
    if existing:
        base = f"https://api.github.com/repos/{cfg['github_repo']}/issues/{existing['number']}"
        _github_api("POST", f"{base}/comments", cfg,
                    {"body": f"{theater['name']} recovered — latest run green. Auto-closing."})
        _github_api("PATCH", base, cfg, {"state": "closed"})
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_alerts.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add shutin/alerts.py tests/test_alerts.py
git commit -m "feat: dual-channel alerting - email + deduped GitHub issue per theater"
```

---

### Task 10: `refresh` CLI — the pipeline conductor

**Files:**
- Create: `shutin/cli.py`, `tests/test_cli.py`, `migrations/002_seed_portland.sql`

**Interfaces:**
- Consumes: everything above.
- Produces: console entrypoint `shutin` with subcommands:
  - `shutin migrate` — connect + migrate, print applied.
  - `shutin refresh [--theater ID]` — for each enabled theater (or the one named): adapter fetch→parse, `record_screenings`, per-theater `tmdb_enrichment` honored, ledger, alert logic; each theater wrapped in try/except so one failure never blocks the rest (N2). Exit code 0 if all green, 1 if any theater failed.
  - `shutin record-fixtures --theater ID` — run the theater's adapter `fetch` and write the raw payload under `tests/fixtures/<id>/` (the one-command fixture refresh promised by docs/02 and the alert issue body).
  - Alert decision (F6/F7): outcome `error` (exception) or `zero_screenings` (0 found AND `was_previously_healthy`) ⇒ `notify_failure`, set `scrape_run.alerted=1`. Green run after a run with `alerted=1` ⇒ `notify_recovery`.

- [ ] **Step 1: Write `migrations/002_seed_portland.sql`**

`adapter_config.base_url` values come from Task 2's verified recon:

```sql
INSERT INTO region VALUES ('portland-or', 'Portland, OR', 'America/Los_Angeles');

INSERT INTO theater (id, region_id, name, website_url, timezone, adapter, adapter_config)
VALUES
  ('hollywood-theatre', 'portland-or', 'Hollywood Theatre',
   'https://hollywoodtheatre.org', 'America/Los_Angeles',
   'wordpress_gecko', '{"base_url": "https://hollywoodtheatre.org"}'),
  ('cinemagic', 'portland-or', 'Cinemagic',
   'https://www.thecinemagictheater.com', 'America/Los_Angeles',
   'indy', '{"base_url": "https://tickets.thecinemagictheater.com"}');
```

- [ ] **Step 2: Write failing CLI tests**

`tests/test_cli.py` (fake adapter registered into `ADAPTERS`, alerts monkeypatched):

```python
from datetime import datetime

import pytest

from shutin import cli, db
from shutin.adapters import ADAPTERS
from shutin.adapters.base import RawScreening


class FakeAdapter:
    fail = False
    screenings = [RawScreening(film_title="Alien", starts_at_local=datetime(2026, 7, 20, 19, 30))]

    @classmethod
    def fetch(cls, config):
        if cls.fail:
            raise RuntimeError("site down")
        return {"x": 1}

    @classmethod
    def parse(cls, payload):
        return cls.screenings


@pytest.fixture
def env(tmp_path, monkeypatch):
    dbfile = tmp_path / "t.db"
    monkeypatch.setenv("SHUTIN_DB", str(dbfile))
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.setitem(ADAPTERS, "fake", FakeAdapter)
    conn = db.connect(dbfile)
    db.migrate(conn)
    conn.execute("DELETE FROM theater")  # replace seed with the fake
    conn.execute(
        "INSERT INTO theater (id, region_id, name, website_url, timezone, adapter,"
        " adapter_config, tmdb_enrichment) VALUES"
        " ('fake-t', 'portland-or', 'Fake', 'http://x', 'America/Los_Angeles', 'fake', '{}', 0)"
    )
    conn.commit()
    conn.close()
    FakeAdapter.fail = False
    alerts = {"fail": [], "recover": []}
    monkeypatch.setattr(cli.alerts, "notify_failure", lambda t, r, c: alerts["fail"].append(t["id"]))
    monkeypatch.setattr(cli.alerts, "notify_recovery", lambda t, c: alerts["recover"].append(t["id"]))
    return dbfile, alerts


def run_row(dbfile, n=1):
    conn = db.connect(dbfile)
    return conn.execute("SELECT * FROM scrape_run ORDER BY id DESC LIMIT 1").fetchone()


def test_refresh_green(env):
    dbfile, alerts = env
    assert cli.main(["refresh"]) == 0
    row = run_row(dbfile)
    assert row["outcome"] == "ok" and row["screenings_found"] == 1
    assert alerts["fail"] == []


def test_refresh_failure_alerts_and_exits_nonzero(env):
    dbfile, alerts = env
    FakeAdapter.fail = True
    assert cli.main(["refresh"]) == 1
    row = run_row(dbfile)
    assert row["outcome"] == "error" and row["alerted"] == 1
    assert alerts["fail"] == ["fake-t"]


def test_zero_after_healthy_is_suspicious(env):
    dbfile, alerts = env
    cli.main(["refresh"])                      # healthy baseline
    FakeAdapter.screenings = []
    cli.main(["refresh"])
    row = run_row(dbfile)
    assert row["outcome"] == "zero_screenings" and alerts["fail"] == ["fake-t"]
    FakeAdapter.screenings = [RawScreening(film_title="Alien", starts_at_local=datetime(2026, 7, 20, 19, 30))]


def test_recovery_closes_the_loop(env):
    dbfile, alerts = env
    FakeAdapter.fail = True
    cli.main(["refresh"])
    FakeAdapter.fail = False
    assert cli.main(["refresh"]) == 0
    assert alerts["recover"] == ["fake-t"]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement**

`shutin/cli.py`:

```python
import argparse
import json
import os
import pathlib
import traceback

from shutin import alerts, db, enrich, store
from shutin.adapters import ADAPTERS


def _conn():
    return db.connect(os.environ.get("SHUTIN_DB", "shutin.db"))


def refresh(theater_id: str | None = None) -> int:
    conn = _conn()
    db.migrate(conn)
    cfg = alerts.config_from_env()
    q = "SELECT * FROM theater WHERE enabled=1"
    rows = conn.execute(q + " AND id=?", (theater_id,)).fetchall() if theater_id \
        else conn.execute(q).fetchall()
    exit_code = 0
    for t in rows:
        theater = dict(t)
        run_id = store.start_run(conn, theater["id"])
        prev_alerted = conn.execute(
            "SELECT alerted FROM scrape_run WHERE theater_id=? AND id<? ORDER BY id DESC LIMIT 1",
            (theater["id"], run_id),
        ).fetchone()
        try:
            adapter = ADAPTERS[theater["adapter"]]
            raw = adapter.parse(adapter.fetch(json.loads(theater["adapter_config"])))
            counts = store.record_screenings(conn, theater["id"], run_id, theater["timezone"], raw)
            suspicious = counts["found"] == 0 and store.was_previously_healthy(conn, theater["id"])
            outcome = "zero_screenings" if suspicious else "ok"
            store.finish_run(conn, run_id, outcome, counts)
            if theater["tmdb_enrichment"] and os.environ.get("TMDB_API_KEY"):
                enrich.enrich_pending_films(conn, os.environ["TMDB_API_KEY"])
            if suspicious:
                _alert(conn, theater, run_id, cfg)
                exit_code = 1
            elif prev_alerted and prev_alerted["alerted"]:
                alerts.notify_recovery(theater, cfg)
            print(f"{theater['id']}: {outcome} {counts}")
        except Exception:
            store.finish_run(conn, run_id, "error", {}, traceback.format_exc()[-2000:])
            _alert(conn, theater, run_id, cfg)
            print(f"{theater['id']}: ERROR")
            exit_code = 1
    return exit_code


def _alert(conn, theater, run_id, cfg):
    run = dict(conn.execute("SELECT * FROM scrape_run WHERE id=?", (run_id,)).fetchone())
    try:
        alerts.notify_failure(theater, run, cfg)
    finally:
        conn.execute("UPDATE scrape_run SET alerted=1 WHERE id=?", (run_id,))
        conn.commit()


def record_fixtures(theater_id: str) -> int:
    conn = _conn()
    t = conn.execute("SELECT * FROM theater WHERE id=?", (theater_id,)).fetchone()
    adapter = ADAPTERS[t["adapter"]]
    payload = adapter.fetch(json.loads(t["adapter_config"]))
    out = pathlib.Path("tests/fixtures") / theater_id / "payload.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shutin")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    r = sub.add_parser("refresh")
    r.add_argument("--theater")
    f = sub.add_parser("record-fixtures")
    f.add_argument("--theater", required=True)
    args = p.parse_args(argv)
    if args.cmd == "migrate":
        print(db.migrate(_conn()) or "up to date")
        return 0
    if args.cmd == "refresh":
        return refresh(args.theater)
    return record_fixtures(args.theater)


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: `record-fixtures` writes one `payload.json`; the per-endpoint fixture layout from Task 2 stays authoritative for adapter tests — `payload.json` is the debugging snapshot the alert issue references. (If during Task 11 this dual format annoys, unify then, not now.)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: everything passes (db, fetch, both adapters, normalize, store, enrich, alerts, cli).

- [ ] **Step 6: First real end-to-end run (live, from dev machine)**

```bash
export SHUTIN_DB=shutin.db TMDB_API_KEY=<key>
.venv/Scripts/python -m shutin.cli refresh
```

Expected: both theaters `ok` with plausible counts. Spot-check:

```sql
-- .venv/Scripts/python -c "..." or sqlite3 shutin.db
SELECT t.name, COUNT(*) n, MIN(s.starts_at), MAX(s.starts_at)
FROM screening s JOIN theater t ON t.id=s.theater_id GROUP BY 1;
SELECT title, enrichment_status, tmdb_match_confidence FROM film ORDER BY 3;
```

Eyeball a few rows against both live sites. Low-confidence/no_match films are expected for repertory one-offs — verify their scraped fields survived.

- [ ] **Step 7: Commit**

```bash
git add shutin/cli.py tests/test_cli.py migrations/002_seed_portland.sql
git commit -m "feat: refresh CLI - full pipeline with per-theater isolation and alert wiring"
```

---

### Task 11: VPS deployment — cron, env, backup

Requires user input: VPS host/access, SMTP credentials, a GitHub token with `repo` scope, TMDB API key. **Ask for these at task start.**

**Files:**
- Create: `deploy/shutin.env.example`, `deploy/crontab.example`, `docs/08-operations.md`

**Interfaces:**
- Produces: the VPS running `shutin refresh` daily at 05:30 America/Los_Angeles, plus nightly DB backup (cross-cutting requirement).

- [ ] **Step 1: Write deploy files**

`deploy/shutin.env.example`:

```bash
SHUTIN_DB=/home/shutin/shutin.db
TMDB_API_KEY=changeme
GITHUB_TOKEN=changeme
GITHUB_REPO=owner/shut-in
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=changeme
SMTP_PASS=changeme
ALERT_EMAIL=sfancler@gmail.com
```

`deploy/crontab.example` (VPS assumed UTC; 05:30 PT ≈ 12:30/13:30 UTC — pick 13:00 UTC, fine for both DST phases):

```cron
# daily refresh, 13:00 UTC ~= early morning Pacific
0 13 * * *  cd /home/shutin/shut-in && set -a && . ./shutin.env && set +a && .venv/bin/shutin refresh >> refresh.log 2>&1
# nightly sqlite backup (WAL-safe) with 14-day rotation
30 11 * * * sqlite3 /home/shutin/shutin.db ".backup /home/shutin/backups/shutin-$(date +\%u).db"
```

`docs/08-operations.md`: setup steps (clone, `python3.12 -m venv .venv`, `pip install -e .`, copy env example, `shutin migrate`, install crontab), where logs live, how to run a manual refresh, how to restore a backup.

- [ ] **Step 2: Deploy and verify**

On the VPS: follow docs/08 exactly (that's the test of the doc). Run `shutin refresh` manually once.
Expected: both theaters `ok`; `refresh.log` written; `scrape_run` rows present.

- [ ] **Step 3: Verify the cron fires**

Temporarily set the cron 5 minutes ahead, confirm a new `scrape_run` row appears, then set the real schedule.

- [ ] **Step 4: Commit**

```bash
git add deploy/ docs/08-operations.md
git commit -m "feat: VPS deployment - cron, env template, backup, operations doc"
```

---

### Task 12: Alert drill — deliberately induced failure (exit criterion)

- [ ] **Step 1: Break one theater on purpose** — on the VPS (or locally against the prod DB copy):

```sql
UPDATE theater SET adapter_config='{"base_url": "https://hollywoodtheatre.org/nonexistent"}'
WHERE id='hollywood-theatre';
```

Run `shutin refresh --theater hollywood-theatre`.
Expected: run outcome `error`, **email received** at ALERT_EMAIL, **GitHub issue opened** titled `[scraper-broken] hollywood-theatre` with the fixture command + debug-skill links in the body.

- [ ] **Step 2: Verify repeat-failure dedup** — run refresh again. Expected: no second issue; a new comment on the existing one.

- [ ] **Step 3: Restore and verify recovery** — fix `adapter_config`, run refresh. Expected: green run, issue auto-closed with a comment.

- [ ] **Step 4: Record the drill** — append results to `docs/08-operations.md` ("Alert drill 2026-MM-DD: pass"). Commit:

```bash
git add docs/08-operations.md
git commit -m "docs: alert drill results - both channels verified"
```

---

### Task 13: Third theater via the `add-theater` skill (roadmap step 7)

Proves the onboarding loop and iterates the skill with real feedback. Candidate list from the roadmap: Laurelhurst, Academy, Cinema 21, Clinton St. **Recommend Clinton St** — recon already identified it as WordPress "The Events Calendar" (`/wp-json/tribe/events/v1/events`, proven by `dlowe/flicks`), so it exercises the *new-adapter* path (`events_calendar`) while staying low-risk. Ask the user which theater; default to Clinton St.

- [ ] **Step 1: Invoke the `add-theater` skill** for the chosen theater and follow it end to end (recon → platform detection → tier probe → fixture capture → adapter → validation → registration). The skill drives; this plan doesn't duplicate its steps.

- [ ] **Step 2: New adapter (if Clinton St): `events_calendar`** — same TDD shape as Task 5: fixtures first, failing fixture test, implement `fetch(config)`/`parse(payload)` against `/wp-json/tribe/events/v1/events`, register in `ADAPTERS`, seed row via `migrations/003_add_<theater>.sql`.

- [ ] **Step 3: Validation per the skill** — human-readable screening table eyeballed against the live site, dry-run, TMDB match-rate report, then enable + first real run, confirm ledger row.

- [ ] **Step 4: Iterate the skill** — whatever friction appeared (missing steps, wrong assumptions, unclear instructions), edit `.claude/skills/add-theater/` accordingly. This is the deferred skill-creator eval loop; real usage is the eval.

- [ ] **Step 5: Commit**

```bash
git add shutin/adapters/ tests/ migrations/ .claude/skills/add-theater/
git commit -m "feat: third theater onboarded via add-theater skill; skill iterated"
```

---

### Task 14: Soak — 7 consecutive green daily runs (exit criterion)

Calendar time, not work time. Day 0 starts after Task 13's theater is live.

- [ ] **Step 1: Daily check (7 days)** — each day confirm via the ledger:

```sql
SELECT theater_id, date(started_at) d, outcome, screenings_found
FROM scrape_run WHERE started_at > datetime('now', '-8 days')
ORDER BY started_at;
```

Any red day: fix via `debug-theater-scraper` skill, reset the 7-day counter.

- [ ] **Step 2: Declare Phase 1 done** — update `README.md` status line (Phase 0 → Phase 1 complete, Phase 2 next) and `docs/05-roadmap.md` (check off Phase 1, note exit-criteria evidence: ledger dates, drill date, third theater id). Commit:

```bash
git add README.md docs/05-roadmap.md
git commit -m "docs: Phase 1 ingestion MVP complete - exit criteria met"
```

---

## Self-review notes

- **Spec coverage:** F1 (Task 11 cron), F2/F3 (RawScreening fields, Tasks 4–6), F4 (Task 8 + per-theater toggle honored in Task 10), F5 (Task 7 upsert/cancel tests), F6 (Task 7 ledger + Task 10 zero-detection), F7 (Task 9 + Task 12 drill), F8 (Task 13). N1 (Task 4 spacing/backoff + robots check in Task 2), N2 (per-theater try/except Task 10; partial-data COALESCE Task 7), N3 (deps constrained globally), N4 (no browser tier needed for either target; tier 2 deferred until a site demands it — YAGNI), N5 (ledger queries in Tasks 12/14). Roadmap items 1–7 map to Tasks 1, 2, 5–6, 8, 7+10+11, 9+12, 13. The `/prototype` gate the user requested is Task 3.
- **Known deliberate gaps (ponytail):** no tier-2 Patchright code (no current target needs it — add when a theater defeats tier 1); no `format`/`event_note` extraction promised beyond what fixtures actually expose (F2 says "when available"); `record-fixtures` snapshot format differs from hand-captured per-endpoint fixtures (unify only if it hurts in Task 13).
- **Type consistency check:** `RawScreening` field names match between base.py, both adapters, store.py, and all tests; `record_screenings(conn, theater_id, run_id, tz, raw)` signature consistent between Task 7 definition and Task 10 caller; `ADAPTERS` registry contract (`module.fetch(config)` / `module.parse(payload)`) consistent across Tasks 4, 5, 6, 10.
