from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.filial_labels import FILIAL_LABELS


ROUTINE_CODE = "02.03.04"
ROUTINE_LABEL = "PW03060R"
EXPECTED_HEADERS = {
    "Grade",
    "Cod",
    "Descricao",
    "UN",
    "Inicial",
    "Ent.",
    "Ent.MCDD",
    "Reserva",
    "Trans.",
    "Saidas",
    "Sai.MCDD",
    "Disp.",
    "Res.Magali",
    "Inic.Agend.",
    "Ent.Agend.",
    "Sai.Agend.",
    "Disp.Agend.",
}
NUMERIC_FIELDS = (
    "Inicial",
    "Ent.",
    "Ent.MCDD",
    "Reserva",
    "Trans.",
    "Saidas",
    "Sai.MCDD",
    "Disp.",
    "Res.Magali",
    "Inic.Agend.",
    "Ent.Agend.",
    "Sai.Agend.",
    "Disp.Agend.",
)
PDF_THEME = {
    "page_bg": "#F5F6F8",
    "panel_bg": "#FFFFFF",
    "panel_bg_alt": "#F8F9FA",
    "header_bg": "#E7E9ED",
    "border": "#D3D7DD",
    "border_strong": "#C6CBD3",
    "text_primary": "#1F2933",
    "text_muted": "#4B5563",
    "accent": "#40566D",
    "accent_soft": "#EEF2F6",
    "warning_bg": "#FFF7E8",
    "warning_text": "#6B5A3C",
    "danger": "#B42318",
    "danger_bg": "#FFF1F0",
    "danger_border": "#F0A6A1",
}


@dataclass(frozen=True)
class Relatorio020304Row:
    grade: str
    codigo: str
    descricao: str
    unidade: str
    inicial: int
    entrada: int
    entrada_mcdd: int
    reserva: int
    transito: int
    saidas: int
    saida_mcdd: int
    disponivel: int
    reserva_magali: int
    inicial_agendado: int
    entrada_agendado: int
    saida_agendado: int
    disponivel_agendado: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Relatorio020304Summary:
    filial: str
    filial_nome: str
    reference_date: date | None
    source_name: str
    row_count: int
    grades: tuple[str, ...]
    unidades: tuple[str, ...]
    totals: dict[str, int]
    produtos_com_disponivel: int
    produtos_sem_disponivel: int
    produtos_com_reserva: int
    produtos_com_saida: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reference_date"] = self.reference_date.isoformat() if self.reference_date else None
        return payload


def read_020304_csv(source_path: Path) -> list[Relatorio020304Row]:
    path = source_path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo nao encontrado: {path}")
    text = _read_text_with_fallback(path)
    delimiter = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = [str(header or "").strip() for header in reader.fieldnames or []]
    missing = sorted(EXPECTED_HEADERS - set(headers))
    if missing:
        raise ValueError(f"Arquivo 02.03.04 invalido. Colunas ausentes: {', '.join(missing)}")

    rows: list[Relatorio020304Row] = []
    for raw_row in reader:
        if not any(str(value or "").strip() for value in raw_row.values()):
            continue
        rows.append(_row_from_mapping(raw_row))
    if not rows:
        raise ValueError("Arquivo 02.03.04 sem produtos validos.")
    return rows


