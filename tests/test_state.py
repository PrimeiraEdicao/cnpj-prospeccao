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
