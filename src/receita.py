from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT_URL = "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/"
USER_AGENT = "Mozilla/5.0 (compatible; CNPJProspeccao/1.0; +https://github.com/)"


@dataclass(frozen=True)
class Release:
    name: str
    url: str


def _get(url: str, timeout: int = 120) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return r


def discover_releases(root_url: str = ROOT_URL) -> list[Release]:
    html = _get(root_url).text
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Release] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"(20\d{2}-\d{2})/?$", href)
        if not m:
            continue
        name = m.group(1)
        found[name] = Release(name=name, url=urljoin(root_url, href if href.endswith("/") else href + "/"))
    return sorted(found.values(), key=lambda x: x.name)


def resolve_release(requested: str | None = None, root_url: str = ROOT_URL) -> Release:
    releases = discover_releases(root_url)
    if not releases:
        raise RuntimeError("Não foi possível descobrir competências no diretório público da Receita.")
    if requested:
        for rel in releases:
            if rel.name == requested:
                return rel
        raise ValueError(f"Competência {requested!r} não encontrada. Última disponível: {releases[-1].name}")
    return releases[-1]


def list_zip_urls(release: Release) -> list[str]:
    html = _get(release.url).text
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".zip"):
            urls.append(urljoin(release.url, href))
    return sorted(set(urls))


def select_files(urls: list[str], token: str) -> list[str]:
    token_lower = token.lower()
    return [u for u in urls if token_lower in Path(u).name.lower()]


def download(url: str, destination: str | Path, chunk_size: int = 2**20) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(partial, "wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
    partial.replace(destination)
    return destination


class TempDownload:
    """Baixa um ZIP para diretório temporário e remove após o uso."""

    def __init__(self, url: str, tmp_root: str | Path | None = None):
        self.url = url
        self.tmp_root = Path(tmp_root) if tmp_root else None
        self._dir: Path | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self._dir = Path(tempfile.mkdtemp(prefix="rfb_", dir=self.tmp_root))
        self.path = download(self.url, self._dir / Path(self.url).name)
        return self.path

    def __exit__(self, exc_type, exc, tb):
        if self._dir and self._dir.exists():
            shutil.rmtree(self._dir, ignore_errors=True)