def summarize_020304_rows(
    rows: list[Relatorio020304Row],
    *,
    filial: str,
    filial_nome: str | None = None,
    reference_date: date | None = None,
    source_name: str = "",
) -> Relatorio020304Summary:
    normalized_filial = normalize_numeric_code(filial)
    label = str(filial_nome or "").strip() or FILIAL_LABELS.get(normalized_filial, "")
    totals = {
        "inicial": sum(row.inicial for row in rows),
        "entrada": sum(row.entrada for row in rows),
        "entrada_mcdd": sum(row.entrada_mcdd for row in rows),
        "reserva": sum(row.reserva for row in rows),
        "transito": sum(row.transito for row in rows),
        "saidas": sum(row.saidas for row in rows),
        "saida_mcdd": sum(row.saida_mcdd for row in rows),
        "disponivel": sum(row.disponivel for row in rows),
        "reserva_magali": sum(row.reserva_magali for row in rows),
        "inicial_agendado": sum(row.inicial_agendado for row in rows),
        "entrada_agendado": sum(row.entrada_agendado for row in rows),
        "saida_agendado": sum(row.saida_agendado for row in rows),
        "disponivel_agendado": sum(row.disponivel_agendado for row in rows),
    }
    return Relatorio020304Summary(
        filial=normalized_filial,
        filial_nome=label or normalized_filial or "-",
        reference_date=reference_date,
        source_name=source_name,
        row_count=len(rows),
        grades=tuple(sorted({row.grade for row in rows if row.grade}, key=_sort_key)),
        unidades=tuple(sorted({row.unidade for row in rows if row.unidade}, key=_sort_key)),
        totals=totals,
        produtos_com_disponivel=sum(1 for row in rows if row.disponivel > 0),
        produtos_sem_disponivel=sum(1 for row in rows if row.disponivel <= 0),
        produtos_com_reserva=sum(1 for row in rows if row.reserva > 0),
        produtos_com_saida=sum(1 for row in rows if row.saidas > 0),
    )


def build_020304_pdf_from_csv(
    source_path: Path,
    *,
    filial: str,
    filial_nome: str | None = None,
    reference_date: date | None = None,
) -> bytes:
    rows = read_020304_csv(source_path)
    summary = summarize_020304_rows(
        rows,
        filial=filial,
        filial_nome=filial_nome,
        reference_date=reference_date,
        source_name=source_path.name,
    )
    return build_020304_pdf(rows, summary=summary)


def build_020304_pdf(rows: list[Relatorio020304Row], *, summary: Relatorio020304Summary) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    buffer = io.BytesIO()
    page_size = A4
    styles = _build_pdf_styles("Rel020304")
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=33 * mm,
        bottomMargin=8 * mm,
        title=f"Relatorio {ROUTINE_CODE} - Filial {summary.filial}",
    )
    generated_at = datetime.now()
    story: list[Any] = [
        Paragraph("RESUMO DO ESTOQUE", styles["section"]),
        _summary_table(summary, styles),
        Spacer(1, 3 * mm),
        Paragraph("PRODUTOS", styles["section"]),
        _product_table(rows, styles),
    ]
    doc.build(
        story,
        onFirstPage=lambda canvas, doc_obj: _draw_page_header(
            canvas,
            doc_obj,
            page_size=page_size,
            generated_at=generated_at,
            summary=summary,
        ),
        onLaterPages=lambda canvas, doc_obj: _draw_page_header(
            canvas,
            doc_obj,
            page_size=page_size,
            generated_at=generated_at,
            summary=summary,
        ),
    )
    return buffer.getvalue()


def write_020304_pdf(
    source_path: Path,
    output_path: Path,
    *,
    filial: str,
    filial_nome: str | None = None,
    reference_date: date | None = None,
) -> Path:
    pdf_bytes = build_020304_pdf_from_csv(
        source_path,
        filial=filial,
        filial_nome=filial_nome,
        reference_date=reference_date,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)
    return output_path


def _row_from_mapping(row: dict[str, Any]) -> Relatorio020304Row:
    return Relatorio020304Row(
        grade=_clean_text(row.get("Grade")),
        codigo=_clean_code(row.get("Cod")),
        descricao=_clean_text(row.get("Descricao")),
        unidade=_clean_text(row.get("UN")),
        inicial=_parse_int(row.get("Inicial")),
        entrada=_parse_int(row.get("Ent.")),
        entrada_mcdd=_parse_int(row.get("Ent.MCDD")),
        reserva=_parse_int(row.get("Reserva")),
        transito=_parse_int(row.get("Trans.")),
        saidas=_parse_int(row.get("Saidas")),
        saida_mcdd=_parse_int(row.get("Sai.MCDD")),
        disponivel=_parse_int(row.get("Disp.")),
        reserva_magali=_parse_int(row.get("Res.Magali")),
        inicial_agendado=_parse_int(row.get("Inic.Agend.")),
        entrada_agendado=_parse_int(row.get("Ent.Agend.")),
        saida_agendado=_parse_int(row.get("Sai.Agend.")),
        disponivel_agendado=_parse_int(row.get("Disp.Agend.")),
    )


