import csv
import io
import json
import zipfile
from pathlib import Path

import pandas as pd

from src import constants as c
from src import etl, receita


def zipped_csv(columns, records):
    text = io.StringIO()
    writer = csv.writer(text, delimiter=';', quoting=csv.QUOTE_ALL)
    writer.writerows([[row.get(col, '') for col in columns] for row in records])
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('DADOSCSV', text.getvalue().encode('latin1'))
    return content.getvalue()


def test_full_etl_reads_zips_joins_and_publishes_non_mei(tmp_path, monkeypatch):
    catalog = {}
    roots = ['11111111', '22222222', '33333333']
    estab = [dict(cnpj_basico=root, cnpj_ordem='0001', cnpj_dv='11',
                  uf='MG', municipio='4553', situacao_cadastral='02',
                  data_inicio_atividade='20200101', bairro='CENTRO',
                  cnae_fiscal_principal='6920601' if i == 2 else '4712100',
                  ddd_1='33', telefone_1='999999999') for i, root in enumerate(roots)]
    empresas = [dict(cnpj_basico=root, razao_social=name, natureza_juridica='2135' if i < 2 else '2062')
                for i, (root, name) in enumerate(zip(roots, ['MEI TESTE', 'MARIA TESTE', 'CONTABIL TESTE']))]
    partners = [dict(cnpj_basico='33333333', identificador_socio='2', nome_socio='JOAO TESTE',
                     qualificacao_socio='49', data_entrada_sociedade='20200101')]
    for prefix, columns, rows in [('Estabelecimentos', c.ESTAB_COLS, estab),
                                  ('Empresas', c.EMPRESA_COLS, empresas), ('Socios', c.SOCIO_COLS, partners)]:
        for i in range(10):
            # As nove outras partes contêm uma raiz fora do recorte, como numa carga nacional.
            records = rows if i == 0 else [dict(cnpj_basico='99999999', uf='SP', municipio='7107', situacao_cadastral='02')]
            catalog[f'https://example.test/{prefix}{i}.zip'] = zipped_csv(columns, records)
    simples = [dict(cnpj_basico=root, opcao_pelo_mei='S' if i == 0 else 'N', opcao_pelo_simples='S')
               for i, root in enumerate(roots)]
    for name, cols, rows in [('Simples', c.SIMPLES_COLS, simples),
                             ('Cnaes', c.CNAE_COLS, [{'codigo': '6920601', 'descricao': 'Contabilidade'}]),
                             ('Qualificacoes', c.QUALIFICACAO_COLS, [{'codigo': '49', 'descricao': 'Socio-Administrador'}])]:
        catalog[f'https://example.test/{name}.zip'] = zipped_csv(cols, rows)
    monkeypatch.setattr(etl, 'resolve_release', lambda name: receita.Release('2026-09', 'https://example.test/'))
    monkeypatch.setattr(etl, 'list_zip_urls', lambda release: list(catalog))
    class Response:
        status_code = 200
        def __init__(self, body): self.body = body; self.headers = {'Content-Length': str(len(body))}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, chunk_size): yield self.body
    monkeypatch.setattr(receita._SESSION, 'get', lambda url, **kw: Response(catalog[url]))
    exclusions = tmp_path / 'excluded.txt'
    exclusions.write_text('6920601\n')
    file = tmp_path / 'data/companies.parquet'
    result, meta = etl.run_etl('MG', '4553', file, chunksize=2, exclusion_file=exclusions)
    assert len(result) == 2
    assert set(result['cnpj_basico']) == {'22222222', '33333333'}
    assert set(result['primeiro_nome']) == {'Maria', 'Joao'}
    assert result.loc[result.cnpj_basico == '33333333', 'is_contabilidade'].item()
    pd.testing.assert_frame_equal(result, pd.read_parquet(file))
    assert json.loads(file.with_name('release.json').read_text())['rows'] == 2
    assert meta['zip_catalog']['Estabelecimentos'] == 10
