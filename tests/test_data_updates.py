import base64
import hashlib
import io
import json

import pandas as pd
import pytest

from src.data_updates import (DataUpdateError, GitHubDataClient, LAST_DISPATCH,
                              active_data_paths, checked_scope, city_catalog, install_snapshot)
from src.reviews import export_reviews


class Response:
    def __init__(self, status=200, body=None):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.headers, self.calls, self.responses = {}, [], list(responses)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def content(raw):
    sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    return Response(body={"sha": sha, "size": len(raw), "encoding": "base64",
                          "content": base64.b64encode(raw).decode()})


@pytest.fixture(autouse=True)
def reset_dispatch():
    LAST_DISPATCH.clear()
    yield
    LAST_DISPATCH.clear()


def test_official_city_catalog_preserves_receita_codes_and_ufs():
    catalog = city_catalog()
    assert len(catalog) >= 5500
    gv = checked_scope({"uf": "MG", "municipio_code": "4553"})
    assert gv == {"uf": "MG", "municipio_code": "4553", "nome": "Governador Valadares"}
    assert catalog.loc[catalog.uf.eq('RO'), 'municipio_code'].str.startswith('0').any()
    with pytest.raises(ValueError):
        checked_scope({"uf": "ES", "municipio_code": "4553"})
    with pytest.raises(ValueError):
        checked_scope({"uf": "MG", "municipio_code": "3127701"})


def test_dispatch_uses_selected_city_and_blocks_double_submission():
    session = Session([Response(body={"workflow_runs": []}), Response(204)])
    client = GitHubDataClient('private-token', session=session)
    result = client.request_update({"uf": "MG", "municipio_code": "4553"})
    method, url, kwargs = session.calls[-1]
    assert method == 'POST' and url.endswith('/dispatches')
    assert kwargs['json']['inputs']['adicionar_municipios'] == '4553'
    assert kwargs['json']['inputs']['solicitacao'] == result['id']
    assert kwargs['json']['ref'] == 'main'
    with pytest.raises(DataUpdateError, match='um minuto'):
        client.request_update()
    assert len(session.calls) == 2


def test_active_update_and_invalid_credentials_do_not_dispatch():
    session = Session([Response(body={"workflow_runs": [{"event": "workflow_dispatch", "status": "queued"}]})])
    with pytest.raises(DataUpdateError, match='andamento'):
        GitHubDataClient('private-token', session=session).request_update()
    assert len(session.calls) == 1
    with pytest.raises(DataUpdateError) as exc:
        GitHubDataClient('private-token', session=Session([Response(403)])).runs()
    assert 'private-token' not in str(exc.value)


def test_remote_contacts_merge_and_retry_conflict_without_losing_other_company():
    first = {'cnpj': '00000000000191', 'status': 'contatado', 'source': 'manual'}
    second = {'cnpj': '11222333000181', 'status': 'contatado', 'source': 'outra sessão'}
    original = export_reviews([]).encode()
    concurrent = export_reviews([second]).encode()
    session = Session([content(original), Response(409), content(concurrent), Response(200)])
    client = GitHubDataClient('private-token', session=session)
    client.save_contacts([first])
    payload = session.calls[-1][2]['json']
    written = base64.b64decode(payload['content']).decode()
    assert first['cnpj'] in written and second['cnpj'] in written
    assert payload['sha'] == content(concurrent).body['sha']
    assert session.calls[-1][1].endswith('/contents/state/contacted_cnpjs.csv')
    # Repetir a confirmação já persistida não gera novo commit.
    client = GitHubDataClient('private-token', session=Session([content(written.encode())]))
    client.save_contacts([first])
    assert len(client.session.calls) == 1


def test_git_blob_checksum_is_verified_before_using_remote_history():
    response = content(b'cnpj,status,source\n')
    response.body['sha'] = '0' * 40
    with pytest.raises(DataUpdateError, match='integridade'):
        GitHubDataClient('private-token', session=Session([response])).contact_registry()


def snapshot():
    from src.demo import demo_data
    from datetime import date
    frame = demo_data(date(2026, 10, 28))
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    meta = {"rows": len(frame), "scopes": [checked_scope({"uf": "MG", "municipio_code": "4553"})],
            "generated_at_utc": "2026-10-28T12:00:00+00:00"}
    return buffer.getvalue(), json.dumps(meta).encode()


def test_snapshot_is_activated_only_after_validating_both_files(tmp_path):
    parquet, metadata = snapshot()
    install_snapshot(tmp_path, 'a' * 40, parquet, metadata)
    before = active_data_paths(tmp_path)
    assert before[0].is_file() and before[1].is_file()
    with pytest.raises(DataUpdateError):
        install_snapshot(tmp_path, 'b' * 40, b'incomplete parquet', metadata)
    assert active_data_paths(tmp_path) == before
    bad_meta = json.loads(metadata)
    bad_meta['rows'] = 999
    with pytest.raises(DataUpdateError):
        install_snapshot(tmp_path, 'c' * 40, parquet, json.dumps(bad_meta).encode())
    assert active_data_paths(tmp_path) == before
    assert not list((tmp_path / 'data/downloaded').glob('load_*'))


def test_download_reads_metadata_and_parquet_at_exact_same_commit(tmp_path):
    parquet, metadata = snapshot()
    head = 'e' * 40
    session = Session([Response(body={"sha": head}), content(metadata), content(parquet)])
    result = GitHubDataClient('private-token', session=session).download_snapshot(tmp_path)
    assert result['rows'] == 4
    assert all(call[2]['params']['ref'] == head for call in session.calls[1:])
    # Um redeploy com uma carga mais nova prevalece sobre uma cópia baixada antiga.
    data = tmp_path / 'data'
    (data / 'companies.parquet').write_bytes(parquet)
    newer = json.loads(metadata)
    newer['generated_at_utc'] = '2026-10-29T12:00:00+00:00'
    (data / 'release.json').write_text(json.dumps(newer))
    assert active_data_paths(tmp_path) == (data / 'companies.parquet', data / 'release.json')


def test_runtime_data_root_uses_bundled_base_without_losing_persistent_snapshot(tmp_path):
    from src.data_updates import active_data_paths
    runtime=tmp_path/'runtime';bundle=tmp_path/'bundle'
    (bundle/'data').mkdir(parents=True)
    (bundle/'data/companies.parquet').touch()
    (bundle/'data/release.json').write_text('{"generated_at_utc":"2026-01-01T00:00:00Z"}')
    assert active_data_paths(runtime,bundle)==(bundle/'data/companies.parquet',bundle/'data/release.json')
    version='a'*40
    folder=runtime/'data/downloaded'/version;folder.mkdir(parents=True)
    (folder/'companies.parquet').touch();(folder/'release.json').write_text('{"generated_at_utc":"2026-02-01T00:00:00Z"}')
    (runtime/'data/active_snapshot.json').write_text('{"version":"'+version+'"}')
    assert active_data_paths(runtime,bundle)[0]==folder/'companies.parquet'
    (bundle/'data/release.json').write_text('{"generated_at_utc":"2026-03-01T00:00:00Z"}')
    assert active_data_paths(runtime,bundle)[0]==bundle/'data/companies.parquet'
