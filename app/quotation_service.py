"""
Quotation Service Module (Additive Only)
Handles quotation creation, management, and conversion to sales.
"""

import io
import logging
import xml.sax.saxutils as xml_escape
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from .models import (
    InventoryMovement,
    Product,
    Customer,
    Sale,
    SaleItem,
    Payment,
    User,
)
from .quotation_models import Quotation, QuotationItem
from .tenant_scope import first_store_settings_for_tenant, row_visible, same_tenant

logger = logging.getLogger(__name__)

# Max characters shown for product name in PDF line table (keeps columns neat).
_QUOTATION_PRODUCT_NAME_MAX = 40

# ReportLab theme
_PDF_PRIMARY = "#1e3a8a"
_PDF_HEADER_BG = "#1e3a8a"
_PDF_ROW_ALT = "#f8fafc"
_PDF_BORDER = "#e5e7eb"


def _short_product_label(name: str, max_chars: int = _QUOTATION_PRODUCT_NAME_MAX) -> str:
    """Truncate long product names so the line table stays compact."""
    text = " ".join(str(name or "").split())
    if not text:
        return "—"
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _money(amount) -> str:
    return f"{float(amount):,.2f}"


class QuotationService:
    """Service for managing quotations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def _generate_quotation_number(self, tenant_id: Optional[int] = None) -> str:
        """Generate globally unique quotation number (e.g., Q-2024-001)."""
        year = datetime.now().year
        last_quotation = (
            self.db.query(Quotation)
            .filter(Quotation.quotation_number.like(f"Q-{year}-%"))
            .order_by(Quotation.id.desc())
            .first()
        )
        
        if last_quotation:
            # Extract number and increment
            try:
                last_num = int(last_quotation.quotation_number.split("-")[-1])
                new_num = last_num + 1
            except (ValueError, IndexError):
                new_num = 1
        else:
            new_num = 1
        
        return f"Q-{year}-{new_num:03d}"
    
    def create_quotation(
        self,
        customer_id: Optional[int],
        customer_name: Optional[str],
        customer_phone: Optional[str],
        customer_email: Optional[str],
        items: List[dict],
        valid_until: Optional[datetime],
        notes: Optional[str],
        created_by: int,
        tenant_id: Optional[int] = None,
        acting_user: Optional[User] = None,
    ) -> Quotation:
        """
        Create a new quotation from product catalog.
        
        Args:
            customer_id: Optional customer ID (if customer exists)
            customer_name: Customer name (required if customer_id not provided)
            customer_phone: Customer phone number
            customer_email: Customer email
            items: List of items with product_id, quantity, unit_price (optional), discount (optional)
            valid_until: Quotation expiry date
            notes: Additional notes
            created_by: User ID who created the quotation
            tenant_id: Optional tenant ID
        
        Returns:
            Created Quotation object
        """
        if not items:
            raise ValueError("Quotation must have at least one item")
        
        # Validate products and calculate totals
        subtotal = Decimal("0")
        discount_total = Decimal("0")
        quotation_items = []
        
        for item_data in items:
            product_id = item_data.get("product_id")
            quantity = int(item_data.get("quantity", 1))
            
            if quantity <= 0:
                raise ValueError(f"Quantity must be positive for product {product_id}")
            
            # Get product
            product = self.db.get(Product, product_id)
            if not product:
                raise ValueError(f"Product {product_id} not found")
            if acting_user is not None and not row_visible(getattr(product, "tenant_id", None), acting_user):
                raise ValueError(f"Product {product_id} not found")
            
            if not product.is_active:
                raise ValueError(f"Product {product.name} is not active")
            
            # Use provided unit_price or product selling_price
            unit_price = Decimal(str(item_data.get("unit_price", product.selling_price)))
            discount = Decimal(str(item_data.get("discount", 0)))
            
            line_total = (unit_price * quantity) - discount
            
            if line_total < 0:
                raise ValueError(f"Line total cannot be negative for product {product.name}")
            
            subtotal += (unit_price * quantity)
            discount_total += discount
            
            quotation_items.append({
                "product_id": product_id,
                "product_name": product.name,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount": discount,
                "line_total": line_total,
                "notes": item_data.get("notes")
            })
        
        total = subtotal - discount_total
        
        if total <= 0:
            raise ValueError("Quotation total must be positive")
        
        # Get customer info if customer_id provided
        if customer_id:
            customer = self.db.get(Customer, customer_id)
            if customer:
                if acting_user is not None and not row_visible(getattr(customer, "tenant_id", None), acting_user):
                    raise ValueError("Customer not found")
                customer_name = customer.name
                customer_phone = customer.phone or customer_phone
                customer_email = customer.email or customer_email
        
        if not customer_name:
            raise ValueError("Customer name is required")
        
        # Create quotation
        quotation = Quotation(
            tenant_id=tenant_id,
            quotation_number=self._generate_quotation_number(tenant_id=tenant_id),
            customer_id=customer_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            subtotal=subtotal,
            discount_total=discount_total,
            tax_total=Decimal("0"),  # Tax can be added later if needed
            total=total,
            status="draft",
            valid_until=valid_until,
            notes=notes,
            created_by=created_by
        )
        
        self.db.add(quotation)
        self.db.flush()  # Get quotation.id
        
        # Create quotation items
        for item_data in quotation_items:
            item = QuotationItem(
                quotation_id=quotation.id,
                product_id=item_data["product_id"],
                product_name=item_data["product_name"],
                quantity=item_data["quantity"],
                unit_price=item_data["unit_price"],
                discount=item_data["discount"],
                line_total=item_data["line_total"],
                notes=item_data.get("notes")
            )
            self.db.add(item)
        
        self.db.commit()
        self.db.refresh(quotation)
        
        logger.info(f"Created quotation {quotation.quotation_number} for customer {customer_name}")
        return quotation
    
    def get_quotation(self, quotation_id: int) -> Optional[Quotation]:
        """Get quotation by ID."""
        return (
            self.db.query(Quotation)
            .options(joinedload(Quotation.items))
            .filter(Quotation.id == quotation_id)
            .first()
        )
    
    def list_quotations(
        self,
        customer_id: Optional[int] = None,
        customer_phone: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        tenant_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[List[Quotation], int]:
        """
        List quotations with filters.
        
        Returns:
            Tuple of (quotations list, total count)
        """
        query = self.db.query(Quotation)

        if tenant_id is not None:
            query = query.filter(Quotation.tenant_id == tenant_id)
        else:
            query = query.filter(Quotation.tenant_id.is_(None))
        
        if customer_id:
            query = query.filter(Quotation.customer_id == customer_id)
        
        if customer_phone:
            query = query.filter(Quotation.customer_phone == customer_phone)
        
        if status:
            query = query.filter(Quotation.status == status)

        if search:
            term = f"%{search.strip()}%"
            query = query.filter(
                (Quotation.quotation_number.ilike(term))
                | (Quotation.customer_name.ilike(term))
                | (Quotation.customer_phone.ilike(term))
            )
        
        total = query.count()
        quotations = query.order_by(Quotation.created_at.desc()).limit(limit).offset(offset).all()
        
        return quotations, total

    def get_quotation_by_number(
        self,
        quotation_number: str,
        tenant_id: Optional[int] = None,
        acting_user: Optional[User] = None,
    ) -> Optional[Quotation]:
        """Find a quotation by its human-readable number."""
        qnum = quotation_number.strip()
        if not qnum:
            return None
        query = self.db.query(Quotation).filter(
            func.lower(Quotation.quotation_number) == qnum.lower()
        )
        if tenant_id is not None:
            query = query.filter(Quotation.tenant_id == tenant_id)
        else:
            query = query.filter(Quotation.tenant_id.is_(None))
        quotation = (
            query.options(joinedload(Quotation.items))
            .first()
        )
        if quotation is None:
            return None
        if acting_user is not None and not row_visible(
            getattr(quotation, "tenant_id", None), acting_user
        ):
            return None
        return quotation

    def build_receipt_payload(self, quotation_id: int, acting_user: Optional[User] = None) -> dict:
        """Receipt line items and totals for printing (draft or already converted)."""
        quotation = self.get_quotation(quotation_id)
        if not quotation:
            raise ValueError(f"Quotation {quotation_id} not found")
        if acting_user is not None and not row_visible(
            getattr(quotation, "tenant_id", None), acting_user
        ):
            raise ValueError(f"Quotation {quotation_id} not found")

        if quotation.status == "converted" and quotation.converted_to_sale_id:
            sale = (
                self.db.query(Sale)
                .options(joinedload(Sale.items), joinedload(Sale.payments))
                .filter(Sale.id == quotation.converted_to_sale_id)
                .first()
            )
            if not sale:
                raise ValueError("Linked sale not found for converted quotation")
            items = []
            for si in sale.items:
                product = self.db.get(Product, si.product_id)
                items.append({
                    "product_id": si.product_id,
                    "product_name": product.name if product else f"Product #{si.product_id}",
                    "quantity": int(si.quantity),
                    "unit_price": float(si.unit_price),
                    "discount": float(si.discount or 0),
                    "line_total": float(si.line_total),
                })
            payments = [
                {"method": p.method, "amount": float(p.amount)}
                for p in sale.payments
            ]
            return {
                "quotation_id": quotation.id,
                "quotation_number": quotation.quotation_number,
                "sale_id": sale.id,
                "status": quotation.status,
                "customer_name": quotation.customer_name,
                "subtotal": float(sale.subtotal),
                "discount_total": float(sale.discount_total),
                "total": float(sale.total),
                "collection_status": sale.collection_status or "collected",
                "items": items,
                "payments": payments,
                "already_converted": True,
            }

        items = [
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity": int(item.quantity),
                "unit_price": float(item.unit_price),
                "discount": float(item.discount or 0),
                "line_total": float(item.line_total),
            }
            for item in quotation.items
        ]
        return {
            "quotation_id": quotation.id,
            "quotation_number": quotation.quotation_number,
            "sale_id": None,
            "status": quotation.status,
            "customer_name": quotation.customer_name,
            "subtotal": float(quotation.subtotal),
            "discount_total": float(quotation.discount_total),
            "total": float(quotation.total),
            "collection_status": "collected",
            "items": items,
            "payments": [],
            "already_converted": False,
        }
    
    def update_quotation(
        self,
        quotation_id: int,
        items: Optional[List[dict]] = None,
        notes: Optional[str] = None,
        valid_until: Optional[datetime] = None,
        acting_user: Optional[User] = None,
    ) -> Quotation:
        """Update quotation (only draft quotations can be updated)."""
        quotation = self.get_quotation(quotation_id)
        if not quotation:
            raise ValueError(f"Quotation {quotation_id} not found")
        if acting_user is not None and not row_visible(getattr(quotation, "tenant_id", None), acting_user):
            raise ValueError(f"Quotation {quotation_id} not found")

        if quotation.status != "draft":
            raise ValueError(f"Cannot update quotation with status '{quotation.status}'")
        
        # Update items if provided
        if items is not None:
            # Delete existing items
            self.db.query(QuotationItem).filter(
                QuotationItem.quotation_id == quotation_id
            ).delete()
            
            # Recalculate totals
            subtotal = Decimal("0")
            discount_total = Decimal("0")
            
            for item_data in items:
                product_id = item_data.get("product_id")
                quantity = int(item_data.get("quantity", 1))
                
                product = self.db.get(Product, product_id)
                if not product:
                    raise ValueError(f"Product {product_id} not found")
                if acting_user is not None and not row_visible(getattr(product, "tenant_id", None), acting_user):
                    raise ValueError(f"Product {product_id} not found")
                
                unit_price = Decimal(str(item_data.get("unit_price", product.selling_price)))
                discount = Decimal(str(item_data.get("discount", 0)))
                
                line_total = (unit_price * quantity) - discount
                subtotal += (unit_price * quantity)
                discount_total += discount
                
                item = QuotationItem(
                    quotation_id=quotation_id,
                    product_id=product_id,
                    product_name=product.name,
                    quantity=quantity,
                    unit_price=unit_price,
                    discount=discount,
                    line_total=line_total,
                    notes=item_data.get("notes")
                )
                self.db.add(item)
            
            quotation.subtotal = subtotal
            quotation.discount_total = discount_total
            quotation.total = subtotal - discount_total
        
        if notes is not None:
            quotation.notes = notes
        
        if valid_until is not None:
            quotation.valid_until = valid_until
        
        quotation.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(quotation)
        
        return quotation
    
    def delete_quotation(self, quotation_id: int, acting_user: Optional[User] = None) -> bool:
        """
        Remove quotation from history. Drafts can always be deleted.
        Converted quotations can be deleted after the receipt/sale was recorded
        (the linked sale is kept; only the quotation record is removed).
        """
        quotation = self.get_quotation(quotation_id)
        if not quotation:
            return False
        if acting_user is not None and not row_visible(getattr(quotation, "tenant_id", None), acting_user):
            return False

        if quotation.status not in ("draft", "converted"):
            raise ValueError(
                f"Cannot delete quotation with status '{quotation.status}'. "
                "Only draft or converted (receipt already printed) quotations can be removed."
            )

        self.db.delete(quotation)
        self.db.commit()
        return True
    
    def convert_to_sale(
        self,
        quotation_id: int,
        payments: List[dict],
        cashier_id: int,
        acting_user: Optional[User] = None,
    ) -> Sale:
        """
        Convert quotation to actual sale.
        
        Args:
            quotation_id: Quotation ID to convert
            payments: List of payment methods and amounts
            cashier_id: User ID processing the sale
        
        Returns:
            Created Sale object
        """
        quotation = self.get_quotation(quotation_id)
        if not quotation:
            raise ValueError(f"Quotation {quotation_id} not found")
        if acting_user is not None and not row_visible(getattr(quotation, "tenant_id", None), acting_user):
            raise ValueError(f"Quotation {quotation_id} not found")

        if quotation.status == "converted":
            raise ValueError("Quotation has already been converted to a sale")
        
        if quotation.status == "expired":
            raise ValueError("Cannot convert expired quotation")
        
        # Check if quotation is expired
        if quotation.valid_until and quotation.valid_until < datetime.utcnow():
            quotation.status = "expired"
            self.db.commit()
            raise ValueError("Quotation has expired")
        
        # Validate payments cover total
        payment_sum = sum(Decimal(str(p.get("amount", 0))) for p in payments)
        if payment_sum + Decimal("0.01") < quotation.total:
            raise ValueError("Insufficient payment amount")

        cashier = self.db.get(User, cashier_id)
        if not cashier:
            raise ValueError("Cashier not found")
        if not same_tenant(getattr(cashier, "tenant_id", None), getattr(quotation, "tenant_id", None)):
            raise ValueError("Cashier is not in the same tenant as this quotation")

        # Create sale (similar to existing sale creation logic)
        sale = Sale(
            cashier_id=cashier_id,
            customer_id=quotation.customer_id,
            tenant_id=getattr(quotation, "tenant_id", None),
            subtotal=quotation.subtotal,
            discount_total=quotation.discount_total,
            total=quotation.total,
            notes=f"Converted from quotation {quotation.quotation_number}"
        )
        self.db.add(sale)
        self.db.flush()
        
        # Create sale items and update stock
        for item in quotation.items:
            product = self.db.get(Product, item.product_id)
            if not product:
                raise ValueError(f"Product {item.product_id} not found")
            
            item_qty = int(item.quantity)
            if product.stock_qty < item_qty:
                raise ValueError(f"Insufficient stock for '{product.name}'. Available: {product.stock_qty}, Required: {item_qty}")
            
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=item.product_id,
                quantity=item_qty,
                unit_price=item.unit_price,
                discount=item.discount,
                line_total=item.line_total
            )
            self.db.add(sale_item)
            
            # Update stock
            product.stock_qty -= item_qty
            
            # Create inventory movement
            movement = InventoryMovement(
                product_id=item.product_id,
                change_qty=-item_qty,
                reason=f"Sale from quotation {quotation.quotation_number}"
            )
            self.db.add(movement)
        
        # Create payments
        for p in payments:
            payment = Payment(
                sale_id=sale.id,
                method=p.get("method"),
                amount=p.get("amount")
            )
            self.db.add(payment)
        
        # Mark quotation as converted
        quotation.status = "converted"
        quotation.converted_to_sale_id = sale.id
        quotation.updated_at = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(sale)
        
        logger.info(f"Converted quotation {quotation.quotation_number} to sale {sale.id}")
        self.db.refresh(sale)
        return sale

    def convert_to_sale_receipt_payload(
        self,
        quotation_id: int,
        payments: List[dict],
        cashier_id: int,
        acting_user: Optional[User] = None,
    ) -> dict:
        """Convert quotation to sale and return receipt data for printing."""
        sale = self.convert_to_sale(
            quotation_id=quotation_id,
            payments=payments,
            cashier_id=cashier_id,
            acting_user=acting_user,
        )
        payload = self.build_receipt_payload(quotation_id, acting_user=acting_user)
        payload["message"] = "Quotation converted to sale successfully"
        return payload
    
    def expire_quotations(self) -> int:
        """Mark expired quotations (background task)."""
        now = datetime.utcnow()
        expired = self.db.query(Quotation).filter(
            Quotation.status.in_(["draft", "sent"]),
            Quotation.valid_until.isnot(None),
            Quotation.valid_until < now
        ).all()
        
        count = 0
        for quotation in expired:
            quotation.status = "expired"
            quotation.updated_at = now
            count += 1
        
        if count > 0:
            self.db.commit()
            logger.info(f"Expired {count} quotations")
        
        return count
    
    def generate_pdf(self, quotation_id: int) -> bytes:
        """Generate a professional PDF quotation with shop header and compact line items."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import inch, mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

        quotation = (
            self.db.query(Quotation)
            .options(joinedload(Quotation.items))
            .filter(Quotation.id == quotation_id)
            .first()
        )
        if not quotation:
            raise ValueError(f"Quotation {quotation_id} not found")
        if not quotation.items:
            raise ValueError(f"Quotation {quotation_id} has no line items")

        settings = first_store_settings_for_tenant(self.db, quotation.tenant_id)
        store_name = (settings.store_name if settings else None) or "Store"
        store_phone = (settings.store_phone if settings else None) or ""
        store_location = (settings.store_location if settings else None) or ""

        cashier_user = self.db.get(User, quotation.created_by)
        cashier_name = (cashier_user.username if cashier_user else None) or "—"

        buffer = io.BytesIO()
        page_w, _page_h = A4
        margin = 18 * mm
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=margin,
            rightMargin=margin,
            topMargin=margin,
            bottomMargin=margin,
        )
        usable_w = page_w - 2 * margin

        styles = getSampleStyleSheet()
        primary = colors.HexColor(_PDF_PRIMARY)

        def _p(text: str, style) -> Paragraph:
            return Paragraph(xml_escape.escape(str(text or "")), style)

        store_title = ParagraphStyle(
            "StoreTitle",
            parent=styles["Heading1"],
            fontSize=16,
            leading=20,
            textColor=primary,
            alignment=TA_CENTER,
            spaceAfter=4,
        )
        store_sub = ParagraphStyle(
            "StoreSub",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4b5563"),
            alignment=TA_CENTER,
            spaceAfter=2,
        )
        doc_title = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading2"],
            fontSize=13,
            leading=16,
            textColor=primary,
            alignment=TA_CENTER,
            spaceBefore=10,
            spaceAfter=14,
        )
        label_style = ParagraphStyle(
            "Label",
            parent=styles["Normal"],
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#6b7280"),
        )
        value_style = ParagraphStyle(
            "Value",
            parent=styles["Normal"],
            fontSize=9,
            leading=11,
            textColor=colors.black,
        )
        footer_style = ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#9ca3af"),
            alignment=TA_CENTER,
        )

        story: list = []

        # —— Shop header ——
        story.append(_p(store_name, store_title))
        contact_parts = []
        if store_location:
            contact_parts.append(store_location.replace("\n", ", "))
        if store_phone:
            contact_parts.append(f"Tel: {store_phone}")
        if contact_parts:
            story.append(_p(" · ".join(contact_parts), store_sub))
        story.append(_p("QUOTATION", doc_title))
        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=colors.HexColor(_PDF_BORDER),
                spaceBefore=0,
                spaceAfter=12,
            )
        )

        # —— Quote + customer (two columns) ——
        created = quotation.created_at.strftime("%d %b %Y") if quotation.created_at else "—"
        valid = (
            quotation.valid_until.strftime("%d %b %Y")
            if quotation.valid_until
            else "30 days from date"
        )
        meta_left = [
            [_p("Quotation No.", label_style), _p(quotation.quotation_number, value_style)],
            [_p("Date", label_style), _p(created, value_style)],
            [_p("Valid Until", label_style), _p(valid, value_style)],
            [_p("Cashier", label_style), _p(cashier_name, value_style)],
            [_p("Status", label_style), _p(quotation.status.upper(), value_style)],
        ]
        meta_right = [[_p("Customer", label_style), _p(quotation.customer_name or "—", value_style)]]
        if quotation.customer_phone:
            meta_right.append([_p("Phone", label_style), _p(quotation.customer_phone, value_style)])
        if quotation.customer_email:
            meta_right.append([_p("Email", label_style), _p(quotation.customer_email, value_style)])

        col_w = usable_w / 2 - 6
        meta_table = Table(
            [[Table(meta_left, colWidths=[col_w * 0.38, col_w * 0.62]), Table(meta_right, colWidths=[col_w * 0.38, col_w * 0.62])]],
            colWidths=[usable_w / 2, usable_w / 2],
        )
        meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(meta_table)
        story.append(Spacer(1, 14))

        # —— Line items (compact product names) ——
        items_data = [["#", "Product", "Qty", "Unit", "Disc.", "Total"]]
        for idx, item in enumerate(quotation.items, 1):
            items_data.append(
                [
                    str(idx),
                    _short_product_label(item.product_name),
                    str(item.quantity),
                    _money(item.unit_price),
                    _money(item.discount),
                    _money(item.line_total),
                ]
            )

        # Column widths tuned for A4; product column stays narrow
        cw = [
            0.32 * inch,
            2.35 * inch,
            0.45 * inch,
            0.95 * inch,
            0.75 * inch,
            0.95 * inch,
        ]
        items_table = Table(items_data, colWidths=cw, repeatRows=1)
        items_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_PDF_HEADER_BG)),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("TOPPADDING", (0, 0), (-1, 0), 8),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("TOPPADDING", (0, 1), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(_PDF_ROW_ALT)]),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(_PDF_BORDER)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (0, -1), "CENTER"),
                    ("ALIGN", (1, 0), (1, -1), "LEFT"),
                    ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                    ("LEFTPADDING", (1, 1), (1, -1), 6),
                    ("RIGHTPADDING", (2, 1), (-1, -1), 6),
                ]
            )
        )
        story.append(items_table)
        story.append(Spacer(1, 12))

        # —— Totals (right-aligned block) ——
        totals_w = 2.4 * inch
        totals_data = [
            ["Subtotal", _money(quotation.subtotal)],
            ["Discount", _money(quotation.discount_total)],
            ["TOTAL", _money(quotation.total)],
        ]
        totals_table = Table(totals_data, colWidths=[totals_w * 0.55, totals_w * 0.45])
        totals_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -2), 9),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, -1), (-1, -1), 11),
                    ("TEXTCOLOR", (0, -1), (-1, -1), primary),
                    ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor(_PDF_BORDER)),
                    ("TOPPADDING", (0, -1), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        wrapper = Table([[None, totals_table]], colWidths=[usable_w - totals_w, totals_w])
        wrapper.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT")]))
        story.append(wrapper)

        if quotation.notes:
            story.append(Spacer(1, 10))
            note_style = ParagraphStyle(
                "Note",
                parent=styles["Normal"],
                fontSize=8,
                leading=10,
                textColor=colors.HexColor("#374151"),
            )
            story.append(
                Paragraph(
                    f"<b>Notes:</b> {xml_escape.escape(str(quotation.notes))}",
                    note_style,
                )
            )

        story.append(Spacer(1, 16))
        story.append(
            _p(
                "Prices are subject to confirmation. Thank you for your business.",
                footer_style,
            )
        )

        doc.build(story)
        buffer.seek(0)
        return buffer.read()

