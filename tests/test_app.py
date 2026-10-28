from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.demo import demo_data
from src.prospecting import now_local
from src.state import get_states, init_db

APP = Path(__file__).resolve().parents[1] / "app.py"


def contact_table(at):
    import json
    return next(json.loads(w.proto.json_args)["markup"] for w in at.get("component_instance")
                if w.proto.component_name.endswith("contact_table"))


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
    table = contact_table(at)
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
    table = contact_table(at)
    assert table.count('target="_blank"') == 2
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
    links = [html.unescape(m.value) for m in at.markdown if 'Abrir WhatsApp</a>' in m.value]
    assert len(links) == 1
    from urllib.parse import urlparse
    query = parse_qs(urlparse(links[0].split('href="')[1].split('"')[0]).query)
    assert 'Juliana' in query['text'][0]
    assert 'web.whatsapp.com/send' in links[0]
    assert '?contact=' not in links[0]


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


def test_appearance_changes_to_dark_and_back_without_resetting_filters(tmp_path, monkeypatch):
    from src.theme import PALETTES
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    next(w for w in at.multiselect if w.label == 'Bairro').set_value(['CENTRO']).run()
    assert at.metric[0].value == '2'
    next(w for w in at.radio if w.label == 'Aparência').set_value('Escuro').run()
    assert not at.exception
    assert at.metric[0].value == '2'
    assert next(w for w in at.multiselect if w.label == 'Bairro').value == ['CENTRO']
    css = next(m.value for m in at.markdown if '--al-bg:' in m.value)
    assert f"--al-bg:{PALETTES['Escuro']['bg']}" in css
    next(w for w in at.radio if w.label == 'Aparência').set_value('Claro').run()
    assert not at.exception
    assert at.metric[0].value == '2'
    css = next(m.value for m in at.markdown if '--al-bg:' in m.value)
    assert f"--al-bg:{PALETTES['Claro']['bg']}" in css


def test_search_formats_and_explanation_for_cnpj_hidden_by_filters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'state.db'}")
    (tmp_path / 'data').mkdir()
    data = demo_data(now_local().date())
    data['cnpj'] = ['01234567000189', '98765432000110', '11222333000199', '00987654000111']
    data.to_parquet(tmp_path / 'data/companies.parquet', index=False)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    for query in ['01.234.567/0001-89', '01234567000189']:
        next(w for w in at.text_input if w.label == 'Buscar empresa/CNPJ/CNAE').set_value(query).run()
        assert not at.exception
        assert at.metric[0].value == '1'
        assert 'Loja Exemplo' in contact_table(at)
    assert any('12.345.678/0001-90' in w.value and '12345678000190' in w.value for w in at.caption)
    next(w for w in at.multiselect if w.label == 'Porte da empresa').set_value(['03']).run()
    assert at.metric[0].value == '0'
    assert any('CNPJ encontrado na base, mas oculto' in w.value for w in at.info)
    next(w for w in at.text_input if w.label == 'Buscar empresa/CNPJ/CNAE').set_value('99.999.999/0001-99').run()
    assert any('não consta na base' in w.value for w in at.info)
    assert not at.exception


def test_import_ui_persists_reviews_removes_queue_and_allows_read_only_inspection(tmp_path, monkeypatch):
    import io
    import streamlit as st
    from src.state import get_reviews, get_states
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'state.db'}")
    (tmp_path / 'data').mkdir()
    data = demo_data(now_local().date())
    data['cnpj'] = ['00000000000191', '11222333000181', '04252011000110', '99999999999999']
    data.to_parquet(tmp_path / 'data/companies.parquet', index=False)
    # AppTest não controla o uploader; injeta o mesmo contrato name/getvalue do UploadedFile.
    class Uploaded(io.BytesIO):
        name = 'revisados.csv'
    uploaded = Uploaded(b'CNPJ\n00.000.000/0001-91\n')
    monkeypatch.setattr(st, 'file_uploader', lambda *args, **kwargs: [uploaded])
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception
    next(b for b in at.button if b.label == 'Adicionar esta página à fila').click().run()
    assert '00000000000191' in at.session_state['contact_queue']
    next(b for b in at.button if b.label == 'Importar CNPJs revisados').click().run()
    assert not at.exception
    assert at.metric[0].value == '2'
    assert '00000000000191' not in at.session_state['contact_queue']
    assert get_reviews(init_db())[0]['status'] == 'revisado'
    assert get_states(['00000000000191'], init_db()) == []
    next(w for w in at.text_input if w.label == 'Buscar empresa/CNPJ/CNAE').set_value('00.000.000/0001-91').run()
    assert any('marcado como revisado' in i.value for i in at.info)
    next(w for w in at.checkbox if w.label == 'Ocultar empresas já revisadas').uncheck().run()
    assert at.metric[0].value == '1'
    table = contact_table(at)
    assert 'Revisado — não contatar' in table and 'href=' not in table
    next(b for b in at.button if b.label == 'Adicionar esta página à fila').click().run()
    assert at.session_state['contact_queue'] == []
    assert not any('Abrir WhatsApp</a>' in m.value for m in at.markdown)
    next(b for b in at.button if b.label == 'Importar CNPJs revisados').click().run()
    assert len(get_reviews(init_db())) == 1
    fresh = AppTest.from_file(str(APP)).run(timeout=15)
    assert fresh.metric[0].value == '2'  # Continua oculto numa nova sessão.


