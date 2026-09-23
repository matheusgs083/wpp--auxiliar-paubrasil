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
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


DARK = colors.HexColor("#0c121e")
SURFACE = colors.HexColor("#111827")
SURFACE_ALT = colors.HexColor("#0f1724")
LINE = colors.HexColor("#26344c")
INK = colors.HexColor("#f8fafc")
MUTED = colors.HexColor("#91a0ba")
BLUE = colors.HexColor("#2f80ed")
GREEN = "#00d084"
RED = "#ff4d6d"
GOLD = "#f5aa17"


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
    title_role = {"motoristas": "Motoristas", "ajudantes": "Ajudantes"}.get(normalized_view)
    title = f"Liga Entrega - {title_role}" if title_role else "Liga Entrega - Dashboard"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LigaPdfTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=17, leading=20, textColor=INK,
        spaceAfter=3 * mm,
    )
    cell_style = ParagraphStyle(
        "LigaPdfCell", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.2, leading=8.5, textColor=INK,
    )
    cell_right_style = ParagraphStyle(
        "LigaPdfCellRight", parent=cell_style, alignment=TA_RIGHT,
    )
    header_style = ParagraphStyle(
        "LigaPdfHeader", parent=cell_style, fontName="Helvetica-Bold",
        fontSize=6.6, leading=7.5, textColor=INK,
    )
    header_center_style = ParagraphStyle(
        "LigaPdfHeaderCenter", parent=header_style, alignment=TA_CENTER,
    )

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
        Spacer(1, 4 * mm),
    ]

    story.append(Spacer(1, 2 * mm))

    headers = ["#", "COLABORADOR", "FILIAL", "ROTAS", "DEVOLUÇÃO\n≤1,4%", "SAÍDA ≤07:30\n≥90%", "DESVIO KM\n≤10%", "CHECKLIST\ndesde 13/07", "TOTAL", "PRÊMIO"]
    widths = [10 * mm, 69 * mm, 24 * mm, 14 * mm, 28 * mm, 30 * mm, 26 * mm, 33 * mm, 22 * mm, 21 * mm]
    views = [normalized_view] if normalized_view != "completo" else ["motoristas", "ajudantes"]
    for role_view in views:
        role_rows = rankings.get(role_view)
        role_rows = [row for row in role_rows if isinstance(row, Mapping) and str(row.get("status") or "ativo") == "ativo"] if isinstance(role_rows, list) else []
        role_title = "Ranking de motoristas" if role_view == "motoristas" else "Ranking de ajudantes"
        story.extend([Paragraph(role_title, ParagraphStyle(
            f"LigaPdf{role_view}Heading", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, textColor=INK, spaceBefore=2 * mm,
            spaceAfter=2 * mm,
        ))])
        table_data: list[list[Any]] = [[_header(header, header_center_style if index not in {1, 2} else header_style) for index, header in enumerate(headers)]]
        for index, row in enumerate(role_rows, 1):
            if not isinstance(row, Mapping):
                continue
            position = row.get("pos") or index
            check_detail = ""
            if row.get("check_f") is not None and row.get("check_e") is not None:
                check_detail = f"{_fmt(row.get('check_f'))}/{_fmt(row.get('check_e'))}"
            table_data.append([
                _rank_cell(position, cell_right_style),
                _p(str(row.get("nome") or row.get("cod") or "-"), ParagraphStyle(
                    f"LigaPdfName{index}", parent=cell_style, fontName="Helvetica-Bold",
                )),
                _p(str(row.get("filial") or "-"), cell_style),
                _p(_fmt(row.get("rotas")), cell_right_style),
                _metric_cell(row.get("pdev"), 1.4, False, f"{_fmt(row.get('devol'))}/{_fmt(row.get('entregas'))}"),
                _metric_cell(row.get("psaida"), 90, True),
                _metric_cell(row.get("km_desv"), 10, False),
                _metric_cell(row.get("check_pct"), 100, True, check_detail),
                _score_cell(row.get("total"), cell_right_style),
                _prize_cell(position, role_view, cell_right_style),
            ])
        if len(table_data) == 1:
            table_data.append([_p("Nenhum colaborador calculado.", cell_style)] + [""] * (len(headers) - 1))
        ranking_table = Table(table_data, colWidths=widths, repeatRows=1)
        ranking_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SURFACE_ALT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [SURFACE, SURFACE_ALT]),
            ("BOX", (0, 0), (-1, -1), 0.6, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(ranking_table)
    document.build(story, onFirstPage=_paint_page, onLaterPages=_paint_page)
    safe_competencia = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in competencia).strip("-") or "dados"
    return buffer.getvalue(), f"liga-entrega-{normalized_view}-{safe_competencia}.pdf"


def _paint_page(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, document.pagesize[0], document.pagesize[1], fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    canvas.line(document.leftMargin, 7 * mm, document.pagesize[0] - document.rightMargin, 7 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.5)
    canvas.drawRightString(document.pagesize[0] - document.rightMargin, 4 * mm, f"Página {document.page}")
    canvas.restoreState()


def _p(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value if value is not None else "-")), style)


def _header(value: Any, style: ParagraphStyle) -> Paragraph:
    text = escape(str(value if value is not None else "-")).replace("\n", "<br/>")
    return Paragraph(text, style)


def _rank_cell(position: Any, style: ParagraphStyle) -> Paragraph:
    color = GOLD if _number(position) <= 3 else "#9fb0c8"
    return Paragraph(f'<font color="{color}"><b>{escape(str(position))}º</b></font>', style)


def _metric_cell(value: Any, target: float, higher_is_better: bool, detail: str = "") -> Paragraph:
    if value is None or value == "":
        return Paragraph('<font color="#91a0ba">-</font>', ParagraphStyle("LigaPdfMetricEmpty", alignment=TA_RIGHT, fontSize=7.2, leading=8.5))
    number = _number(value)
    good = number >= target if higher_is_better else number <= target
    color = GREEN if good else RED
    detail_html = f'<br/><font color="#91a0ba" size="6">{escape(detail)}</font>' if detail else ""
    return Paragraph(
        f'<font color="{color}"><b>{escape(_fmt_pct(number))}</b></font>{detail_html}',
        ParagraphStyle("LigaPdfMetric", alignment=TA_RIGHT, fontSize=7.2, leading=8.5),
    )


def _score_cell(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f'<font color="#f8fafc"><b>{escape(_fmt(value))}</b></font>', style)


def _prize_cell(position: Any, role_view: str, style: ParagraphStyle) -> Paragraph:
    prizes: list[Any]
    if role_view == "motoristas":
        prizes = [700, 600, 500, 450, 400, 350, 300, 300, 250, 250, 250, "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE"]
    else:
        prizes = [500, 400, 350, 300, 250, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 150, 150, "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE"]
    index = int(_number(position)) - 1
    value = prizes[index] if 0 <= index < len(prizes) else None
    text = "Brinde" if value == "BRINDE" else f"R$ {_fmt(value)}" if value else "-"
    color = GREEN if value else "#91a0ba"
    return Paragraph(f'<font color="{color}"><b>{escape(text)}</b></font>', style)


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
