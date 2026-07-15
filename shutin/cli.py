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
        run_id = None
        try:
            run_id = store.start_run(conn, theater["id"])
            prev_alerted = conn.execute(
                "SELECT alerted FROM scrape_run WHERE theater_id=? AND id<? ORDER BY id DESC LIMIT 1",
                (theater["id"], run_id),
            ).fetchone()
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
            if run_id is not None:
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
        store.mark_alerted(conn, run_id)


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
