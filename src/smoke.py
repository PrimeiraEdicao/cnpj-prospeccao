"""Valida descoberta, catálogo e download real de um ZIP pequeno."""
import zipfile

from .constants import CNAE_COLS
from .etl import read_small_zip
from .receita import TempDownload, list_zip_urls, resolve_release, select_files, validate_zip_catalog


def main():
    release = resolve_release()
    urls = list_zip_urls(release)
    validate_zip_catalog(urls)
    print(f"Competência detectada: {release.name}", flush=True)
    print(f"Catálogo consultado: {release.url}", flush=True)
    print(f"Arquivos ZIP detectados: {len(urls)}", flush=True)
    with TempDownload(select_files(urls, "Cnaes")[0]) as path:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("ZIP de CNAEs corrompido")
        cnaes = read_small_zip(path, CNAE_COLS)
        if cnaes.empty:
            raise RuntimeError("Tabela de CNAEs vazia")
    print(f"Download e leitura validados: {len(cnaes)} CNAEs", flush=True)


if __name__ == "__main__":
    main()
