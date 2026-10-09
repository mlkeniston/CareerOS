from careeros.db import Database


def test_initialize_is_repeatable_and_core_tables_exist(tmp_path):
    db = Database(tmp_path / "careeros.sqlite3")
    db.initialize()
    db.initialize()
    with db.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"schema_migrations", "settings", "tasks", "jobs", "applications", "portfolio_proposals"} <= tables


def test_values_persist_after_reopening(tmp_path):
    path = tmp_path / "careeros.sqlite3"
    Database(path).initialize()
    with Database(path).connect() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES('planner_provider','ollama')")
    with Database(path).connect() as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='planner_provider'").fetchone()[0] == "ollama"
