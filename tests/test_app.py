from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.demo import demo_data
from src.state import get_states, init_db

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_demo_opens_without_database_or_real_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "invalid://must-not-be-used")
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception
    assert "fictícias" in at.info[0].value
    assert at.metric[0].value == "3"
    assert at.button[0].disabled
    assert not (tmp_path / "data").exists()
    next(box for box in at.checkbox if box.label == "Remover escritórios/serviços contábeis").uncheck().run()
    assert not at.exception
    assert at.metric[0].value == "4"


def test_contact_query_preserves_percent_and_plus_and_is_idempotent(tmp_path, monkeypatch):
    from datetime import date
    monkeypatch.chdir(tmp_path)
    db_url = f"sqlite:///{tmp_path / 'state.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    data = demo_data(date.today())
    data["cnpj"] = [f"{i:014d}" for i in range(1, 5)]
    (tmp_path / "data").mkdir()
    data.to_parquet(tmp_path / "data/companies.parquet", index=False)
    at = AppTest.from_file(str(APP))
    message = "Oferta 20%20 e A+B / café"
    at.query_params.update({"contact": "00000000000001", "attempt": "one-click",
                            "phone": "5500000000000", "name": "Maria", "msg": message})
    at.run(timeout=15)
    assert not at.exception
    at.run()
    assert not at.exception
    engine = init_db()
    assert get_states(["00000000000001"], engine)[0]["attempt_count"] == 1
    from sqlalchemy import text
    with engine.connect() as conn:
        assert conn.execute(text("SELECT message FROM contact_attempts")).scalar_one() == message


def test_new_snapshot_invalidates_cached_data(tmp_path, monkeypatch):
    from datetime import date
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    (tmp_path / "data").mkdir()
    file = tmp_path / "data/companies.parquet"
    data = demo_data(date.today())
    data.to_parquet(file, index=False)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception
    assert at.metric[0].value == "3"
    data.iloc[:1].to_parquet(file, index=False)
    at.run()
    assert not at.exception
    assert at.metric[0].value == "1"
