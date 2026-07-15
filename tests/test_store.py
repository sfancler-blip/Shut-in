from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from shutin import db, store
from shutin.adapters.base import RawScreening

TZ = "America/Los_Angeles"


def setup_conn():
    conn = db.connect(":memory:")
    db.migrate(conn)
    # OR IGNORE: 002_seed_portland (Task 10) now seeds this region via migrate()
    conn.execute("INSERT OR IGNORE INTO region VALUES ('portland-or', 'Portland, OR', ?)", (TZ,))
    conn.execute(
        "INSERT INTO theater (id, region_id, name, website_url, timezone, adapter, adapter_config)"
        " VALUES ('t1', 'portland-or', 'T1', 'http://x', ?, 'veezi_web', '{}')",
        (TZ,),
    )
    return conn


def _relative_local(offset_days: int, hour: int = 19) -> datetime:
    """Naive local wall-clock datetime `offset_days` from now (store.py compares against
    real wall-clock _now(), so tests must not hardcode a fixed calendar date)."""
    local_now = datetime.now(timezone.utc).astimezone(ZoneInfo(TZ))
    shifted = local_now + timedelta(days=offset_days)
    return shifted.replace(hour=hour, minute=30, second=0, microsecond=0, tzinfo=None)


def raw(title="Alien", offset_days=6, hour=19):
    return RawScreening(film_title=title, starts_at_local=_relative_local(offset_days, hour))


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
    store.finish_run(
        conn, r1, "ok",
        store.record_screenings(conn, "t1", r1, TZ, [raw(offset_days=6), raw(offset_days=7)]),
    )

    r2 = store.start_run(conn, "t1")
    counts = store.record_screenings(conn, "t1", r2, TZ, [raw(offset_days=6)])
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
    store.record_screenings(
        conn, "t1", r1, TZ, [raw("Alien (35mm)", offset_days=6), raw("Alien", offset_days=7)]
    )
    assert conn.execute("SELECT COUNT(*) c FROM film").fetchone()["c"] == 1


def test_was_previously_healthy():
    conn = setup_conn()
    assert not store.was_previously_healthy(conn, "t1")
    r1 = store.start_run(conn, "t1")
    store.finish_run(conn, r1, "ok", {"found": 5, "new": 5, "updated": 0, "cancelled": 0})
    assert store.was_previously_healthy(conn, "t1")


def test_mark_alerted_sets_flag():
    conn = setup_conn()
    r1 = store.start_run(conn, "t1")
    assert conn.execute("SELECT alerted FROM scrape_run WHERE id=?", (r1,)).fetchone()["alerted"] == 0
    store.mark_alerted(conn, r1)
    assert conn.execute("SELECT alerted FROM scrape_run WHERE id=?", (r1,)).fetchone()["alerted"] == 1
