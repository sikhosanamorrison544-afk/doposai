"""Generate a simple product price list PDF (name + selling price only)."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Iterable, Any
from xml.sax.saxutils import escape


def _price(v: Any) -> str:
    return f"{float(v):,.2f}"


def _para(text: str, style) -> "Paragraph":
    from reportlab.platypus import Paragraph

    return Paragraph(escape(str(text or "")), style)


def build_price_list_pdf(store_name: str, products: Iterable[Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=48, bottomMargin=48)
    styles = getSampleStyleSheet()
    product_list = list(products)
    story = [
        _para(store_name, styles["Title"]),
        _para("Price List", styles["Heading2"]),
        _para(datetime.now().strftime("%d %b %Y"), styles["Normal"]),
        Spacer(1, 16),
    ]

    data = [["Product", "Price"]]
    if product_list:
        for p in product_list:
            data.append([str(p.name or ""), _price(p.selling_price)])
    else:
        data.append(["No active products", "—"])

    table = Table(data, colWidths=[360, 100], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 11),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return buf.getvalue()
