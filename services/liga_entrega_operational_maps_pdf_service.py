"""PDF do recorte visível do acompanhamento de fechamento da 03.11.20."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_liga_entrega_operational_maps_pdf(*, competencia: str, maps: list[Mapping[str, Any]]) -> tuple[bytes, str]:
    if not maps:
        raise ValueError("Selecione pelo menos um mapa para gerar o PDF.")
    if len(maps) > 1500:
        raise ValueError("O PDF aceita até 1.500 mapas por vez. Restrinja os filtros.")

    styles = getSampleStyleSheet()
    title = ParagraphStyle("ClosingTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.HexColor("#f8fafc"))
    subtitle = ParagraphStyle("ClosingSubtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#b7c5d9"))
    cell = ParagraphStyle("ClosingCell", parent=styles["Normal"], fontName="Helvetica", fontSize=6.5, leading=7.5, textColor=colors.HexColor("#edf4ff"))
    header = ParagraphStyle("ClosingHeader", parent=cell, fontName="Helvetica-Bold", fontSize=6.1, leading=7, textColor=colors.HexColor("#dbeafe"))

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A3), leftMargin=8 * mm, rightMargin=8 * mm, topMargin=9 * mm, bottomMargin=9 * mm, title="Fechamento de mapas")
    story: list[Any] = [
        Paragraph("Fechamento de mapas · 03.11.20", title),
        Paragraph(f"Competência {escape(str(competencia or '-'))} · {len(maps)} mapa(s) no recorte selecionado", subtitle),
        Spacer(1, 4 * mm),
    ]
    headers = ["FILIAL", "MAPA", "PLACA", "SAÍDA", "ENTRADA", "FÍSICO", "FINANCEIRO", "TEMPO ROTA", "TI TOTAL", "STATUS", "ALERTAS"]
    widths = [19 * mm, 18 * mm, 22 * mm, 27 * mm, 27 * mm, 27 * mm, 28 * mm, 24 * mm, 21 * mm, 31 * mm, 54 * mm]
    data: list[list[Any]] = [[Paragraph(item, header) for item in headers]]
    for item in maps:
        alerts = item.get("alertas") if isinstance(item.get("alertas"), list) else []
        data.append([
            _cell(item.get("filial"), cell), _cell(item.get("mapa"), cell), _cell(item.get("placa"), cell),
            _cell(item.get("saida"), cell), _cell(item.get("entrada"), cell), _cell(item.get("fechamento_fisico"), cell),
            _cell(item.get("fechamento_financeiro"), cell), _cell(item.get("tempo_rota"), cell), _cell(item.get("tempo_interno_total"), cell),
            _cell(item.get("status_fechamento") or item.get("status_operacional"), cell), _cell(" · ".join(str(value) for value in alerts) or "-", cell),
        ])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12213a")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#111b2c"), colors.HexColor("#0d1626")]),
        ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#334966")),
        ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#293b55")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    document.build(story, onFirstPage=_paint, onLaterPages=_paint)
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in str(competencia or "dados")).strip("-") or "dados"
    return buffer.getvalue(), f"fechamento-mapas-{safe}.pdf"


def _cell(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value if value is not None and value != "" else "-")), style)


def _paint(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#07101d"))
    canvas.rect(0, 0, document.pagesize[0], document.pagesize[1], fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#91a0ba"))
    canvas.setFont("Helvetica", 6.5)
    canvas.drawRightString(document.pagesize[0] - document.rightMargin, 4 * mm, f"Página {document.page}")
    canvas.restoreState()
