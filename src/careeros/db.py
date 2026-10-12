from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.fts_enabled = False

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            migration_dir = Path(__file__).parent / "migrations"
            # Numbered SQL files are applied in order; new schema changes belong in
            # the next migration so existing local databases upgrade in place.
            for migration in sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql")):
                if conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (migration.name,)).fetchone():
                    continue
                script = migration.read_text(encoding="utf-8")
                try:
                    conn.executescript("BEGIN IMMEDIATE;\n" + script + "\nINSERT INTO schema_migrations(version) VALUES ('" + migration.name.replace("'", "''") + "');\nCOMMIT;")
                except Exception:
                    if conn.in_transaction:
                        conn.rollback()
                    raise
            self._initialize_fts(conn)

    def _initialize_fts(self, conn: sqlite3.Connection) -> None:
        try:
            conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(title, company, location, description, content='jobs', content_rowid='rowid');
                CREATE TRIGGER IF NOT EXISTS jobs_fts_ai AFTER INSERT ON jobs BEGIN
                  INSERT INTO jobs_fts(rowid, title, company, location, description) VALUES (new.rowid, new.title, new.company, new.location, new.description);
                END;
                CREATE TRIGGER IF NOT EXISTS jobs_fts_ad AFTER DELETE ON jobs BEGIN
                  INSERT INTO jobs_fts(jobs_fts, rowid, title, company, location, description) VALUES ('delete', old.rowid, old.title, old.company, old.location, old.description);
                END;
                CREATE TRIGGER IF NOT EXISTS jobs_fts_au AFTER UPDATE ON jobs BEGIN
                  INSERT INTO jobs_fts(jobs_fts, rowid, title, company, location, description) VALUES ('delete', old.rowid, old.title, old.company, old.location, old.description);
                  INSERT INTO jobs_fts(rowid, title, company, location, description) VALUES (new.rowid, new.title, new.company, new.location, new.description);
                END;
            """)
            conn.execute("INSERT INTO jobs_fts(jobs_fts) VALUES ('rebuild')")
            self.fts_enabled = True
        except sqlite3.OperationalError:
            self.fts_enabled = False

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False, factory=_ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()
