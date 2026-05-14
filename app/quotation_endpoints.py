"""
REST endpoints for quotation management.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import Depends, HTTPException, Body
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import auth
from .database import get_db
from .models import User
from .quotation_service import QuotationService
from .tenant_scope import row_visible

logger = logging.getLogger(__name__)


class QuotationItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: Optional[Decimal] = None
    discount: Optional[Decimal] = 0
    notes: Optional[str] = None


class QuotationCreate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    items: List[QuotationItemCreate]
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None


class QuotationItemRead(BaseModel):
    id: int
    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    discount: Decimal
    line_total: Decimal

    class Config:
        from_attributes = True


class QuotationRead(BaseModel):
    id: int
    quotation_number: str
    customer_id: Optional[int]
    customer_name: Optional[str]
    customer_phone: Optional[str]
    total: Decimal
    status: str
    valid_until: Optional[datetime]
    created_at: datetime
    items: List[QuotationItemRead]

    class Config:
        from_attributes = True


class QuotationConvertRequest(BaseModel):
    payments: List[dict] = Field(..., description="List of payment methods and amounts")


def register_quotation_endpoints(app):
    """Register quotation endpoints with FastAPI app."""

    @app.post("/api/quotations", response_model=QuotationRead)
    async def create_quotation(
        quotation_data: QuotationCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(auth.get_current_active_user),
    ):
        """Create a new quotation."""
        service = QuotationService(db)

        items = [
            {
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price) if item.unit_price else None,
                "discount": float(item.discount) if item.discount else 0,
                "notes": item.notes,
            }
            for item in quotation_data.items
        ]

        try:
            quotation = service.create_quotation(
                customer_id=quotation_data.customer_id,
                customer_name=quotation_data.customer_name,
                customer_phone=quotation_data.customer_phone,
                customer_email=quotation_data.customer_email,
                items=items,
                valid_until=quotation_data.valid_until,
                notes=quotation_data.notes,
                created_by=current_user.id,
                tenant_id=current_user.tenant_id,
                acting_user=current_user,
            )

            db.refresh(quotation)
            return quotation

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error creating quotation: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/quotations/{quotation_id}", response_model=QuotationRead)
    async def get_quotation(
        quotation_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(auth.get_current_active_user),
    ):
        """Get quotation by ID."""
        service = QuotationService(db)
        quotation = service.get_quotation(quotation_id)

        if not quotation or not row_visible(getattr(quotation, "tenant_id", None), current_user):
            raise HTTPException(status_code=404, detail="Quotation not found")

        return quotation

    @app.get("/api/quotations", response_model=dict)
    async def list_quotations(
        customer_id: Optional[int] = None,
        customer_phone: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
        current_user: User = Depends(auth.get_current_active_user),
    ):
        """List quotations with filters."""
        service = QuotationService(db)
        quotations, total = service.list_quotations(
            customer_id=customer_id,
            customer_phone=customer_phone,
            status=status,
            tenant_id=current_user.tenant_id,
            limit=limit,
            offset=offset,
        )

        return {
            "quotations": [
                {
                    "id": q.id,
                    "quotation_number": q.quotation_number,
                    "customer_name": q.customer_name,
                    "total": float(q.total),
                    "status": q.status,
                    "created_at": q.created_at.isoformat(),
                }
                for q in quotations
            ],
            "total": total,
        }

    @app.put("/api/quotations/{quotation_id}", response_model=QuotationRead)
    async def update_quotation(
        quotation_id: int,
        update_data: dict = Body(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(auth.get_current_active_user),
    ):
        """Update quotation (only draft quotations)."""
        service = QuotationService(db)

        try:
            items = update_data.get("items")
            notes = update_data.get("notes")
            valid_until_str = update_data.get("valid_until")
            valid_until = None
            if valid_until_str:
                try:
                    valid_until = datetime.fromisoformat(valid_until_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            quotation = service.update_quotation(
                quotation_id=quotation_id,
                items=items,
                notes=notes,
                valid_until=valid_until,
                acting_user=current_user,
            )
            return quotation
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/quotations/{quotation_id}", status_code=204)
    async def delete_quotation(
        quotation_id: int,
        db: Session = Depends(get_db),
        current_admin: User = Depends(auth.get_current_admin_user),
    ):
        """Delete quotation (only draft quotations)."""
        service = QuotationService(db)

        try:
            success = service.delete_quotation(quotation_id, acting_user=current_admin)
            if not success:
                raise HTTPException(status_code=404, detail="Quotation not found")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/quotations/{quotation_id}/convert-to-sale", response_model=dict)
    async def convert_quotation_to_sale(
        quotation_id: int,
        convert_data: QuotationConvertRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(auth.get_current_active_user),
    ):
        """Convert quotation to sale."""
        service = QuotationService(db)

        try:
            sale = service.convert_to_sale(
                quotation_id=quotation_id,
                payments=convert_data.payments,
                cashier_id=current_user.id,
                acting_user=current_user,
            )

            return {
                "sale_id": sale.id,
                "quotation_id": quotation_id,
                "message": "Quotation converted to sale successfully",
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error converting quotation: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/quotations/{quotation_id}/pdf")
    async def download_quotation_pdf(
        quotation_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(auth.get_current_active_user),
    ):
        """Download quotation as PDF."""
        service = QuotationService(db)

        try:
            q = service.get_quotation(quotation_id)
            if not q or not row_visible(getattr(q, "tenant_id", None), current_user):
                raise HTTPException(status_code=404, detail="Quotation not found")
            pdf_bytes = service.generate_pdf(quotation_id)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=quotation_{quotation_id}.pdf"
                },
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(f"Error generating PDF: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