def _summary_table(summary: Relatorio020304Summary, styles: dict[str, Any]) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    totals = summary.totals
    rows = [
        [
            Paragraph("Filial", styles["table_header"]),
            Paragraph("Data Ref.", styles["table_header"]),
            Paragraph("Produtos", styles["table_header"]),
            Paragraph("Grades", styles["table_header"]),
            Paragraph("Unidades", styles["table_header"]),
            Paragraph("Arquivo", styles["table_header"]),
        ],
        [
            Paragraph(_escape(f"{summary.filial} - {summary.filial_nome}"), styles["table_cell_bold"]),
            Paragraph(_escape(_format_date(summary.reference_date)), styles["table_cell_bold"]),
            Paragraph(_escape(_format_int(summary.row_count)), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_compact_list(summary.grades)), styles["table_cell_bold"]),
            Paragraph(_escape(_format_compact_list(summary.unidades)), styles["table_cell_bold"]),
            Paragraph(_escape(summary.source_name or "-"), styles["table_cell_bold"]),
        ],
        [
            Paragraph("Estoque Inicial", styles["table_header"]),
            Paragraph("Entradas", styles["table_header"]),
            Paragraph("Reservas", styles["table_header"]),
            Paragraph("Transferencia", styles["table_header"]),
            Paragraph("Saidas", styles["table_header"]),
            Paragraph("Disponivel", styles["table_header"]),
        ],
        [
            Paragraph(_escape(_format_int(totals["inicial"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["entrada"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["reserva"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["transito"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["saidas"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["disponivel"])), styles["table_cell_bold_right"]),
        ],
        [
            Paragraph("Ent. MCDD", styles["table_header"]),
            Paragraph("Sai. MCDD", styles["table_header"]),
            Paragraph("Res. Magali", styles["table_header"]),
            Paragraph("Inicial Agend.", styles["table_header"]),
            Paragraph("Sai. Agend.", styles["table_header"]),
            Paragraph("Disp. Agend.", styles["table_header"]),
        ],
        [
            Paragraph(_escape(_format_int(totals["entrada_mcdd"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["saida_mcdd"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["reserva_magali"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["inicial_agendado"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["saida_agendado"])), styles["table_cell_bold_right"]),
            Paragraph(_escape(_format_int(totals["disponivel_agendado"])), styles["table_cell_bold_right"]),
        ],
    ]
    table = Table(rows, colWidths=[32 * mm, 27 * mm, 24 * mm, 24 * mm, 24 * mm, 62 * mm])
    table.setStyle(_table_style(header_rows=(0, 2, 4), grid=True))
    return table


def _product_table(rows: list[Relatorio020304Row], styles: dict[str, Any]) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Table

    headers = [
        "Codigo",
        "Produto",
        "UN",
        "Inicial",
        "Reserva",
        "Saidas",
        "Disponivel",
    ]
    table_rows: list[list[Any]] = [headers]
    for row in sorted(rows, key=lambda item: (_sort_key(item.grade), _sort_key(item.codigo))):
        table_rows.append(
            [
                row.codigo,
                _truncate(row.descricao, 34),
                row.unidade,
                _format_int(row.inicial),
                _format_int(row.reserva),
                _format_int(row.saidas),
                _format_int(row.disponivel),
            ]
        )
    table = Table(
        table_rows,
        repeatRows=1,
        splitByRow=1,
        colWidths=[
            21 * mm,
            65 * mm,
            12 * mm,
            25 * mm,
            22 * mm,
            22 * mm,
            26 * mm,
        ],
    )
    extra_commands: list[tuple[Any, ...]] = []
    for index, row in enumerate(sorted(rows, key=lambda item: (_sort_key(item.grade), _sort_key(item.codigo))), start=1):
        if row.disponivel <= 0:
            extra_commands.extend(
                [
                    ("BACKGROUND", (6, index), (6, index), _theme_color("danger_bg")),
                    ("TEXTCOLOR", (6, index), (6, index), _theme_color("danger")),
                    ("FONTNAME", (6, index), (6, index), "Courier-Bold"),
                ]
            )
        else:
            extra_commands.extend(
                [
                    ("BACKGROUND", (6, index), (6, index), _theme_color("accent_soft")),
                    ("FONTNAME", (6, index), (6, index), "Courier-Bold"),
                ]
            )
        if row.reserva > 0:
            extra_commands.extend(
                [
                    ("TEXTCOLOR", (4, index), (4, index), _theme_color("warning_text")),
                    ("FONTNAME", (4, index), (4, index), "Courier-Bold"),
                ]
            )
    table.setStyle(_table_style(header_rows=(0,), grid=True, extra_commands=tuple(extra_commands), font_size=8.4))
    return table


def _build_pdf_styles(prefix: str) -> dict[str, Any]:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    return {
        "section": ParagraphStyle(
            f"{prefix}Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.4,
            leading=12.4,
            alignment=TA_LEFT,
            spaceBefore=4,
            spaceAfter=2,
            textColor=_theme_color("accent"),
        ),
        "table_header": ParagraphStyle(
            f"{prefix}TableHeader",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=8.1,
            leading=8.9,
            alignment=TA_LEFT,
            textColor=_theme_color("text_primary"),
        ),
        "table_cell": ParagraphStyle(
            f"{prefix}TableCell",
            parent=styles["BodyText"],
            fontName="Courier",
            fontSize=7.8,
            leading=8.8,
            alignment=TA_LEFT,
            textColor=_theme_color("text_primary"),
        ),
        "table_cell_bold": ParagraphStyle(
            f"{prefix}TableCellBold",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=7.9,
            leading=8.9,
            alignment=TA_LEFT,
            textColor=_theme_color("text_primary"),
        ),
        "table_cell_bold_right": ParagraphStyle(
            f"{prefix}TableCellBoldRight",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=7.9,
            leading=8.9,
            alignment=2,
            textColor=_theme_color("text_primary"),
        ),
    }


def _table_style(
    *,
    header_rows: tuple[int, ...],
    grid: bool,
    extra_commands: tuple[tuple[Any, ...], ...] = (),
    font_size: float = 7.4,
) -> Any:
    from reportlab.platypus import TableStyle

    commands: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), "Courier"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("TEXTCOLOR", (0, 0), (-1, -1), _theme_color("text_primary")),
        ("BACKGROUND", (0, 0), (-1, -1), _theme_color("panel_bg")),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
    ]
    if grid:
        commands.append(("ROWBACKGROUNDS", (0, 0), (-1, -1), [_theme_color("panel_bg"), _theme_color("panel_bg_alt")]))
        commands.append(("GRID", (0, 0), (-1, -1), 0.25, _theme_color("border")))
    for header_row in header_rows:
        commands.extend(
            [
                ("BACKGROUND", (0, header_row), (-1, header_row), _theme_color("header_bg")),
                ("FONTNAME", (0, header_row), (-1, header_row), "Courier-Bold"),
                ("LINEBELOW", (0, header_row), (-1, header_row), 0.4, _theme_color("border_strong")),
            ]
        )
    commands.extend(extra_commands)
    return TableStyle(commands)


def _draw_page_header(
    canvas: Any,
    doc_obj: Any,
    *,
    page_size: tuple[float, float],
    generated_at: datetime,
    summary: Relatorio020304Summary,
) -> None:
    from reportlab.lib.units import mm

    width, height = page_size
    totals = summary.totals
    stats_line = (
        f"Produtos: {_format_int(summary.row_count)}      "
        f"Inicial: {_format_int(totals['inicial'])}      "
        f"Reservas: {_format_int(totals['reserva'])}      "
        f"Saidas: {_format_int(totals['saidas'])}      "
        f"Disponivel: {_format_int(totals['disponivel'])}"
    )
    canvas.saveState()
    canvas.setFillColor(_theme_color("page_bg"))
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(_theme_color("panel_bg"))
    canvas.rect(7 * mm, height - 30 * mm, width - 14 * mm, 23 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(_theme_color("border_strong"))
    canvas.rect(7 * mm, height - 30 * mm, width - 14 * mm, 23 * mm, fill=0, stroke=1)
    canvas.setFillColor(_theme_color("text_primary"))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(9 * mm, height - 9 * mm, f"{ROUTINE_LABEL} - Bot API")
    canvas.drawCentredString(width / 2, height - 9 * mm, "RELATORIO 02.03.04 - ESTOQUE POR FILIAL")
    canvas.drawRightString(width - 9 * mm, height - 9 * mm, generated_at.strftime("%d/%m/%Y"))
    canvas.setFillColor(_theme_color("text_muted"))
    canvas.setFont("Courier", 7.2)
    canvas.drawString(9 * mm, height - 13 * mm, "Distribuidora de Bebidas Pau Brasil LTDA")
    canvas.drawRightString(width - 9 * mm, height - 13 * mm, f"Pag. {doc_obj.page}")
    canvas.drawString(9 * mm, height - 17 * mm, "Versao: Bot API      Rotina: 02.03.04      Usuario: BOT")
    canvas.drawRightString(width - 9 * mm, height - 17 * mm, generated_at.strftime("%H:%M"))
    canvas.drawString(
        9 * mm,
        height - 21 * mm,
        _truncate(f"Filial: {summary.filial} - {summary.filial_nome} | Grade(s): {_format_compact_list(summary.grades)}", 125),
    )
    canvas.drawString(9 * mm, height - 25 * mm, _truncate(stats_line, 125))
    canvas.setStrokeColor(_theme_color("accent"))
    canvas.line(9 * mm, height - 28 * mm, width - 9 * mm, height - 28 * mm)
    canvas.restoreState()


def _read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1", errors="replace")


def _detect_delimiter(text: str) -> str:
    sample = text[:65536]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";" if sample.count(";") >= sample.count(",") else ","


def _parse_int(value: Any) -> int:
    text = str(value or "").strip().replace(".", "").replace(",", ".")
    if not text:
        return 0
    try:
        return int(Decimal(text).to_integral_value())
    except (InvalidOperation, ValueError):
        digits = "".join(char for char in text if char.isdigit() or char == "-")
        return int(digits or 0)


def _format_int(value: Any) -> str:
    try:
        amount = int(value or 0)
    except (TypeError, ValueError):
        amount = 0
    return f"{amount:,}".replace(",", ".")


def _format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if isinstance(value, date) else "-"


def _format_compact_list(values: tuple[str, ...] | list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value or "").strip()]
    if not cleaned:
        return "-"
    if len(cleaned) <= 6:
        return ", ".join(cleaned)
    return ", ".join(cleaned[:6]) + f" +{len(cleaned) - 6}"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_code(value: Any) -> str:
    text = str(value or "").strip()
    digits = "".join(char for char in text if char.isdigit())
    return normalize_numeric_code(digits or text)


def _truncate(value: str, max_length: int) -> str:
    text = _clean_text(value)
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _escape(value: Any) -> str:
    return escape(str(value or ""))


def _sort_key(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    digits = "".join(char for char in text if char.isdigit())
    if digits:
        return int(digits), text
    return 999999999, text


def _theme_color(name: str) -> Any:
    from reportlab.lib import colors

    return colors.HexColor(PDF_THEME[name])
