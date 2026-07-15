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


def finish_run(conn, run_id: int, outcome: str, counts: dict, error_detail: str | None = None):
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
