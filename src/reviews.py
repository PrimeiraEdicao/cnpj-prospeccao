"""Importação de listas revisadas, independente da base e das aberturas do WhatsApp."""
from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .utils import digits, normalize_text, strip_accents

REVIEW_LABELS = {
    "revisado": "Revisado anteriormente — contato ou descarte",
    "contatado": "Já contatado",
    "fora_perfil": "Fora do perfil",
}
MAX_UNCOMPRESSED = 100 * 1024 * 1024
MAX_FILES = 500


def import_cnpj(value) -> str | None:
    """Valida identificadores numéricos e recupera zeros perdidos em células numéricas."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if value < 0:
            return None
        if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
            return None
        number = str(int(value)).zfill(14)
    else:
        text = str(value).strip()
        if not re.fullmatch(r"[0-9\s./-]+", text):
            return None
        number = digits(text)
    if len(number) != 14 or len(set(number)) == 1:
        return None
    for size, weights in ((12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
                          (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))):
        remainder = sum(int(n) * w for n, w in zip(number[:size], weights)) % 11
        if int(number[size]) != (0 if remainder < 2 else 11 - remainder):
            return None
    return number


def _header(value) -> str:
    return re.sub(r"[^a-z0-9]", "", strip_accents(normalize_text(value)).lower())


@dataclass
class ImportReport:
    records: dict[str, dict] = field(default_factory=dict)
    valid_rows: int = 0
    invalid_rows: int = 0
    blank_rows: int = 0
    files_read: int = 0
    ignored: list[str] = field(default_factory=list)

    @property
    def duplicates(self):
        return self.valid_rows - len(self.records)

    def add(self, value, status: str, source: str):
        if value is None or not str(value).strip():
            self.blank_rows += 1
            return
        number = import_cnpj(value)
        if not number:
            self.invalid_rows += 1
            return
        self.valid_rows += 1
        if number in self.records:
            sources = set(self.records[number]["source"].split(" | "))
            sources.add(source)
            self.records[number]["source"] = " | ".join(sorted(sources))
        else:
            self.records[number] = {"cnpj": number, "status": status, "source": source}


def _archive_budget(archive):
    members = [m for m in archive.infolist() if not m.is_dir()]
    if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_UNCOMPRESSED:
        raise ValueError("Arquivo excede o limite de 500 arquivos ou 100 MB descompactados.")
    return members


def _tabular_rows(rows, source: str, status: str, report: ImportReport):
    rows = iter(rows)
    for _ in range(20):
        header = next(rows, None)
        if header is None:
            break
        keys = [_header(v) for v in header]
        cnpj_col = next((i for i, key in enumerate(keys) if key in {"cnpj", "cnpjcompleto"}), None)
        if cnpj_col is None:
            continue
        status_col = keys.index("status") if "status" in keys else None
        source_col = keys.index("source") if "source" in keys else None
        for row in rows:
            row_status = (str(row[status_col]) if status_col is not None and len(row) > status_col else status)
            row_status = row_status if row_status in REVIEW_LABELS else status
            row_source = (normalize_text(row[source_col]) if source_col is not None and len(row) > source_col else "")
            report.add(row[cnpj_col] if len(row) > cnpj_col else None,
                       row_status, row_source or source)
        return True
    report.ignored.append(f"{source}: sem coluna CNPJ")
    return False


def _read_file(name: str, data: bytes, status: str, report: ImportReport):
    suffix = Path(name).suffix.lower()
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            _archive_budget(archive)
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            read = False
            for sheet in workbook:
                read |= _tabular_rows(sheet.values, f"{name}/{sheet.title}", status, report)
            report.files_read += int(read)
        finally:
            workbook.close()
    elif suffix in {".csv", ".txt"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin1")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            report.ignored.append(f"{name}: vazio")
            return
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
            rows = list(csv.reader(io.StringIO(text), dialect))
        except csv.Error:
            rows = [[line] for line in lines]
        if any(_header(v) in {"cnpj", "cnpjcompleto"} for v in rows[0]):
            report.files_read += int(_tabular_rows(rows, name, status, report))
        elif all(len(row) == 1 for row in rows) and any(import_cnpj(row[0]) for row in rows):
            report.files_read += 1
            for row in rows:
                report.add(row[0], status, name)
        else:
            report.ignored.append(f"{name}: sem coluna ou lista de CNPJs válidos")
    else:
        report.ignored.append(f"{name}: formato não suportado")


def parse_review_files(files: list[tuple[str, bytes]], status: str = "revisado") -> ImportReport:
    if status not in REVIEW_LABELS:
        raise ValueError("Selecione um motivo de revisão válido.")
    report = ImportReport()
    if len(files) > MAX_FILES or sum(len(data) for _, data in files) > MAX_UNCOMPRESSED:
        raise ValueError("Importação excede o limite de 500 arquivos ou 100 MB.")
    entries = 0
    total = 0
    def read_checked(name, data):
        try:
            _read_file(name, data, status, report)
        except Exception as exc:
            raise ValueError(f"Não foi possível ler {name}. Confira se o arquivo está íntegro. {exc}") from exc

    for name, data in files:
        if Path(name).suffix.lower() == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in _archive_budget(archive):
                    entries += 1
                    total += member.file_size
                    if entries > MAX_FILES or total > MAX_UNCOMPRESSED:
                        raise ValueError("Importação excede o limite descompactado.")
                    # Lê na memória; nunca extrai caminhos fornecidos pelo ZIP.
                    read_checked(f"{Path(name).name}/{member.filename}", archive.read(member))
        else:
            entries += 1
            total += len(data)
            read_checked(Path(name).name, data)
    return report


def export_reviews(records) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["cnpj", "status", "source"], lineterminator="\n")
    writer.writeheader()
    for row in sorted(records, key=lambda r: r["cnpj"]):
        writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    return output.getvalue()


def load_review_registry(path: Path) -> list[dict]:
    if not path.exists():
        return []
    report = parse_review_files([(path.name, path.read_bytes())])
    if report.invalid_rows or report.ignored:
        raise ValueError("Lista versionada de revisão contém CNPJ ou formato inválido.")
    return list(report.records.values())


def combine_reviews(registry, database) -> list[dict]:
    # Classificações feitas explicitamente no app prevalecem sobre o lote genérico.
    records = {row["cnpj"]: row for row in registry}
    records.update({row["cnpj"]: row for row in database})
    return list(records.values())


def apply_reviews(df: pd.DataFrame, records) -> pd.DataFrame:
    df = df.copy()
    lookup = {row["cnpj"]: row for row in records}
    numbers = df["cnpj"].map(digits)
    df["reviewed"] = numbers.isin(lookup)
    df["review_status"] = numbers.map(lambda n: lookup.get(n, {}).get("status", ""))
    df["review_label"] = df["review_status"].map(REVIEW_LABELS).fillna("")
    return df
