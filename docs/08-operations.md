# Operations

Shut-in runs on a small VPS under a **dedicated, unprivileged `shutin` user** — never as
root, and never touching any other service that may share the box. If the VPS already
runs other software (e.g. under a different service user), leave that user, its
`/opt/*` directories, its systemd units, and its crontab strictly alone; Shut-in's
footprint is limited to `/home/shutin`.

## One-time VPS setup

Run as root (or via `sudo`) the first time only.

```bash
# 1. Dedicated user — Shut-in never runs as root or shares another service's account
adduser --disabled-password --gecos "" shutin

# 2. sqlite3 CLI is required for the nightly backup cron; Ubuntu doesn't ship it by default
which sqlite3 || apt-get update && apt-get install -y sqlite3

# 3. Backup destination directory
mkdir -p /home/shutin/backups && chown shutin:shutin /home/shutin/backups
```

Clone and build as the `shutin` user:

```bash
su - shutin
git clone https://github.com/sfancler-blip/Shut-in.git shut-in
cd shut-in
git checkout claude/movie-showtimes-aggregator-plan-hkl99q   # or main once merged

python3 -m venv .venv
.venv/bin/pip install -e .     # runtime deps only — no [dev] extras on the VPS
```

**Note on the clone:** the Shut-in repo is public, so cloning/pulling over `https` needs
no credential at all. The only place a GitHub token is needed is inside `shutin.env`
(`GITHUB_TOKEN`), which the alerting module uses to *file* issues via the GitHub API on
scrape failure (a write operation, unlike the read-only clone/pull). Reuse a token you
already have locally (e.g. `gh auth token` if the `gh` CLI is authenticated on your
workstation) — generate/copy it into `shutin.env` directly on the box (e.g. by piping it
over SSH) rather than typing it into shell history or committing it anywhere. It only
needs the `repo` scope. Never put the token in a git remote URL, a log, or a commit.

Create the environment file from the template and fill in real values:

```bash
cp deploy/shutin.env.example shutin.env
# edit shutin.env:
#   SHUTIN_DB=/home/shutin/shutin.db
#   TMDB_API_KEY=<real key>
#   GITHUB_TOKEN=<real token, repo scope>
#   GITHUB_REPO=sfancler-blip/Shut-in
#   ALERT_EMAIL=<real address>
#   leave SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS UNSET if you don't have SMTP creds —
#   alerts.py treats a missing SMTP_HOST as "email channel disabled" and just prints a
#   warning line instead of failing; the GitHub-issue channel still works independently.
chmod 600 shutin.env
```

`shutin.env` must stay `chmod 600`, owned by `shutin`, and is already covered by
`.gitignore` — never commit a real one. Only `deploy/shutin.env.example` (all
`changeme` placeholders) is tracked.

Initialize the database and do one manual verification run:

```bash
cd /home/shutin/shut-in
set -a; . ./shutin.env; set +a
.venv/bin/shutin migrate
.venv/bin/shutin refresh
```

Expected: one line per enabled theater ending in `ok` with non-zero `found` counts, and
new rows in the `scrape_run` table (`sqlite3 shutin.env… /home/shutin/shutin.db "select
id, theater_id, outcome, screenings_found from scrape_run order by id desc limit 5"`).

## Cron

