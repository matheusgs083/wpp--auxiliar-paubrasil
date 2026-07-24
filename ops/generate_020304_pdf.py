from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot_api.services.filial_labels import FILIAL_LABELS
from bot_api.services.relatorio_020304_pdf_service import (
    read_020304_csv,
    summarize_020304_rows,
    write_020304_pdf,
)


def main() -> None:
    args = _parse_args()
    source_path = args.source_path.expanduser().resolve()
    reference_date = _parse_date(args.reference_date) if args.reference_date else _file_date(source_path)
    filial_nome = args.filial_nome or FILIAL_LABELS.get(args.filial, "")
    output_path = args.output_path or _default_output_path(
        source_path,
        filial=args.filial,
        filial_nome=filial_nome,
        reference_date=reference_date,
    )

    try:
        rows = read_020304_csv(source_path)
        summary = summarize_020304_rows(
            rows,
            filial=args.filial,
            filial_nome=filial_nome,
            reference_date=reference_date,
            source_name=source_path.name,
        )
        write_020304_pdf(
            source_path,
            output_path,
            filial=args.filial,
            filial_nome=filial_nome,
            reference_date=reference_date,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "output_path": str(output_path.resolve()),
                    "summary": summary.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "detail": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera um PDF modelo do relatorio Promax 02.03.04 a partir do CSV publicado por filial."
    )
    parser.add_argument("source_path", type=Path, help="Arquivo CSV da rotina 02.03.04.")
    parser.add_argument("--filial", required=True, help="Codigo da filial/revenda. Exemplo: 3.")
    parser.add_argument("--filial-nome", help="Nome curto da filial. Exemplo: Patos.")
    parser.add_argument(
        "--reference-date",
        help="Data de referencia no formato YYYY-MM-DD ou DD/MM/YYYY. Se omitida, usa a data de modificacao do CSV.",
    )
    parser.add_argument("--output-path", type=Path, help="Destino do PDF. Se omitido, usa output/pdf/.")
    return parser.parse_args()


def _parse_date(value: str) -> date:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("Data invalida. Use YYYY-MM-DD ou DD/MM/YYYY.")


def _file_date(path: Path) -> date:
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def _default_output_path(source_path: Path, *, filial: str, filial_nome: str, reference_date: date) -> Path:
    clean_name = "".join(char.lower() if char.isalnum() else "-" for char in str(filial_nome or "filial"))
    clean_name = "-".join(part for part in clean_name.split("-") if part) or "filial"
    return Path("output") / "pdf" / f"020304-filial-{filial}-{clean_name}-{reference_date.isoformat()}.pdf"


if __name__ == "__main__":
    main()
