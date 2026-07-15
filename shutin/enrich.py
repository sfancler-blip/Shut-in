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
