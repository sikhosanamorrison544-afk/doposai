"""PDF generation for POs and customer statements."""
from __future__ import annotations

import io
from decimal import Decimal
from typing import Any, List, Optional


def _money(v: Any) -> str:
    return f"{float(v):,.2f}"


def build_simple_pdf(title: str, lines: List[tuple[str, str]], footer: Optional[str] = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    data = [["Field", "Value"]] + [[k, v] for k, v in lines]
    t = Table(data, colWidths=[180, 300])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(t)
    if footer:
        story.append(Spacer(1, 12))
        story.append(Paragraph(footer, styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


def purchase_order_pdf(po: Any, supplier_name: str, items: list) -> bytes:
    lines = [
        ("PO Number", po.po_number),
        ("Supplier", supplier_name),
        ("Status", po.status),
        ("Total", _money(po.total)),
        ("Notes", po.notes or ""),
    ]
    for it in items:
        lines.append(
            (
                it.product_name,
                f"ord {it.quantity_ordered} / recv {it.quantity_received} @ {_money(it.unit_cost)}",
            )
        )
    return build_simple_pdf(f"Purchase Order {po.po_number}", lines)


def customer_statement_pdf(
    customer_name: str,
    rows: List[tuple[str, str, str]],
    balance: Decimal,
    *,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    meta = customer_name
    if phone:
        meta += f" · {phone}"
    if email:
        meta += f" · {email}"
    story = [
        Paragraph(f"Customer Statement — {meta}", styles["Title"]),
        Spacer(1, 12),
    ]
    data = [["Date", "Type", "Amount"]] + [[a, b, c] for a, b, c in rows]
    data.append(["", "Outstanding balance", _money(balance)])
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
    story.append(t)
    doc.build(story)
    return buf.getvalue()
