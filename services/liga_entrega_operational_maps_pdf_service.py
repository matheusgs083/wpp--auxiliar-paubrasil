"""PDF executivo do recorte visível de fechamento de mapas da 03.11.20."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


_NAVY = colors.HexColor("#07101d")
_SURFACE = colors.HexColor("#0f1929")
_SURFACE_ALT = colors.HexColor("#111e31")
_LINE = colors.HexColor("#2d405d")
_MUTED = colors.HexColor("#aabbd3")
_TEXT = colors.HexColor("#edf4ff")
_BLUE = colors.HexColor("#60a5fa")
_GREEN = colors.HexColor("#34d399")
_AMBER = colors.HexColor("#fcd34d")
_ROSE = colors.HexColor("#fda4af")


def build_liga_entrega_operational_maps_pdf(*, competencia: str, maps: list[Mapping[str, Any]]) -> tuple[bytes, str]:
    """Monta um PDF compacto para impressão A4 em paisagem.

    A visualização do painel preserva todos os marcos; no PDF, os marcos de
    menor prioridade ficam fora para a leitura caber em uma folha padrão sem
    reduzir a fonte a um tamanho ilegível.
    """
    if not maps:
        raise ValueError("Selecione pelo menos um mapa para gerar o PDF.")
    if len(maps) > 1500:
        raise ValueError("O PDF aceita até 1.500 mapas por vez. Restrinja os filtros.")

    styles = getSampleStyleSheet()
    title = ParagraphStyle("ClosingTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=colors.white)
    subtitle = ParagraphStyle("ClosingSubtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=7.7, leading=10, textColor=_MUTED)
    kpi_value = ParagraphStyle("ClosingKpiValue", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=13, leading=14, textColor=colors.white)
    kpi_label = ParagraphStyle("ClosingKpiLabel", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=6.4, leading=8, textColor=_MUTED)
    cell = ParagraphStyle("ClosingCell", parent=styles["Normal"], fontName="Helvetica", fontSize=6.35, leading=7.6, textColor=_TEXT)
    cell_bold = ParagraphStyle("ClosingCellBold", parent=cell, fontName="Helvetica-Bold")
    header = ParagraphStyle("ClosingHeader", parent=cell, fontName="Helvetica-Bold", fontSize=5.9, leading=7, textColor=colors.HexColor("#dbeafe"))
    status = ParagraphStyle("ClosingStatus", parent=cell, fontName="Helvetica-Bold", fontSize=6.1, leading=7.2, textColor=colors.white)

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=9 * mm,
        rightMargin=9 * mm,
        topMargin=12 * mm,
        bottomMargin=11 * mm,
        title="Fechamento de mapas",
        author="Pau Brasil Transportes",
    )
    summary = _summary(maps)
    section = ParagraphStyle("ClosingSection", parent=subtitle, fontName="Helvetica-Bold", fontSize=8, textColor=_BLUE)
    story: list[Any] = [
        Paragraph("Fechamento de mapas · 03.11.20", title),
        Paragraph(
            f"Competência {escape(str(competencia or '-'))} · recorte gerado com {len(maps)} mapa(s) · tempos internos medidos da entrada ao fechamento financeiro.",
            subtitle,
        ),
        Spacer(1, 3.2 * mm),
        _summary_cards(summary, kpi_value, kpi_label),
        Spacer(1, 3.2 * mm),
        Paragraph("Detalhamento por mapa", section),
        Spacer(1, 1.6 * mm),
    ]

    headers = ["DATA", "FILIAL", "MAPA", "PLACA", "SAÍDA", "ENTRADA", "FÍSICO", "FINANCEIRO", "ROTA", "TI TOTAL", "STATUS E ALERTAS"]
    widths = [15 * mm, 14 * mm, 14 * mm, 18 * mm, 21 * mm, 21 * mm, 20 * mm, 21 * mm, 15 * mm, 16 * mm, 57 * mm]
    data: list[list[Any]] = [[Paragraph(item, header) for item in headers]]
    alert_rows: list[int] = []
    for index, item in enumerate(maps, start=1):
        alerts = item.get("alertas") if isinstance(item.get("alertas"), list) else []
        if alerts:
            alert_rows.append(index)
        status_value = str(item.get("status_fechamento") or item.get("status_operacional") or "-")
        alert_value = " · ".join(str(value) for value in alerts)
        status_markup = f"<b>{escape(status_value)}</b>"
        if alert_value:
            status_markup += f'<br/><font color="#fda4af">{escape(alert_value)}</font>'
        data.append([
            _cell(_display_date(item.get("data")), cell),
            _cell(item.get("filial"), cell_bold),
            _cell(item.get("mapa"), cell_bold),
            _cell(item.get("placa"), cell),
            _cell(item.get("saida"), cell),
            _cell(item.get("entrada"), cell),
            _cell(item.get("fechamento_fisico"), cell),
            _cell(item.get("fechamento_financeiro"), cell),
            _cell(item.get("tempo_rota"), cell_bold),
            _cell(item.get("tempo_interno_total"), cell_bold),
            Paragraph(status_markup, status),
        ])

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#183250")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_SURFACE, _SURFACE_ALT]),
        ("BOX", (0, 0), (-1, -1), 0.45, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#293b55")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
    ]
    for row in alert_rows:
        table_style.append(("BACKGROUND", (0, row), (-1, row), colors.HexColor("#231d2b")))
        table_style.append(("LINEBEFORE", (0, row), (0, row), 1.8, colors.HexColor("#fb7185")))
    table.setStyle(TableStyle(table_style))
    story.append(table)
    document.build(story, onFirstPage=_paint, onLaterPages=_paint)
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in str(competencia or "dados")).strip("-") or "dados"
    return buffer.getvalue(), f"fechamento-mapas-{safe}.pdf"


def _summary(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "mapas": len(rows),
        "retornaram": sum(str(item.get("status_operacional") or "") == "Retornou" for item in rows),
        "fechados": sum(bool(item.get("fechamento_financeiro") not in {None, "", "-"}) for item in rows),
        "pendentes": sum(not bool(item.get("fechamento_financeiro") not in {None, "", "-"}) for item in rows),
        "alertas": sum(bool(item.get("alertas")) for item in rows),
        "pulou_mpd": sum(bool(item.get("pulou_mpd")) for item in rows),
    }


def _summary_cards(summary: Mapping[str, int], value_style: ParagraphStyle, label_style: ParagraphStyle) -> Table:
    items = [
        ("MAPAS", summary["mapas"], _BLUE),
        ("RETORNARAM", summary["retornaram"], _GREEN),
        ("FECHADOS", summary["fechados"], _GREEN),
        ("PENDENTES", summary["pendentes"], _AMBER),
        ("COM ALERTA", summary["alertas"], _ROSE),
        ("PULOU MPD", summary["pulou_mpd"], _AMBER),
    ]
    cells = []
    for label, value, color in items:
        value_line = Paragraph(f'<font color="{color.hexval()}">{value}</font>', value_style)
        cells.append(Table([[value_line], [Paragraph(label, label_style)]], colWidths=[41 * mm], rowHeights=[6.4 * mm, 4.6 * mm]))
    table = Table([cells], colWidths=[43 * mm] * len(cells), hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0d1829")),
        ("BOX", (0, 0), (-1, -1), 0.45, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, _LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.2),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
    ]))
    return table


def _cell(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value if value is not None and value != "" else "-")), style)


def _display_date(value: Any) -> str:
    value = str(value or "").strip()
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return f"{value[8:10]}/{value[5:7]}"
    return value or "-"


def _paint(canvas: Any, document: Any) -> None:
    canvas.saveState()
    width, height = document.pagesize
    canvas.setFillColor(_NAVY)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#1e3a5f"))
    canvas.setLineWidth(0.6)
    canvas.line(document.leftMargin, height - 7 * mm, width - document.rightMargin, height - 7 * mm)
    canvas.setFillColor(_MUTED)
    canvas.setFont("Helvetica", 6.2)
    canvas.drawString(document.leftMargin, 5.2 * mm, "Pau Brasil Transportes · acompanhamento operacional")
    canvas.drawRightString(width - document.rightMargin, 5.2 * mm, f"Página {document.page}")
    canvas.restoreState()
