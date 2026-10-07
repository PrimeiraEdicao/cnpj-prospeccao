import io
import zipfile
from html import escape
from pathlib import Path

import pandas as pd
import pytest

from src.prospecting import filter_data, now_local, prepare_data
from src.reviews import (apply_reviews, combine_reviews, export_reviews, import_cnpj,
                         load_review_registry, parse_review_files)
from src.state import get_reviews, get_states, import_reviews, init_db, record_attempt
from src.demo import demo_data

FIRST = "00000000000191"
SECOND = "11222333000181"


def xlsx_bytes(rows):
    """Fixture XLSX mínima com células de texto e números (sem dependência de escrita)."""
    content = io.BytesIO()
    sheet_rows = []
    for n, row in enumerate(rows, 1):
        cells = []
        for col, value in enumerate(row):
            ref = f"{chr(65 + col)}{n}"
            cells.append(f'<c r="{ref}"><v>{value}</v></c>' if isinstance(value, (int, float)) else
                         f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        sheet_rows.append(f'<row r="{n}">' + "".join(cells) + '</row>')
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Empresas" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(sheet_rows) + '</sheetData></worksheet>')
    return content.getvalue()


def test_zip_reads_excel_and_deduplicates_cnpj_without_using_phones(tmp_path):
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as archive:
        archive.writestr('a.xlsx', xlsx_bytes([['CNPJ', 'Contatos'], ['00.000.000/0001-91', '5533999999999'], [SECOND, '']]))
        archive.writestr('b.xlsx', xlsx_bytes([['CNPJ'], [191], ['11.222.333/0001-81'], ['inválido'], ['']]))
        archive.writestr('numeros_memoria.txt', '5533999999999\n5533988888888\n')
    report = parse_review_files([('lista.zip', content.getvalue())])
    assert set(report.records) == {FIRST, SECOND}
    assert report.valid_rows == 4 and report.duplicates == 2
    assert report.invalid_rows == 1 and report.blank_rows == 1
    assert report.files_read == 2
    assert len(report.ignored) == 1 and 'numeros_memoria' in report.ignored[0]
    assert all(row['status'] == 'revisado' for row in report.records.values())
    assert 'a.xlsx' in report.records[FIRST]['source'] and 'b.xlsx' in report.records[FIRST]['source']


def test_validation_and_csv_backup_keep_leading_zeros_status_and_source(tmp_path):
    assert import_cnpj(191.0) == FIRST
    for value in [-1, True, float('nan'), 191.5, '00000000000000', '00.000.000/0001-90', '55(33)999999999']:
        assert import_cnpj(value) is None
    report = parse_review_files([('lista.txt', f'{FIRST}\n11.222.333/0001-81\n'.encode())], 'fora_perfil')
    path = tmp_path / 'review.csv'
    path.write_text(export_reviews(report.records.values()), encoding='utf8')
    assert load_review_registry(path) == list(report.records.values())
    # Sem coluna CNPJ, telefone em outra coluna não pode virar identificador.
    report = parse_review_files([('telefone.csv', f'Telefone;Nome\n{FIRST};teste\n'.encode())])
    assert not report.records


def test_malformed_excel_and_oversized_zip_report_errors(monkeypatch):
    with pytest.raises(ValueError, match='íntegro'):
        parse_review_files([('invalido.xlsx', b'not an excel file')])
    monkeypatch.setattr('src.reviews.MAX_UNCOMPRESSED', 100)
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('lista.txt', b'0' * 1000)
    with pytest.raises(ValueError, match='limite'):
        parse_review_files([('lista.zip', content.getvalue())])


def test_database_import_is_idempotent_preserves_attempts_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{tmp_path / 'state.db'}")
    engine = init_db()
    record_attempt('existing', FIRST, '5533999999999', 'Maria', 'Olá', engine)
    records = [{'cnpj': FIRST, 'status': 'contatado', 'source': 'antigo.csv'},
               {'cnpj': SECOND, 'status': 'fora_perfil', 'source': 'antigo.csv'}]
    assert import_reviews(records, engine) == (2, 0)
    first_review = get_reviews(engine)
    assert import_reviews(records + records, engine) == (0, 2)
    assert get_reviews(engine) == first_review
    assert get_states([FIRST], engine)[0]['attempt_count'] == 1
    assert get_states([SECOND], engine) == []
    engine.dispose()
    assert len(get_reviews(init_db())) == 2
    with pytest.raises(ValueError):
        import_reviews([{'cnpj': FIRST, 'status': 'revisado'}, {'cnpj': '1', 'status': 'revisado'}], init_db())
    assert len(get_reviews(init_db())) == 2


def test_review_list_remains_effective_after_new_snapshot_and_is_independent_of_history():
    data = prepare_data(demo_data(now_local().date()))
    data['cnpj'] = [FIRST, SECOND, '04252011000110', '99999999999999']
    data['idade_anos'] = 2
    data['attempt_count'] = 0
    registry = [{'cnpj': FIRST, 'status': 'revisado', 'source': 'a.csv'}]
    database = [{'cnpj': SECOND, 'status': 'fora_perfil', 'source': 'b.csv'}]
    records = combine_reviews(registry, database)
    loaded = apply_reviews(data, records)
    assert set(filter_data(loaded)['cnpj']) == {'04252011000110'}
    assert len(filter_data(loaded, hide_reviewed=False)) == 3
    assert len(filter_data(loaded, contact_status='Todos')) == 1
    reloaded = apply_reviews(pd.concat([data, data.iloc[:1]], ignore_index=True), records)
    assert FIRST not in set(filter_data(reloaded)['cnpj'])


def test_versioned_registry_is_valid_unique_and_contains_no_contact_details():
    path = Path(__file__).resolve().parents[1] / 'config/reviewed_cnpjs.csv'
    records = load_review_registry(path)
    assert len(records) == len({r['cnpj'] for r in records})
    assert len(records) >= 1544
    assert all(import_cnpj(r['cnpj']) == r['cnpj'] for r in records)
    assert set(records[0]) == {'cnpj', 'status', 'source'}
