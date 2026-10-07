from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.demo import demo_data
from src.prospecting import now_local
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
    data = demo_data(now_local().date())
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
    data = demo_data(now_local().date())
    data.to_parquet(file, index=False)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception
    assert at.metric[0].value == "3"
    data.iloc[:1].to_parquet(file, index=False)
    at.run()
    assert not at.exception
    assert at.metric[0].value == "1"


def test_neighborhood_and_porte_filters_control_visible_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    neighborhood = next(w for w in at.multiselect if w.label == 'Bairro')
    neighborhood.set_value(['ILHA DOS ARAUJOS']).run()
    assert not at.exception
    assert at.metric[0].value == '1'
    table = next(m.value for m in at.markdown if 'class="prospect-table"' in m.value)
    assert 'Oficina Exemplo' in table
    assert 'Loja Exemplo' not in table
    portes = next(w for w in at.multiselect if w.label == 'Porte da empresa')
    portes.set_value(['01']).run()
    assert at.metric[0].value == '0'
    assert not at.exception


def test_real_table_links_queue_and_manual_name_do_not_record_until_opened(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, unquote
    import html
    monkeypatch.chdir(tmp_path)
    db_url = f"sqlite:///{tmp_path / 'state.db'}"
    monkeypatch.setenv('DATABASE_URL', db_url)
    (tmp_path / 'data').mkdir()
    data = demo_data(now_local().date())
    data['cnpj'] = [f'{i:014d}' for i in range(1, 5)]
    # Testa que o CNAE secundário afasta uma escola da lista publicada antiga.
    data.loc[2, 'cnae_fiscal_secundaria'] = '8511200'
    data.to_parquet(tmp_path / 'data/companies.parquet', index=False)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception
    assert at.metric[0].value == '2'
    table = next(m.value for m in at.markdown if 'class="prospect-table"' in m.value)
    assert table.count('target="cnpj-whatsapp"') == 2
    assert '<th>Contato</th>' in table
    assert 'Mercado Exemplo' not in table
    assert get_states(['00000000000001'], init_db()) == []
    next(b for b in at.button if b.label == 'Adicionar esta página à fila').click().run()
    assert not at.exception
    assert at.session_state['contact_queue'] == ['00000000000001', '00000000000002']
    assert get_states(['00000000000001'], init_db()) == []
    next(b for b in at.button if b.label == 'Próximo contato').click().run()
    assert at.session_state['contact_queue'] == ['00000000000002']
    assert get_states(['00000000000001'], init_db()) == []
    next(w for w in at.text_input if w.label == 'Nome usado na saudação').set_value('Juliana').run()
    links = [html.unescape(m.value) for m in at.markdown if 'Abrir WhatsApp e registrar tentativa</a>' in m.value]
    assert len(links) == 1
    assert parse_qs(links[0].split('href="?')[1].split('"')[0])['name'] == ['Juliana']


def test_contact_link_recomputes_greeting_at_click_time(tmp_path, monkeypatch):
    from datetime import datetime
    from src import prospecting
    from src.prospecting import DEFAULT_TEMPLATE, SAO_PAULO, contact_link
    from urllib.parse import parse_qs
    from sqlalchemy import text
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'state.db'}")
    (tmp_path / 'data').mkdir()
    data = demo_data(now_local().date())
    data['cnpj'] = [f'{i:014d}' for i in range(1, 5)]
    data.to_parquet(tmp_path / 'data/companies.parquet', index=False)
    monkeypatch.setattr(prospecting, 'now_local', lambda: datetime(2026, 10, 6, 8, tzinfo=SAO_PAULO))
    query = parse_qs(contact_link(data.iloc[0], data.iloc[0]['whatsapp_1'], DEFAULT_TEMPLATE,
                                 'Daniel', attempt_id='time-test')[1:])
    monkeypatch.setattr(prospecting, 'now_local', lambda: datetime(2026, 10, 6, 15, tzinfo=SAO_PAULO))
    at = AppTest.from_file(str(APP))
    at.query_params.update({k: v[0] for k, v in query.items()})
    at.run(timeout=15)
    assert not at.exception
    with init_db().connect() as conn:
        message = conn.execute(text('SELECT message FROM contact_attempts')).scalar_one()
    assert message.startswith('Boa tarde! Tudo bem?')
