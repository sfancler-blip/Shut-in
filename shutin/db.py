import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migration (id TEXT PRIMARY KEY)")
    done = {r["id"] for r in conn.execute("SELECT id FROM schema_migration")}
    applied = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if f.stem not in done:
            conn.executescript(f.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migration VALUES (?)", (f.stem,))
            applied.append(f.stem)
    conn.commit()
    return applied
