"""
Quotation Service Module (Additive Only)
Handles quotation creation, management, and conversion to sales.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import InventoryMovement, Product, Customer, Sale, SaleItem, Payment, User
from .quotation_models import Quotation, QuotationItem
from .tenant_scope import row_visible, same_tenant

logger = logging.getLogger(__name__)


class QuotationService:
    """Service for managing quotations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def _generate_quotation_number(self) -> str:
        """Generate unique quotation number (e.g., Q-2024-001)."""
        year = datetime.now().year
        # Get the last quotation number for this year
        last_quotation = self.db.query(Quotation).filter(
            Quotation.quotation_number.like(f"Q-{year}-%")
        ).order_by(Quotation.id.desc()).first()
        
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
            quotation_number=self._generate_quotation_number(),
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
        return self.db.get(Quotation, quotation_id)
    
    def list_quotations(
        self,
        customer_id: Optional[int] = None,
        customer_phone: Optional[str] = None,
        status: Optional[str] = None,
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
        
        total = query.count()
        quotations = query.order_by(Quotation.created_at.desc()).limit(limit).offset(offset).all()
        
        return quotations, total
    
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
        """Delete quotation (only draft quotations can be deleted)."""
        quotation = self.get_quotation(quotation_id)
        if not quotation:
            return False
        if acting_user is not None and not row_visible(getattr(quotation, "tenant_id", None), acting_user):
            return False

        if quotation.status != "draft":
            raise ValueError(f"Cannot delete quotation with status '{quotation.status}'")
        
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
        return sale
    
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
        """Generate PDF quotation document."""
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        
        quotation = self.get_quotation(quotation_id)
        if not quotation:
            raise ValueError(f"Quotation {quotation_id} not found")
        
        # Create PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        story = []
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#1e40af'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        # Title
        story.append(Paragraph("QUOTATION", title_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Quotation details
        data = [
            ["Quotation Number:", quotation.quotation_number],
            ["Date:", quotation.created_at.strftime("%Y-%m-%d")],
            ["Valid Until:", quotation.valid_until.strftime("%Y-%m-%d") if quotation.valid_until else "N/A"],
            ["Status:", quotation.status.upper()],
        ]
        
        if quotation.customer_name:
            data.append(["Customer:", quotation.customer_name])
        if quotation.customer_phone:
            data.append(["Phone:", quotation.customer_phone])
        if quotation.customer_email:
            data.append(["Email:", quotation.customer_email])
        
        table = Table(data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(table)
        story.append(Spacer(1, 0.3*inch))
        
        # Items table
        items_data = [["#", "Product", "Qty", "Unit Price", "Discount", "Total"]]
        for idx, item in enumerate(quotation.items, 1):
            items_data.append([
                str(idx),
                item.product_name,
                str(item.quantity),
                f"${float(item.unit_price):.2f}",
                f"${float(item.discount):.2f}",
                f"${float(item.line_total):.2f}"
            ])
        
        items_table = Table(items_data, colWidths=[0.5*inch, 3*inch, 0.7*inch, 1*inch, 1*inch, 1*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
        story.append(items_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Totals
        totals_data = [
            ["Subtotal:", f"${float(quotation.subtotal):.2f}"],
            ["Discount:", f"${float(quotation.discount_total):.2f}"],
            ["TOTAL:", f"${float(quotation.total):.2f}"]
        ]
        
        totals_table = Table(totals_data, colWidths=[4*inch, 2*inch])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 14),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#1e40af')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(totals_table)
        
        if quotation.notes:
            story.append(Spacer(1, 0.3*inch))
            story.append(Paragraph(f"<b>Notes:</b> {quotation.notes}", styles['Normal']))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer.read()