Install the schedule for the `shutin` user (not root — Shut-in's crontab is entirely
separate from any other service's):

```bash
crontab -u shutin deploy/crontab.example
crontab -u shutin -l   # verify
```

The box runs UTC. Schedule:

| Time (UTC) | Job |
|---|---|
| 13:00 | `shutin refresh --exclude hollywood-theatre` — daily showtimes refresh for all theaters except Hollywood, which is relayed separately (~05:00–06:00 Pacific depending on DST); see "Hollywood relay (interim)" below |
| 11:30 | nightly SQLite backup (`.backup`), rotated across 7 files by day-of-week |

To confirm cron actually fires end-to-end (recommended once after any crontab change):
temporarily edit the refresh line's minute/hour to ~5 minutes in the future
(`crontab -u shutin -e`), wait for it to run, confirm a new `scrape_run` row landed with
a `started_at` after the temporary edit, then reinstall the real schedule from
`deploy/crontab.example`.

## Logs

The refresh cron redirects stdout/stderr to `/home/shutin/shut-in/refresh.log`, and the
backup cron redirects to `/home/shutin/shut-in/backup.log` (both append mode — rotate/
truncate manually if they grow large; there's no log rotation configured yet). Tail them
with:

```bash
tail -n 50 /home/shutin/shut-in/refresh.log
tail -n 50 /home/shutin/shut-in/backup.log
```

Per-run outcomes also live in the `scrape_run` table (`outcome`, `error_detail`,
`screenings_found/new/updated/cancelled`, `alerted`) — this is the primary source of
truth for whether a scrape actually succeeded, since a zero-exit cron job can still have
logged a `zero_screenings`/`error` outcome per-theater.

## Manual refresh

```bash
cd /home/shutin/shut-in
set -a; . ./shutin.env; set +a
.venv/bin/shutin refresh                  # both theaters
.venv/bin/shutin refresh --theater <id>   # one theater only
```

## Backup / restore

Nightly cron runs (see schedule above):

```bash
sqlite3 /home/shutin/shutin.db ".backup /home/shutin/backups/shutin-$(date +%u).db"
```

`.backup` is WAL-safe (uses SQLite's online backup API, consistent even if a refresh is
mid-write) and rotates across 7 files (`shutin-1.db` … `shutin-7.db`, one per weekday),
so the last full week is always recoverable. Run it manually any time:

```bash
mkdir -p /home/shutin/backups
sqlite3 /home/shutin/shutin.db ".backup /home/shutin/backups/shutin-manual-$(date +%Y%m%dT%H%M%S).db"
ls -la /home/shutin/backups
```

To restore, stop the cron first (`crontab -u shutin -r`, or comment the refresh line
out), then:

```bash
cp /home/shutin/shutin.db /home/shutin/shutin.db.bak-before-restore   # safety net
cp /home/shutin/backups/shutin-<n>.db /home/shutin/shutin.db
```

or, for a copy taken while the live DB might have been open, use SQLite's own restore
instead of a raw file copy:

```bash
sqlite3 /home/shutin/shutin.db ".restore /home/shutin/backups/shutin-<n>.db"
```

Then reinstall the crontab (`crontab -u shutin deploy/crontab.example`) once satisfied.

## Hollywood relay (interim)

**Why:** hollywoodtheatre.org Cloudflare-challenges (403) requests from the VPS's Hetzner
datacenter IP, even with the same `curl_cffi` TLS-impersonation that passes cleanly from
a residential IP. Rather than fight Cloudflare from the datacenter, Hollywood's fetch is
relayed from this Windows desktop's residential IP until a dedicated home microserver
exists (see the `home-microserver-plan` note).

**Architecture:** the adapter contract already splits `fetch()` (network) from `parse()`
(pure). A scheduled task on the Windows desktop runs
[deploy/relay-hollywood.ps1](../deploy/relay-hollywood.ps1) daily, which:

1. Runs `shutin fetch-payload --theater hollywood-theatre --out <TEMP>\hollywood-payload.json`
   locally (residential IP passes Cloudflare; writes the adapter's raw JSON payload, no parsing).
2. `scp`s the payload to `/home/shutin/inbox/hollywood-payload.json` on the VPS.
3. `ssh`es in and runs `shutin refresh --theater hollywood-theatre --payload <path>` as the
   `shutin` user, which skips `fetch()` entirely and parses+stores the shipped payload.

The VPS's own 13:00 UTC cron now runs `shutin refresh --exclude hollywood-theatre` so it no
longer wastes a run failing Hollywood's fetch itself (see Cron section above).

**Where things live:**
- Scheduled task: Windows Task Scheduler, task name `ShutIn Hollywood Relay`, daily at
  05:45 local (Pacific), `Start-ScheduledTaskInfo`/`Get-ScheduledTaskInfo` to inspect.
- Transcript log: `relay.log` in the repo root on the Windows desktop (gitignored, append
  mode via `Start-Transcript`).
- Scratch DB: `relay.db` in the repo root on the Windows desktop (gitignored) — only used
  to read the `hollywood-theatre` row's `adapter_config`; never touches the real dataset.

**Run manually:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\relay-hollywood.ps1
```

**Known issues:**
- **If the Windows box is off (or asleep) at the scheduled time, Hollywood silently gets
  no run that day.** There is no VPS-side fallback fetch attempt and no alert fires for a
  missed day — this is silence, not an error. Check `relay.log` and the VPS `scrape_run`
  table for `hollywood-theatre` if showtimes look stale.
- Retire this relay (delete the scheduled task, `deploy/relay-hollywood.ps1`, and the
  `--exclude hollywood-theatre` on the VPS cron) once the planned home microserver is
  running and can fetch Hollywood directly from its own residential IP.

## Known issues (historical)

- ~~The GitHub-issue alert channel gets HTTP 403 on issue creation~~ **Fixed** (commit
  `867f377`): `_github_api` sent no `User-Agent` header, and GitHub's API rejects
  UA-less requests with a bare `HTTP Error 403` regardless of token scope — not a
  token/permission problem. Added `User-Agent: shutin-alerts` to the request headers
  and locked it in with a regression test (`tests/test_alerts.py::test_github_api_sends_user_agent`).
  Verified live from the VPS: an authenticated `GET` through the real
  `alerts._github_api` code path returned `200` with the issue list. The write path
  (issue `POST`) gets exercised for real whenever a theater fails and `notify_failure`
  runs. The GitHub channel is expected to work in production now; SMTP remains
  intentionally unconfigured (no creds provided), so email stays a "channel disabled"
  no-op until that's supplied.
- ~~Hollywood Theatre returns a Cloudflare JS-challenge (403) from the VPS's IP~~
  **Mitigated** (Task 11b): see "Hollywood relay (interim)" above.

## Alert drill 2026-07-16: pass

Live end-to-end failure -> alert -> dedupe -> recovery drill against the VPS and the
Windows relay (Task 12). Induced failure was `shutin refresh --theater hollywood-theatre`
(plain fetch, no `--payload`) — this genuinely 403s at Cloudflare from the VPS's
datacenter IP, so no config mutation was needed and restore was a no-op.

**Interim note:** the first attempt at this drill hit a live, externally-confirmed
GitHub REST API outage (`githubstatus.com` "Degraded REST API Availability", impact
`major`, started `2026-07-16T22:51:13Z`) that 503'd every GitHub call for about 45
minutes — `alerts.py` degraded correctly during that window (printed
`alerts: github channel failed: HTTP Error 503`, did not crash the run). Once GitHub's
"API Requests" component returned to `operational`, the drill was re-run start to finish
and passed clean, below.

**Step 1 (induced failure → issue opened):**
```
ssh root@5.78.194.128 "sudo -u shutin bash -c 'cd /home/shutin/shut-in && set -a && . ./shutin.env && set +a && .venv/bin/shutin refresh --theater hollywood-theatre'"
```
Output: `alerts: email channel disabled (SMTP_*/ALERT_EMAIL unset)` (expected — SMTP
unconfigured), `hollywood-theatre: ERROR`, exit 1. `scrape_run` row 16:
`outcome=error, alerted=1`. GitHub issue **#2** `[scraper-broken] hollywood-theatre`
opened at `2026-07-17T00:02:43Z` with the run-16 traceback (Cloudflare `403`), the
`shutin record-fixtures` repair command, and the `.claude/skills/debug-theater-scraper`
link in the body, per `notify_failure`'s template.

**Step 2 (dedupe):** repeated the same command. `scrape_run` row 17:
`outcome=error, alerted=1`. **No second issue created** — `gh issue list` still shows
only issue #2 open (plus the unrelated closed probe #1) — and a single new comment
landed on #2 at `2026-07-17T00:02:57Z` referencing "Run 17", confirming the dedupe path
(comment-on-existing) rather than a duplicate issue.

**Step 3 (recovery via relay):** `Start-ScheduledTask "ShutIn Hollywood Relay"`,
foreground-polled `Get-ScheduledTaskInfo` from `Running` to `Ready`
(`LastTaskResult 0`, run at `7/16/2026 5:03:18 PM` local). `relay.log`: payload fetched
locally, scp'd, ingested via `--payload` — `hollywood-theatre: ok {'found': 262, 'new':
0, 'updated': 262, 'cancelled': 0}`, no GitHub error line this time. `scrape_run` row 18:
`outcome=ok, screenings_found=262, alerted=0`. Issue #2 got a recovery comment
("Hollywood Theatre recovered — latest run green. Auto-closing.") at
`2026-07-17T00:05:18Z` and was auto-closed one second later at `2026-07-17T00:05:19Z`.

**Conclusion:** full failure -> alert -> dedupe -> recovery loop verified end to end on
both the induced-failure and relay-recovery legs, and on both alert channels (GitHub
issue lifecycle live; email correctly reporting itself disabled). See
[task-12-report.md](../.superpowers/sdd/task-12-report.md) for the complete command-by-
command log including the earlier GitHub-outage attempt.

## Deploying a new commit

```bash
su - shutin
cd /home/shutin/shut-in
git pull                        # public repo — no credentials needed
.venv/bin/pip install -e .      # re-run in case dependencies changed
```