def test_versioned_reviews_apply_to_new_base_and_block_old_whatsapp_links(tmp_path, monkeypatch):
    from src.reviews import load_review_registry
    reviewed = load_review_registry(APP.parent / 'config/reviewed_cnpjs.csv')[0]['cnpj']
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'state.db'}")
    (tmp_path / 'data').mkdir()
    data = demo_data(now_local().date())
    data['cnpj'] = [reviewed, '11222333000181', '04252011000110', '99999999999999']
    data.to_parquet(tmp_path / 'data/companies.parquet', index=False)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception and at.metric[0].value == '2'
    at.query_params.update({'contact': reviewed, 'attempt': 'old-link', 'phone': '5500000000000',
                            'name': 'Maria', 'msg': 'Olá'})
    at.run()
    assert not at.exception
    assert any('não deve receber nova abordagem' in w.value for w in at.warning)
    assert get_states([reviewed], init_db()) == []
    assert not at.get('link_button')


def test_page_size_and_filters_reset_page_and_batch_contains_only_visible_rows(tmp_path, monkeypatch):
    import pandas as pd
    from bs4 import BeautifulSoup
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'state.db'}")
    (tmp_path / 'data').mkdir()
    base = demo_data(now_local().date()).iloc[:1]
    data = pd.concat([base] * 45, ignore_index=True)
    data['cnpj'] = [f'{i:014d}' for i in range(100, 145)]
    data['razao_social'] = [f'Empresa {i}' for i in range(45)]
    data.to_parquet(tmp_path / 'data/companies.parquet', index=False)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception

    assert next(w for w in at.selectbox if w.label == 'Empresas por página').value == 20
    table = BeautifulSoup(contact_table(at), 'html.parser')
    assert len(table.select('tbody tr')) == 20
    next(w for w in at.number_input if w.label == 'Página').set_value(3).run()
    table = BeautifulSoup(contact_table(at), 'html.parser')
    assert len(table.select('tbody tr')) == 5
    assert 'Empresa 40' in table.select_one('tbody tr').text
    next(w for w in at.selectbox if w.label == 'Empresas por página').set_value(50).run()
    assert next(w for w in at.number_input if w.label == 'Página').value == 1
    assert len(BeautifulSoup(contact_table(at), 'html.parser').select('tbody tr')) == 45
    assert get_states(data['cnpj'].tolist(), init_db()) == []
    assert not at.exception


def test_explicit_marking_updates_database_and_removes_company_from_next_list(tmp_path, monkeypatch):
    from src import contact_table as table_module
    from src.state import get_reviews
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'confirmed.db'}")
    (tmp_path / 'data').mkdir()
    data = demo_data(now_local().date())
    data['cnpj'] = ['00000000000191', '11222333000181', '04252011000110', '99999999999999']
    data.to_parquet(tmp_path / 'data/companies.parquet', index=False)
    value = [None]
    monkeypatch.setattr(table_module, 'render_contact_table', lambda *args: value[0])
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert at.metric[0].value == '3'
    value[0] = {'id': 'manual-one', 'action': 'mark_contacted', 'cnpjs': ['00000000000191']}
    at.run()
    assert not at.exception
    assert at.metric[0].value == '2'
    assert get_reviews(init_db())[0]['status'] == 'contatado'
    assert get_states(['00000000000191'], init_db()) == []
    at.run()  # O mesmo evento não é aplicado duas vezes.
    assert len(get_reviews(init_db())) == 1
    next(w for w in at.selectbox if w.label == 'Histórico de contato').set_value('Contatadas').run()
    assert at.metric[0].value == '1'
    assert not at.exception
