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


def test_manual_confirmation_hides_company_on_new_load_without_inventing_attempt(tmp_path, monkeypatch):
    import pandas as pd
    import pytest
    from src.state import confirm_contacts, get_reviews
    from src.reviews import apply_reviews
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "manual.db"}')
    engine = init_db()
    rows = pd.DataFrame({'cnpj': ['00000000000191', '11222333000181'], 'reviewed': [False, False]})
    written = []
    assert confirm_contacts(['00000000000191'], rows, engine, registry_writer=written.extend) == (1, 0)
    assert confirm_contacts(['00000000000191'], rows, engine) == (0, 1)
    assert get_states(['00000000000191'], engine) == []
    reloaded = apply_reviews(rows.drop(columns='reviewed'), get_reviews(engine))
    assert reloaded['reviewed'].tolist() == [True, False]
    assert reloaded.iloc[0]['review_status'] == 'contatado'
    assert written[0]['cnpj'] == '00000000000191'
    with pytest.raises(ValueError, match='revisada'):
        confirm_contacts(['00000000000191'], reloaded, engine)
    with pytest.raises(ValueError):
        confirm_contacts(['04252011000110'], rows, engine)


def test_remote_failure_does_not_silently_mark_contacts_only_in_local_database(tmp_path, monkeypatch):
    import pandas as pd
    import pytest
    from src.state import confirm_contacts, get_reviews
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "failed.db"}')
    engine = init_db()
    def fail(records):
        raise RuntimeError('remote unavailable')
    with pytest.raises(RuntimeError):
        confirm_contacts(['00000000000191'], pd.DataFrame({'cnpj': ['00000000000191'], 'reviewed': [False]}),
                         engine, registry_writer=fail)
    assert get_reviews(engine) == []
