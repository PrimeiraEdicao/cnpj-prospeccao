from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urljoin
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Desde 2026, a Receita publica o CNPJ em um compartilhamento público Nextcloud/WebDAV.
# O token abaixo é o compartilhamento oficial atualmente divulgado no catálogo do CNPJ.
SHARE_TOKEN = os.getenv("RECEITA_SHARE_TOKEN", "YggdBLfdninEJX9")
WEBDAV_ROOT_URL = os.getenv(
    "RECEITA_WEBDAV_URL",
    "https://arquivos.receitafederal.gov.br/public.php/webdav",
).rstrip("/")
DIRECT_FILES_ROOT_URL = os.getenv(
    "RECEITA_DIRECT_FILES_URL",
    f"https://arquivos.receitafederal.gov.br/public.php/dav/files/{SHARE_TOKEN}",
).rstrip("/")

# Mantido como alias por compatibilidade com chamadas antigas do módulo.
ROOT_URL = WEBDAV_ROOT_URL
USER_AGENT = os.getenv(
    "RECEITA_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
)
DAV_NS = {"d": "DAV:"}
MIRROR_ROOT_URL = os.getenv(
    "RECEITA_MIRROR_URL",
    "https://dados-abertos-rf-cnpj.casadosdados.com.br/arquivos/",
).rstrip("/") + "/"


@dataclass(frozen=True)
class Release:
    name: str
    url: str


def _build_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=1.5,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD", "PROPFIND"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _build_session()


def _propfind(url: str, timeout: int = 20) -> bytes:
    """Lista um diretório do compartilhamento público da Receita via WebDAV."""
    response = _SESSION.request(
        "PROPFIND",
        url.rstrip("/") + "/",
        auth=(SHARE_TOKEN, ""),
        headers={"Depth": "1"},
        timeout=(30, timeout),
    )
    response.raise_for_status()
    return response.content


def _dav_hrefs(content: bytes) -> list[str]:
    root = ElementTree.fromstring(content)
    hrefs: list[str] = []
    for item in root.findall("d:response", DAV_NS):
        href = item.findtext("d:href", default="", namespaces=DAV_NS)
        if href:
            hrefs.append(unquote(href))
    return hrefs


def _release_names_from_dav(content: bytes) -> list[str]:
    found: set[str] = set()
    for href in _dav_hrefs(content):
        match = re.search(r"/(20\d{2}-\d{2})/?$", href)
        if match:
            found.add(match.group(1))
    return sorted(found)


def _zip_names_from_dav(content: bytes) -> list[str]:
    found: set[str] = set()
    for href in _dav_hrefs(content):
        match = re.search(r"/([^/]+\.zip)$", href, flags=re.IGNORECASE)
        if match:
            found.add(match.group(1))
    return sorted(found)


def _mirror_releases(root_url: str = MIRROR_ROOT_URL) -> list[Release]:
    response = _SESSION.get(root_url, timeout=(20, 40))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    by_month: dict[str, tuple[str, str]] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        match = re.search(r"(20\d{2}-\d{2}-\d{2})/?$", href)
        if not match:
            continue
        folder = match.group(1)
        month = folder[:7]
        previous = by_month.get(month)
        if previous is None or folder > previous[0]:
            by_month[month] = (folder, urljoin(root_url, href if href.endswith("/") else href + "/"))
    return [Release(name=month, url=info[1]) for month, info in sorted(by_month.items())]


def discover_releases(root_url: str = ROOT_URL) -> list[Release]:
    try:
        names = _release_names_from_dav(_propfind(root_url))
        if names:
            return [Release(name=name, url=f"{root_url.rstrip('/')}/{name}/") for name in names]
    except (requests.RequestException, ElementTree.ParseError, OSError):
        pass

    # GitHub-hosted runners podem ter a conexão encerrada/bloqueada pela origem da RFB.
    # Nesse caso, usa um espelho público que replica os mesmos ZIPs da Receita via CDN.
    return _mirror_releases()


def resolve_release(requested: str | None = None, root_url: str = ROOT_URL) -> Release:
    releases = discover_releases(root_url)
    if not releases:
        raise RuntimeError(
            "Não foi possível descobrir competências no compartilhamento WebDAV público da Receita."
        )
    if requested:
        for rel in releases:
            if rel.name == requested:
                return rel
        raise ValueError(
            f"Competência {requested!r} não encontrada. Última disponível: {releases[-1].name}"
        )
    return releases[-1]


def _mirror_release_for_month(month: str) -> Release | None:
    for release in _mirror_releases():
        if release.name == month:
            return release
    return None


def _list_mirror_zip_urls(release: Release) -> list[str]:
    response = _SESSION.get(release.url, timeout=(20, 40))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.lower().endswith(".zip"):
            urls.append(urljoin(release.url, href))
    return sorted(set(urls))


def list_zip_urls(release: Release) -> list[str]:
    if release.url.startswith(MIRROR_ROOT_URL):
        return _list_mirror_zip_urls(release)

    try:
        names = _zip_names_from_dav(_propfind(release.url))
        if names:
            base = f"{DIRECT_FILES_ROOT_URL}/{release.name}"
            return [f"{base}/{quote(name)}" for name in names]
    except (requests.RequestException, ElementTree.ParseError, OSError):
        pass

    mirror = _mirror_release_for_month(release.name)
    if mirror is None:
        raise RuntimeError(f"Competência {release.name} não encontrada no espelho de contingência.")
    return _list_mirror_zip_urls(mirror)


def select_files(urls: list[str], token: str) -> list[str]:
    token_lower = token.lower()
    return [u for u in urls if token_lower in unquote(Path(u).name).lower()]


def download(
    url: str,
    destination: str | Path,
    chunk_size: int = 2**20,
    attempts: int = 5,
) -> Path:
    """Baixa arquivo grande com tentativas e retomada parcial por HTTP Range."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        existing = partial.stat().st_size if partial.exists() else 0
        headers: dict[str, str] = {}
        if existing:
            headers["Range"] = f"bytes={existing}-"

        try:
            with _SESSION.get(
                url,
                headers=headers,
                stream=True,
                timeout=(30, 300),
            ) as response:
                response.raise_for_status()

                # Se o servidor ignorar Range e devolver 200, recomeça para não duplicar bytes.
                resume = existing > 0 and response.status_code == 206
                mode = "ab" if resume else "wb"
                with open(partial, mode) as handle:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            handle.write(chunk)

            partial.replace(destination)
            return destination
        except (requests.RequestException, OSError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 16))

    raise RuntimeError(f"Falha ao baixar {url} após {attempts} tentativas") from last_error


class TempDownload:
    """Baixa um ZIP para diretório temporário e remove após o uso."""

    def __init__(self, url: str, tmp_root: str | Path | None = None):
        self.url = url
        self.tmp_root = Path(tmp_root) if tmp_root else None
        self._dir: Path | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self._dir = Path(tempfile.mkdtemp(prefix="rfb_", dir=self.tmp_root))
        self.path = download(self.url, self._dir / unquote(Path(self.url).name))
        return self.path

    def __exit__(self, exc_type, exc, tb):
        if self._dir and self._dir.exists():
            shutil.rmtree(self._dir, ignore_errors=True)
