"""PDF export for the already calculated Liga Entrega dashboard.

The PDF intentionally consumes the dashboard snapshot produced by
``LigaEntregaDashboardService``.  That keeps the export aligned with the
screen, including active expurgos, team status and the same ranking totals.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_liga_entrega_dashboard_pdf(
    dashboard: Mapping[str, Any],
    *,
    view: str,
) -> tuple[bytes, str]:
    """Return a downloadable PDF and its safe filename for one ranking view."""

    normalized_view = str(view or "completo").strip().lower()
    if normalized_view not in {"motoristas", "ajudantes", "completo"}:
        raise ValueError("A visão do PDF deve ser completa, motoristas ou ajudantes.")

    rankings = dashboard.get("rankings")
    rankings = rankings if isinstance(rankings, Mapping) else {}
    competencia = str(dashboard.get("competencia") or "sem-competencia").strip()
    title = "Liga Entrega - Dashboard"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LigaPdfTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=17, leading=20, textColor=colors.HexColor("#16243b"),
        spaceAfter=3 * mm,
    )
    subtitle_style = ParagraphStyle(
        "LigaPdfSubtitle", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9, leading=12, textColor=colors.HexColor("#52647e"),
    )
    cell_style = ParagraphStyle(
        "LigaPdfCell", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.4, leading=9, textColor=colors.HexColor("#16243b"),
    )
    cell_right_style = ParagraphStyle(
        "LigaPdfCellRight", parent=cell_style, alignment=TA_RIGHT,
    )
    header_style = ParagraphStyle(
        "LigaPdfHeader", parent=cell_style, fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    summary = dashboard.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    operation = dashboard.get("operacao")
    operation = operation if isinstance(operation, Mapping) else {}
    expurgos = dashboard.get("expurgos")
    expurgos = expurgos if isinstance(expurgos, Mapping) else {}
    counts = expurgos.get("counts")
    counts = counts if isinstance(counts, Mapping) else {}
    total_expurgos = sum(_number(counts.get(key)) for key in ("devolucao", "km", "dispersao", "tml"))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=title,
        author="Bot API",
    )
    story: list[Any] = [
        Paragraph(escape(title), title_style),
        Paragraph(
            escape(f"Competência: {competencia}  |  Dashboard da Liga Entrega  |  Expurgos aplicados: {int(total_expurgos)}"),
            subtitle_style,
        ),
        Spacer(1, 5 * mm),
    ]

    summary_data = [
        [_p("Rotas processadas", header_style), _p("Entregas", header_style), _p("Devoluções", header_style), _p("Saída ≤07:30", header_style), _p("Desvio KM", header_style)],
        [
            _p(_fmt(summary.get("rotas")), cell_style),
            _p(_fmt(summary.get("entregas", operation.get("entregas"))), cell_style),
            _p(_fmt(summary.get("devolucoes", operation.get("devolucoes"))), cell_style),
            _p(_fmt_pct(operation.get("saida_pct")), cell_style),
            _p(_fmt_pct(operation.get("km_desv")), cell_style),
        ],
    ]
    summary_table = Table(summary_data, colWidths=[48 * mm] * 5, repeatRows=1)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4f86")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#eef4fb")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#a8bad2")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c5d2e3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([summary_table, Spacer(1, 5 * mm)])

    headers = ["#", "Colaborador", "Filial", "Rotas", "Devolução", "Saída ≤07:30", "Desvio KM", "Checklist", "Total"]
    widths = [11 * mm, 76 * mm, 25 * mm, 16 * mm, 27 * mm, 31 * mm, 25 * mm, 32 * mm, 20 * mm]
    views = [normalized_view] if normalized_view != "completo" else ["motoristas", "ajudantes"]
    for role_view in views:
        role_rows = rankings.get(role_view)
        role_rows = role_rows if isinstance(role_rows, list) else []
        role_title = "Ranking de motoristas" if role_view == "motoristas" else "Ranking de ajudantes"
        story.extend([Paragraph(role_title, ParagraphStyle(
            f"LigaPdf{role_view}Heading", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, textColor=colors.HexColor("#1f4f86"), spaceBefore=2 * mm,
            spaceAfter=2 * mm,
        ))])
        table_data: list[list[Any]] = [[_p(header, header_style) for header in headers]]
        for index, row in enumerate(role_rows, 1):
            if not isinstance(row, Mapping):
                continue
            position = row.get("pos") or index
            check = _fmt_pct(row.get("check_pct"))
            if row.get("check_f") is not None and row.get("check_e") is not None:
                check = f"{check} ({_fmt(row.get('check_f'))}/{_fmt(row.get('check_e'))})"
            table_data.append([
                _p(f"{position}º", cell_right_style),
                _p(str(row.get("nome") or row.get("cod") or "-"), cell_style),
                _p(str(row.get("filial") or "-"), cell_style),
                _p(_fmt(row.get("rotas")), cell_right_style),
                _p(_fmt_pct(row.get("pdev")), cell_right_style),
                _p(_fmt_pct(row.get("psaida")), cell_right_style),
                _p(_fmt_pct(row.get("km_desv")), cell_right_style),
                _p(check, cell_right_style),
                _p(_fmt(row.get("total")), cell_right_style),
            ])
        if len(table_data) == 1:
            table_data.append([_p("Nenhum colaborador calculado.", cell_style)] + [""] * (len(headers) - 1))
        ranking_table = Table(table_data, colWidths=widths, repeatRows=1)
        ranking_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16243b")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fc")]),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#a8bad2")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d7e0eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(ranking_table)
    document.build(story)
    safe_competencia = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in competencia).strip("-") or "dados"
    return buffer.getvalue(), f"liga-entrega-{normalized_view}-{safe_competencia}.pdf"


def _p(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value if value is not None else "-")), style)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "-"
    number = _number(value)
    if float(number).is_integer():
        return str(int(number))
    return f"{number:.1f}".replace(".", ",")


def _fmt_pct(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return f"{_number(value):.2f}%".replace(".", ",")
