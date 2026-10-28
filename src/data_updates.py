"""Cliente servidor-servidor para cargas da Receita e histórico durável no GitHub."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
import requests

from .reviews import export_reviews, parse_review_files
from .scopes import validate_scopes

CATALOG_SOURCE = "https://www.gov.br/receitafederal/dados/municipios.csv/@@download/file"
CATALOG = Path(__file__).resolve().parents[1] / "config/municipalities.csv"
STATE_FILE = "state/contacted_cnpjs.csv"
WORKFLOW = "update-receita.yml"
API_ROOT = "https://api.github.com"
LOCK = threading.Lock()
LAST_DISPATCH = {}
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}


def city_catalog() -> pd.DataFrame:
    data = pd.read_csv(CATALOG, dtype=str, keep_default_na=False)
    if data.duplicated(["uf", "municipio_code"]).any():
        raise ValueError("Catálogo de cidades contém códigos repetidos.")
    validate_scopes(data.to_dict("records"))
    return data


def checked_scope(scope: dict) -> dict:
    normalized = validate_scopes([scope])[0]
    data = city_catalog()
    found = data[data.uf.eq(normalized["uf"]) & data.municipio_code.eq(normalized["municipio_code"])]
    if len(found) != 1:
        raise ValueError("Cidade não encontrada no catálogo oficial da Receita.")
    return {"uf": normalized["uf"], "municipio_code": normalized["municipio_code"], "nome": found.iloc[0]["nome"]}


class DataUpdateError(RuntimeError):
    pass


class GitHubDataClient:
    def __init__(self, token: str, repository="PrimeiraEdicao/cnpj-prospeccao", branch="main", session=None):
        if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Configure a credencial e um repositório válido para atualizar os dados.")
        self.repository, self.branch = repository, branch
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28"})

    def _request(self, method, suffix, *, expected=(200,), **kwargs):
        try:
            response = self.session.request(method, f"{API_ROOT}/repos/{self.repository}/{suffix}",
                                            timeout=(10, 90), **kwargs)
        except requests.RequestException:
            raise DataUpdateError("Não foi possível conectar ao serviço de dados. Tente novamente.") from None
        if response.status_code not in expected:
            # Não propaga cabeçalhos, tokens nem respostas remotas para a interface.
            raise DataUpdateError(f"Serviço de dados respondeu HTTP {response.status_code}. Confira os Secrets e as permissões do repositório.")
        return response

    def runs(self):
        return self._request("GET", f"actions/workflows/{WORKFLOW}/runs",
                             params={"branch": self.branch, "per_page": 30}).json()["workflow_runs"]

    def request_update(self, scope=None):
        scope = checked_scope(scope) if scope else None
        with LOCK:
            key = (self.repository, self.branch)
            if time.monotonic() - LAST_DISPATCH.get(key, -1e9) < 60:
                raise DataUpdateError("A solicitação anterior ainda está sendo registrada. Aguarde um minuto e consulte o andamento.")
            runs = self.runs()
            if any(r.get("event") != "pull_request" and r["status"] in ACTIVE_STATUSES for r in runs):
                raise DataUpdateError("Já existe uma atualização ou validação em andamento. Aguarde a conclusão antes de solicitar outra.")
            request_id = uuid.uuid4().hex
            inputs = {"solicitacao": request_id}
            if scope:
                inputs.update(adicionar_uf=scope["uf"], adicionar_municipios=scope["municipio_code"], nome_cidade=scope["nome"])
            self._request("POST", f"actions/workflows/{WORKFLOW}/dispatches", expected=(204,),
                          json={"ref": self.branch, "inputs": inputs})
            LAST_DISPATCH[key] = time.monotonic()
        return {"id": request_id, "scope": scope}

    def _content(self, path, ref=None, allow_missing=False):
        response = self._request("GET", f"contents/{path}", params={"ref": ref or self.branch},
                                 expected=(200, 404) if allow_missing else (200,))
        if response.status_code == 404:
            return None, None
        data = response.json()
        if data.get("size", 0) > 80 * 1024 * 1024:
            raise DataUpdateError("A base excede o tamanho suportado nesta hospedagem. Reduza o recorte de cidades.")
        content = data.get("content")
        if data.get("encoding") != "base64" or not content:
            content = self._request("GET", f"git/blobs/{data['sha']}").json()["content"]
        try:
            raw = base64.b64decode("".join(content.split()), validate=True)
        except (ValueError, TypeError):
            raise DataUpdateError("O arquivo recebido está incompleto. A base anterior foi mantida.") from None
        actual = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        if actual != data["sha"]:
            raise DataUpdateError("A integridade do arquivo recebido não confere. A base anterior foi mantida.")
        return raw, data["sha"]

    def contact_registry(self):
        raw, _ = self._content(STATE_FILE, allow_missing=True)
        if raw is None:
            return []
        report = parse_review_files([("contacted.csv", raw)])
        if report.invalid_rows or report.ignored:
            raise DataUpdateError("O histórico remoto contém registros inválidos. Nenhuma alteração foi feita.")
        return list(report.records.values())

    def save_contacts(self, records):
        with LOCK:
            for _ in range(3):
                raw, sha = self._content(STATE_FILE, allow_missing=True)
                report = parse_review_files([("contacted.csv", raw or b"cnpj,status,source\n")])
                if report.invalid_rows or report.ignored:
                    raise DataUpdateError("O histórico remoto precisa ser revisado antes de salvar novos contatos.")
                merged = report.records
                for record in records:
                    merged.setdefault(record["cnpj"], record)
                content = export_reviews(merged.values()).encode()
                if raw == content:
                    return
                payload = {"message": "state: registrar empresas contatadas", "branch": self.branch,
                           "content": base64.b64encode(content).decode()}
                if sha:
                    payload["sha"] = sha
                response = self._request("PUT", f"contents/{STATE_FILE}", expected=(200, 201, 409, 422), json=payload)
                if response.status_code in (200, 201):
                    return
            raise DataUpdateError("O histórico foi alterado simultaneamente. Atualize a lista e tente novamente.")

    def download_snapshot(self, root: Path):
        # Os arquivos são buscados no MESMO commit para não misturar competências.
        head = self._request("GET", f"commits/{self.branch}").json()["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise DataUpdateError("Versão de dados inválida.")
        raw_meta, _ = self._content("data/release.json", ref=head)
        raw_data, _ = self._content("data/companies.parquet", ref=head)
        return install_snapshot(root, head, raw_data, raw_meta)


def active_data_paths(root: Path) -> tuple[Path, Path]:
    data = root / "data"
    pointer = data / "active_snapshot.json"
    if pointer.exists():
        try:
            version = json.loads(pointer.read_text())["version"]
            if re.fullmatch(r"[0-9a-f]{40}", version):
                folder = data / "downloaded" / version
                if (folder / "companies.parquet").is_file() and (folder / "release.json").is_file():
                    # Um redeploy pode trazer uma competência mais recente no próprio repositório.
                    bundled_meta = data / "release.json"
                    if bundled_meta.exists() and (data / "companies.parquet").is_file():
                        bundled = json.loads(bundled_meta.read_text()).get("generated_at_utc", "")
                        local = json.loads((folder / "release.json").read_text()).get("generated_at_utc", "")
                        if bundled and local and pd.Timestamp(bundled) > pd.Timestamp(local):
                            return data / "companies.parquet", bundled_meta
                    return folder / "companies.parquet", folder / "release.json"
        except (ValueError, KeyError, TypeError, OSError):
            pass
    return data / "companies.parquet", data / "release.json"


def install_snapshot(root: Path, version: str, parquet: bytes, metadata: bytes):
    if not re.fullmatch(r"[0-9a-f]{40}", version):
        raise DataUpdateError("Versão inválida.")
    data = root / "data"
    parent = data / "downloaded"
    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="load_", dir=parent))
    try:
        (temp / "companies.parquet").write_bytes(parquet)
        (temp / "release.json").write_bytes(metadata)
        meta = json.loads(metadata)
        validate_scopes(meta["scopes"])
        frame = pd.read_parquet(temp / "companies.parquet")
        required = {"cnpj", "razao_social", "data_abertura", "uf", "municipio", "cnae_fiscal_principal"}
        if not required.issubset(frame.columns) or len(frame) != int(meta["rows"]) or frame.cnpj.duplicated().any():
            raise ValueError("Linhas ou colunas inconsistentes")
        with LOCK:
            target = parent / version
            if not target.exists():
                temp.rename(target)
            pointer = data / "active_snapshot.json"
            temporary_pointer = data / f".active_{uuid.uuid4().hex}.json"
            temporary_pointer.write_text(json.dumps({"version": version}))
            temporary_pointer.replace(pointer)
        return meta
    except (ValueError, KeyError, TypeError, OSError):
        raise DataUpdateError("Não foi possível validar a nova base. A base anterior foi mantida.") from None
    finally:
        if temp.exists():
            shutil.rmtree(temp)
