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
    import sqlite3

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins)
