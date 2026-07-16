import json
from datetime import datetime, timedelta

import pytest

from shutin import cli, db
from shutin.adapters import ADAPTERS
from shutin.adapters.base import RawScreening


class FakeAdapter:
    fail = False
    # AMENDED (Task 7 review): relative future date, not hardcoded - hardcoded dates rot.
    screenings = [RawScreening(film_title="Alien",
                               starts_at_local=(datetime.now() + timedelta(days=7)).replace(hour=19, minute=30, second=0, microsecond=0))]

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
    FakeAdapter.screenings = [RawScreening(film_title="Alien",
                                           starts_at_local=(datetime.now() + timedelta(days=7)).replace(hour=19, minute=30, second=0, microsecond=0))]
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
    FakeAdapter.screenings = [RawScreening(film_title="Alien",
                                           starts_at_local=(datetime.now() + timedelta(days=7)).replace(hour=19, minute=30, second=0, microsecond=0))]


def test_recovery_closes_the_loop(env):
    dbfile, alerts = env
    FakeAdapter.fail = True
    cli.main(["refresh"])
    FakeAdapter.fail = False
    assert cli.main(["refresh"]) == 0
    assert alerts["recover"] == ["fake-t"]


def test_refresh_payload_skips_fetch(env, tmp_path, monkeypatch):
    dbfile, alerts = env
    payload_file = tmp_path / "p.json"
    payload_file.write_text('{"x": 1}', encoding="utf-8")

    def boom(config):
        raise AssertionError("fetch must not run in payload mode")

    monkeypatch.setattr(FakeAdapter, "fetch", boom)
    assert cli.main(["refresh", "--theater", "fake-t", "--payload", str(payload_file)]) == 0
    row = run_row(dbfile)
    assert row["outcome"] == "ok" and row["screenings_found"] == 1


def test_refresh_exclude(env):
    dbfile, alerts = env
    assert cli.main(["refresh", "--exclude", "fake-t"]) == 0
    assert run_row(dbfile) is None  # the only theater was excluded -> no run rows


def test_payload_requires_theater(env):
    with pytest.raises(SystemExit) as e:
        cli.main(["refresh", "--payload", "x.json"])
    assert e.value.code == 2  # argparse usage error


def test_fetch_payload_writes_file(env, tmp_path):
    dbfile, alerts = env
    out = tmp_path / "out.json"
    assert cli.main(["fetch-payload", "--theater", "fake-t", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"x": 1}
