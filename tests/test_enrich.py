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


def test_malformed_candidate_does_not_block_other_films(monkeypatch):
    conn = seeded_conn()
    conn.execute(
        "INSERT INTO film (title, normalized_title) VALUES ('Aliens (35mm)', 'aliens')"
    )

    responses = {
        "alien": {"results": [
            {"id": 348, "title": "Alien", "overview": "In space...",
             "poster_path": "/alien.jpg", "popularity": 60},
        ]},
        "aliens": {"results": [
            {"title": "Aliens", "popularity": 90},  # missing "id" -> KeyError on write
        ]},
    }

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, params=None, **kw):
        return FakeResp(responses[params["query"]])

    monkeypatch.setattr(enrich.fetch, "get", fake_get)

    result = enrich.enrich_pending_films(conn, api_key="x")  # must not raise

    rows = {r["normalized_title"]: r for r in conn.execute("SELECT * FROM film").fetchall()}
    assert rows["alien"]["enrichment_status"] == "matched"
    assert rows["alien"]["tmdb_id"] == 348
    assert rows["aliens"]["enrichment_status"] == "pending"
    assert result["matched"] == 1


def test_api_error_leaves_film_pending(monkeypatch):
    conn = seeded_conn()

    def boom(*a, **k):
        raise RuntimeError("TMDB down")

    monkeypatch.setattr(enrich.fetch, "get", boom)
    result = enrich.enrich_pending_films(conn, api_key="x")  # must not raise
    assert result == {"matched": 0, "no_match": 0}
    assert conn.execute("SELECT enrichment_status s FROM film").fetchone()["s"] == "pending"
