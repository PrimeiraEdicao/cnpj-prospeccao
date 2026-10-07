"""Atualiza a lista versionada: python -m scripts.import_reviews arquivo.zip."""
import argparse
from pathlib import Path

from src.reviews import REVIEW_LABELS, combine_reviews, export_reviews, load_review_registry, parse_review_files


def main():
    parser = argparse.ArgumentParser(description="Importar CNPJs revisados sem apagar a base Receita.")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--status", choices=REVIEW_LABELS, default="revisado")
    parser.add_argument("--output", default="config/reviewed_cnpjs.csv")
    args = parser.parse_args()
    report = parse_review_files([(Path(name).name, Path(name).read_bytes()) for name in args.files], args.status)
    if not report.records:
        parser.error("Nenhum CNPJ válido encontrado. Confira a coluna CNPJ ou a lista de 14 dígitos.")
    path = Path(args.output)
    # Uma reimportação não muda o motivo de registros anteriores.
    combined = combine_reviews(list(report.records.values()), load_review_registry(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".csv.tmp")
    temporary.write_text(export_reviews(combined), encoding="utf-8")
    temporary.replace(path)
    print(f"{report.files_read} arquivos; {report.valid_rows} linhas válidas; {len(report.records)} CNPJs únicos; "
          f"{report.duplicates} repetições; {report.invalid_rows} inválidos; {report.blank_rows} vazios.")
    print(f"Lista persistente: {path} ({len(combined)} CNPJs).")
    for ignored in report.ignored:
        print(f"Ignorado: {ignored}")


if __name__ == "__main__":
    main()
