# Shut-in Hollywood relay: fetch from this (residential) IP, ship to VPS, trigger ingest.
# Scheduled daily via Windows Task Scheduler (see docs/08-operations.md).
$ErrorActionPreference = "Stop"
$repo = "C:\Users\Fancy\Documents\Obsidian Vault\Claude Projects\Shut-in"
$vps = "root@5.78.194.128"
$payload = Join-Path $env:TEMP "hollywood-payload.json"

Start-Transcript -Path (Join-Path $repo "relay.log") -Append
try {
    Set-Location $repo
    $env:SHUTIN_DB = Join-Path $repo "relay.db"   # local scratch DB (gitignored), only theater config is read
    & "$repo\.venv\Scripts\shutin.exe" fetch-payload --theater hollywood-theatre --out $payload
    if ($LASTEXITCODE -ne 0) { throw "fetch-payload failed: $LASTEXITCODE" }
    scp $payload "${vps}:/home/shutin/inbox/hollywood-payload.json"
    if ($LASTEXITCODE -ne 0) { throw "scp failed: $LASTEXITCODE" }
    ssh $vps "chown shutin:shutin /home/shutin/inbox/hollywood-payload.json && sudo -u shutin bash -c 'cd /home/shutin/shut-in && set -a && . ./shutin.env && set +a && .venv/bin/shutin refresh --theater hollywood-theatre --payload /home/shutin/inbox/hollywood-payload.json'"
    if ($LASTEXITCODE -ne 0) { throw "remote ingest failed: $LASTEXITCODE" }
} finally {
    Stop-Transcript
}
