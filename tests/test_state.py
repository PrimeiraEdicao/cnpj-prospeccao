import os
from pathlib import Path

from src.state import get_states, init_db, record_attempt


def test_state_is_idempotent(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    engine = init_db()
    assert record_attempt("abc", "12345678000190", "5533999999999", "Maria", "Oi", engine=engine)
    assert not record_attempt("abc", "12345678000190", "5533999999999", "Maria", "Oi", engine=engine)
    rows = get_states(["12345678000190"], engine=engine)
    assert rows[0]["attempt_count"] == 1


def test_concurrent_tabs_preserve_count_and_duplicate_click_is_ignored(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'parallel.db'}")
    engine = init_db()
    def attempt(i):
        return record_attempt(str(i), "12345678000190", "5533999999999", "Maria", "Oi", engine)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, list(range(12)) * 2))
    assert sum(results) == 12
    assert get_states(["12345678000190"], engine)[0]["attempt_count"] == 12


def test_standard_postgres_urls_use_installed_psycopg_driver(monkeypatch):
    from src.state import get_engine
    for url in ("postgresql://user:pass@localhost/db", "postgres://user:pass@localhost/db"):
        monkeypatch.setenv("DATABASE_URL", url)
        engine = get_engine()
        assert engine.dialect.driver == "psycopg"
        engine.dispose()
