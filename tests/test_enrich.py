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
