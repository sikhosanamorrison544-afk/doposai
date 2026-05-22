import csv
import io
import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from typing import Optional as OptionalType
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware

from . import auth
try:
    from .ai_service import ai_service, OLLAMA_MODEL, OLLAMA_BASE_URL
    AI_SERVICE_AVAILABLE = True
except ImportError as e:
    logging.warning(f"AI service not available: {e}. AI features will be disabled.")
    AI_SERVICE_AVAILABLE = False
    ai_service = None
    OLLAMA_MODEL = None
    OLLAMA_BASE_URL = None
from .backup_service import get_backup_service
from .config import (
    BASE_DIR,
    DATABASE_URL,
    STORE_NAME,
    STORE_PHONE,
    STORE_LOCATION,
    get_cors_origins_and_credentials,
)
from .database import Base, engine, get_db, SessionLocal
from .accounting_models import (
    ChartOfAccount, JournalEntry, JournalEntryLine, AccountingPeriod,
    ExpenseAccountMapping, FixedAsset, AssetDepreciationSchedule
)
from .accounting_engine import AccountingEngine
from .accounting_setup import initialize_chart_of_accounts, verify_chart_of_accounts
from .accounting_reports import AccountingReports
from .accounting_backfill import backfill_historical_transactions
from .escpos_printer import print_receipt, print_withdrawal_receipt
from .quotation_models import Tenant, Quotation, QuotationItem
from .saas_models import PasswordResetToken, RefreshToken
from .models import (
    Category,
    CashierShift,
    Customer,
    InventoryMovement,
    LaybyCustomer,
    LaybyPayment,
    LaybyTransaction,
    Notification,
    Payment,
    Product,
    Sale,
    SaleItem,
    StoreSettings,
    User,
    Withdrawal,
    Refund,
    RefundItem,
    ImportJob,
)

from . import tenant_scope
from .permissions import (
    Perm,
    ROLE_DESCRIPTIONS,
    dep_perm,
    has_permission,
    permissions_as_strings,
    require_permission,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    logging.warning(
        "Could not run create_all on import: %s. Service will start; DB will retry on first use.",
        e,
    )

try:
    ImportJob.__table__.create(bind=engine, checkfirst=True)
except Exception as e:
    logging.warning("Could not ensure import_jobs table: %s", e)

try:
    from migrate_import_jobs import migrate as _migrate_import_jobs

    _migrate_import_jobs()
except Exception as e:
    logging.warning("Could not upgrade import_jobs columns: %s", e)

# Initialize Chart of Accounts on startup (if not already initialized)
try:
    with SessionLocal() as db:
        initialize_chart_of_accounts(db)
        logging.info("Accounting system initialized successfully")
except Exception as e:
    logging.warning(
        "Could not initialize Chart of Accounts: %s. Accounting features will be disabled until COA is initialized.",
        e,
    )

app = FastAPI(title="Raspberry Pi Offline POS", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    """Liveness probe without DB access. Use as Render health check path so deploys don't fail if DB is slow to connect."""
    return {"status": "ok"}


_cors_origins, _cors_credentials = get_cors_origins_and_credentials()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)

from .billing.feature_middleware import PlanFeatureMiddleware

app.add_middleware(PlanFeatureMiddleware)

from .billing.routes import billing_router, payments_router, subscriptions_router
from .platform_routes import router as platform_router
from .saas_auth_routes import router as saas_auth_router
from .enterprise.routes import router as enterprise_router
from . import enterprise_models  # noqa: F401 — register enterprise ORM tables
from .whatsapp.routes import (
    api_router as whatsapp_api_router,
    webhook_router as whatsapp_webhook_router,
)
from .whatsapp import models as _whatsapp_models  # noqa: F401 — register ORM tables
from .bi.routes import router as bi_router

app.include_router(saas_auth_router)
app.include_router(subscriptions_router)
app.include_router(payments_router)
app.include_router(billing_router)
app.include_router(platform_router)
app.include_router(enterprise_router)
app.include_router(whatsapp_webhook_router)
app.include_router(whatsapp_api_router)
app.include_router(bi_router)

# Background task to periodically process offline backup queue
async def process_backup_queue_periodically():
    """Background task to periodically process offline backup queue."""
    import asyncio
    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            backup_service = get_backup_service()
            if backup_service.is_enabled():
                db = SessionLocal()
                try:
                    backup_service.process_offline_queue(db)
                except Exception as e:
                    logging.error(f"Error processing backup queue: {e}")
                finally:
                    db.close()
        except Exception as e:
            logging.error(f"Error in backup queue processor: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    """Start background tasks on application startup."""
    import asyncio

    from .config import APP_ENV
    from .startup_config import DISABLE_STARTUP_OLLAMA

    if APP_ENV == "production" and (
        "change" in (auth.SECRET_KEY or "").lower() or len(auth.SECRET_KEY or "") < 32
    ):
        logging.warning(
            "JWT_SECRET_KEY looks weak or default. Set a strong JWT_SECRET_KEY in the host environment."
        )

    # Start backup queue processor in background
    asyncio.create_task(process_backup_queue_periodically())

    if DISABLE_STARTUP_OLLAMA:
        logging.info(
            "Startup Ollama pre-warm disabled (set DISABLE_STARTUP_OLLAMA=0 to enable)."
        )
    else:
        asyncio.create_task(_start_ollama_background_tasks())

    try:
        from .scheduler_service import start_scheduler

        start_scheduler()
        logging.info("Scheduler service started successfully")
    except Exception as e:
        logging.error(f"Failed to start scheduler service: {e}", exc_info=True)

    try:
        from .notification_service import NotificationService

        db = SessionLocal()
        try:
            notification_service = NotificationService(db)
            count = notification_service.check_all_products_and_create_notifications()
            if count > 0:
                logging.info(
                    "Created %s notifications for low-stock/out-of-stock products on startup",
                    count,
                )
            else:
                logging.info("No new notifications needed - all products are in stock")
        finally:
            db.close()
    except Exception as e:
        logging.error(
            "Error checking products for notifications on startup: %s", e, exc_info=True
        )


async def _start_ollama_background_tasks():
    import asyncio
    """Ollama pre-warm and keep-alive (skipped on small cloud instances by default)."""

    # Ensure Ollama is running (start in background if not), then pre-warm
    async def ensure_and_prewarm_ollama():
        """Start Ollama if needed, then pre-warm the model so it's always available."""
        await asyncio.sleep(1)  # Brief delay for system stability
        try:
            if not AI_SERVICE_AVAILABLE or not ai_service:
                return
            # Try to start Ollama if it's not responding (runs separately in background)
            await asyncio.to_thread(ai_service.ensure_ollama_running, 0)  # No throttle on first run
            await asyncio.sleep(2)  # Give Ollama time to bind and start
            logging.info("Pre-warming Ollama and loading model...")
            is_available = ai_service._check_ollama_available(retries=2, use_cache=False)
            if is_available:
                await asyncio.to_thread(ai_service.warm_model)
                logging.info("✓ Ollama model pre-warmed (kept in memory)")
            else:
                logging.warning("⚠ Ollama not available yet; it may still be starting. Will retry on first use.")
        except Exception as e:
            logging.warning(f"Error ensuring/pre-warming Ollama: {e}")
    
    asyncio.create_task(ensure_and_prewarm_ollama())
    
    # Keep Ollama running and model loaded: ensure process if down, warm every 10 min
    async def keep_ollama_alive():
        """If Ollama is down, try to start it. Keep model loaded by warming every 10 minutes."""
        await asyncio.sleep(60)  # First run 1 min after startup
        tick = 0
        while True:
            try:
                await asyncio.sleep(60)  # Every 1 minute
                tick += 1
                if not AI_SERVICE_AVAILABLE or not ai_service:
                    continue
                if tick % 10 == 0:  # Every 10 min: ensure running then warm
                    await asyncio.to_thread(ai_service.ensure_ollama_running, 120)  # Throttle start attempts to 2 min
                    await asyncio.to_thread(ai_service.warm_model)
            except Exception as e:
                logging.debug(f"Keep-alive error (non-critical): {e}")
    
    asyncio.create_task(keep_ollama_alive())


@app.on_event("shutdown")
async def shutdown_event():
    """Stop background tasks on application shutdown."""
    try:
        from .scheduler_service import stop_scheduler
        stop_scheduler()
        logging.info("Scheduler service stopped")
    except Exception as e:
        logging.error(f"Error stopping scheduler service: {e}", exc_info=True)
    try:
        from .whatsapp.meta_client import shutdown as wa_shutdown
        await wa_shutdown()
    except Exception as e:
        logging.error(f"Error closing WhatsApp HTTP client: {e}", exc_info=True)

# Handle favicon requests before mounting static files
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Return 204 No Content for favicon requests to prevent 404 errors."""
    return Response(status_code=204)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
  """Return FastAPI HTTP errors as plain detail strings (for mobile/web clients)."""
  detail = exc.detail
  if not isinstance(detail, str):
    detail = str(detail)
  return JSONResponse(status_code=exc.status_code, content={"detail": detail})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unexpected exceptions; keep billing/payment errors readable."""
    import traceback
    from fastapi.exceptions import RequestValidationError

    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    if isinstance(exc, RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    error_detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logging.error("Unhandled error on %s: %s", request.url.path, error_detail)
    return JSONResponse(
        status_code=500,
        content={"detail": "Server error. Please try again or contact support."},
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    # Get store name from database, fallback to config
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("index.html", {"request": request, "store_name": store_name})


@app.get("/accounting", response_class=HTMLResponse)
async def accounting_page(request: Request, db: Session = Depends(get_db)):
    """Accounting Reports Page"""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse(
        "accounting.html",
        {"request": request, "store_name": store_name}
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db)):
    # Authentication for actions is enforced on the API endpoints.
    # Get store name from database, fallback to config
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("admin.html", {"request": request, "store_name": store_name})


@app.get("/platform/tenants", response_class=HTMLResponse)
async def platform_tenants_page(request: Request, db: Session = Depends(get_db)):
    """Platform owner: list all businesses (tenants) on this POS deployment."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse(
        "platform-tenants.html",
        {"request": request, "store_name": store_name},
    )


@app.get("/platform/tanents", response_class=RedirectResponse)
async def platform_tenants_typo():
    """Common typo → correct path."""
    return RedirectResponse(url="/platform/tenants", status_code=307)


@app.get("/store-settings", response_class=HTMLResponse)
async def store_settings_page(request: Request, db: Session = Depends(get_db)):
    # Authentication for actions is enforced on the API endpoints.
    # Get store name from database, fallback to config
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("store-settings.html", {"request": request, "store_name": store_name})


@app.get("/quotations", response_class=HTMLResponse)
async def quotations_page(request: Request, db: Session = Depends(get_db)):
    """Quotation management page."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("quotations.html", {"request": request, "store_name": store_name})


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, db: Session = Depends(get_db)):
    """Public reset-password page; reads ?token=... from query string.

    The token is NOT validated here — that happens server-side when the user
    submits the form. We just render the page; bad tokens get a clear error.
    """
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse(
        "reset-password.html",
        {"request": request, "store_name": store_name},
    )


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


@app.post("/api/auth/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    from .http_rate_limit import rate_limit_hit

    rate_limit_hit(request, "legacy_oauth_token", max_calls=40, window_sec=60)
    logging.info(f"Login attempt for username: {form_data.username}")
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        # Check if user exists for better error messaging
        found_user = auth.get_user_by_username(db, form_data.username)
        if found_user:
            if not found_user.is_active:
                logging.warning(f"Login failed: User '{form_data.username}' exists but is inactive")
            else:
                logging.warning(f"Login failed: User '{form_data.username}' exists but password is incorrect")
        else:
            logging.warning(f"Login failed: User '{form_data.username}' not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logging.info(f"Login successful for user: {user.username} (role: {user.role})")
    payload = {"sub": user.username, "role": user.role}
    if user.tenant_id is not None:
        payload["tid"] = user.tenant_id
    access_token = auth.create_access_token(data=payload)
    return Token(access_token=access_token, username=user.username, role=user.role)


class UserMeRead(BaseModel):
    username: str
    role: str
    permissions: List[str]
    role_description: str


@app.get("/api/auth/me", response_model=UserMeRead)
async def read_current_user_me(
    current_user: User = Depends(auth.get_current_active_user),
):
    """Current user role and permission list for UI gating."""
    role = (current_user.role or "cashier").strip().lower()
    if role == "owner":
        role = "admin"
    return UserMeRead(
        username=current_user.username,
        role=role,
        permissions=permissions_as_strings(current_user),
        role_description=ROLE_DESCRIPTIONS.get(role, ""),
    )


class ProductCreate(BaseModel):
    name: str
    barcode: Optional[str] = None
    category_id: Optional[int] = None
    stock_qty: float = Field(default=0, ge=0, description="Stock quantity must be >= 0")
    reserved_qty: float = Field(default=0, ge=0, description="Stock reserved for layby / to-collect")
    cost_price: Decimal
    selling_price: Decimal
    is_active: bool = True
    expiry_date: Optional[date] = None
    
    @field_validator('stock_qty')
    @classmethod
    def validate_stock_qty(cls, v):
        if v < 0:
            raise ValueError('Stock quantity cannot be negative')
        return float(v)


class ProductRead(ProductCreate):
    id: int

    class Config:
        from_attributes = True


@app.get("/api/products", response_model=List[ProductRead])
async def list_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    products = (
        tenant_scope.filter_products(db, current_user)
        .filter(Product.is_active == True)  # noqa: E712
        .order_by(Product.name)
        .all()
    )
    return products


@app.get("/api/products/export/csv")
async def export_products_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Export all products as CSV file for backup (round-trip safe with import)."""
    from .inventory_csv import build_products_csv_bytes, product_to_export_row

    products = tenant_scope.filter_products(db, current_user).order_by(Product.name).all()
    rows = [product_to_export_row(p) for p in products]
    content = build_products_csv_bytes(rows)

    from datetime import datetime
    filename = f"inventory_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def generate_unique_barcode(db: Session, user: User) -> str:
    """Generate a unique auto-assigned barcode in format AUTO-XXXXXX (per-tenant)."""
    # Find the highest existing auto-generated barcode number in this tenant
    existing_auto_barcodes = (
        tenant_scope.filter_products(db, user)
        .with_entities(Product.barcode)
        .filter(Product.barcode.like("AUTO-%"))
        .all()
    )

    max_num = 0
    for (barcode,) in existing_auto_barcodes:
        if barcode and barcode.startswith("AUTO-"):
            try:
                # Extract number from AUTO-XXXXXX format
                num_str = barcode.split("-", 1)[1] if "-" in barcode else ""
                num = int(num_str) if num_str.isdigit() else 0
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                continue

    # Generate next barcode (6-digit zero-padded)
    next_num = max_num + 1
    new_barcode = f"AUTO-{next_num:06d}"

    # Double-check it doesn't exist (safety check)
    existing = tenant_scope.filter_products(db, user).filter(Product.barcode == new_barcode).first()
    if existing:
        # If it exists, find the next available number
        while existing:
            next_num += 1
            new_barcode = f"AUTO-{next_num:06d}"
            existing = tenant_scope.filter_products(db, user).filter(Product.barcode == new_barcode).first()

    return new_barcode


@app.post("/api/products", response_model=ProductRead)
async def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(auth.get_current_admin_user),
):
    # Ensure stock_qty is non-negative (Pydantic validation should catch this, but extra safeguard)
    if product.stock_qty < 0:
        raise HTTPException(status_code=400, detail="Stock quantity cannot be negative")
    
    # Auto-assign barcode if not provided
    product_dict = product.dict()
    if not product_dict.get('barcode') or not product_dict['barcode'].strip():
        new_barcode = generate_unique_barcode(db, current_admin)
        product_dict['barcode'] = new_barcode
        logging.info(f"Auto-assigned barcode {new_barcode} to product: {product_dict.get('name', 'Unknown')}")
    
    db_product = Product(**product_dict, tenant_id=tenant_scope.tenant_id_for_row(current_admin))
    # Extra safeguard: ensure stock_qty is non-negative
    if db_product.stock_qty < 0:
        db_product.stock_qty = 0.0
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    if product.stock_qty:
        movement = InventoryMovement(
            product_id=db_product.id,
            change_qty=product.stock_qty,
            reason="Initial stock",
        )
        db.add(movement)
        db.commit()
    
    # Sync to Google Sheets backup
    try:
        backup_service = get_backup_service()
        if backup_service.is_enabled():
            backup_service.sync_product_create(db, db_product)
    except Exception as e:
        logging.error(f"Error syncing product to backup: {e}")
    
    # Check for expiring products after product creation
    try:
        from .notification_service import NotificationService
        notification_service = NotificationService(db)
        notification_service.check_expiring_products_and_create_notifications(days_ahead=7)
        notification_service.check_expiring_products_and_send_email(days_ahead=7)
    except Exception as e:
        logging.warning(f"Error checking expiring products: {e}")
    
    return db_product


@app.get("/api/products/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    product = tenant_scope.require_product(db, product_id, current_user)


@app.put("/api/products/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: int,
    product: ProductCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(auth.get_current_admin_user),
):
    db_product = tenant_scope.require_product(db, product_id, current_admin)
    
    # Ensure stock_qty is non-negative
    if product.stock_qty < 0:
        raise HTTPException(status_code=400, detail="Stock quantity cannot be negative")
    
    old_stock = db_product.stock_qty
    
    for field, value in product.dict().items():
        setattr(db_product, field, value)
    
    # Extra safeguard: ensure stock_qty is non-negative
    if db_product.stock_qty < 0:
        db_product.stock_qty = 0.0
    
    db.commit()
    db.refresh(db_product)
    
    new_stock = db_product.stock_qty

    diff = new_stock - old_stock
    if diff:
        movement = InventoryMovement(
            product_id=db_product.id,
            change_qty=diff,
            reason="Stock adjustment",
        )
        db.add(movement)
        db.commit()
    
    # Check for low stock after stock update
    try:
        from .notification_service import NotificationService
        notification_service = NotificationService(db)
        notification_service.check_low_stock(db_product)
        # Send batch email with all low-stock products
        notification_service.check_all_products_low_stock()
    except Exception as e:
        logging.warning(f"Error checking low stock for product {db_product.id}: {e}")
    
    # Check for expiring products after product update
    try:
        from .notification_service import NotificationService
        notification_service = NotificationService(db)
        notification_service.check_expiring_products_and_create_notifications(days_ahead=7)
        notification_service.check_expiring_products_and_send_email(days_ahead=7)
    except Exception as e:
        logging.warning(f"Error checking expiring products: {e}")
    
    # Sync to Google Sheets backup
    try:
        backup_service = get_backup_service()
        if backup_service.is_enabled():
            backup_service.sync_product_update(db, db_product)
    except Exception as e:
        logging.error(f"Error syncing product update to backup: {e}")
    
    return db_product


@app.delete("/api/products/{product_id}")
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(auth.get_current_admin_user),
):
    product = tenant_scope.require_product(db, product_id, current_admin)
    db.delete(product)
    db.commit()

    # Sync deletion to Google Sheets backup
    try:
        backup_service = get_backup_service()
        if backup_service.is_enabled():
            backup_service.sync_product_delete(db, product_id)
    except Exception as e:
        logging.error(f"Error syncing product deletion to backup: {e}")
    
    return {"ok": True}


@app.get("/api/products/barcode/{barcode}", response_model=Optional[ProductRead])
async def find_by_barcode(
    barcode: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    product = (
        tenant_scope.filter_products(db, current_user)
        .filter(Product.barcode == barcode)
        .first()
    )
    return product


# ==================== INVENTORY IMPORT ====================

def get_or_create_category(db: Session, name: str, user: User, description: str = "") -> Optional[Category]:
    """Get existing category or create a new one (scoped to the user's tenant)."""
    if not name or not name.strip():
        return None
    name = name.strip()
    cat = tenant_scope.filter_categories(db, user).filter(Category.name == name).first()
    if cat:
        return cat
    cat = Category(
        name=name,
        description=description or None,
        tenant_id=tenant_scope.tenant_id_for_row(user),
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def parse_decimal(value: str) -> Decimal:
    """Parse currency/number text (delegates to inventory_csv)."""
    from .inventory_csv import parse_decimal as _parse_decimal

    return _parse_decimal(value)


def parse_float(value: str) -> float:
    """Parse number text (delegates to inventory_csv)."""
    from .inventory_csv import parse_float as _parse_float

    return _parse_float(value)


def extract_products_from_csv(content: bytes) -> List[dict]:
    """Extract product data from CSV (export format, legacy headers, aliases)."""
    from .inventory_csv import extract_products_from_csv_bytes

    return extract_products_from_csv_bytes(content)


def extract_products_from_pdf(content: bytes) -> List[dict]:
    """Extract product data from PDF content."""
    try:
        import pdfplumber
    except ImportError:
        raise HTTPException(status_code=500, detail="PDF processing library not installed")
    
    products = []
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        try:
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        # Assume first row is header
                        headers = [str(cell).strip().lower() if cell else "" for cell in table[0]]
                        # Try to find column indices
                        name_idx = None
                        code_idx = None
                        category_idx = None
                        cost_idx = None
                        price_idx = None
                        stock_idx = None
                        
                        for i, header in enumerate(headers):
                            if 'name' in header or 'product' in header:
                                name_idx = i
                            elif 'code' in header or 'barcode' in header:
                                code_idx = i
                            elif 'category' in header:
                                category_idx = i
                            elif 'cost' in header or 'average cost' in header:
                                cost_idx = i
                            elif 'price' in header or 'selling' in header:
                                price_idx = i
                            elif 'stock' in header or 'quantity' in header:
                                stock_idx = i
                        
                        # Process data rows
                        for row in table[1:]:
                            if not row or len(row) < 2:
                                continue
                            name = str(row[name_idx]).strip() if name_idx and name_idx < len(row) else ""
                            if not name:
                                continue
                            
                            products.append({
                                'name': name,
                                'code': str(row[code_idx]).strip() if code_idx and code_idx < len(row) else "",
                                'category': str(row[category_idx]).strip() if category_idx and category_idx < len(row) else "",
                                'cost': parse_decimal(str(row[cost_idx]) if cost_idx and cost_idx < len(row) else "0"),
                                'price': parse_decimal(str(row[price_idx]) if price_idx and price_idx < len(row) else "0"),
                                'stock': parse_float(str(row[stock_idx]) if stock_idx and stock_idx < len(row) else "0"),
                            })
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        logging.error(f"Error parsing PDF: {e}")
        raise HTTPException(status_code=400, detail=f"Error parsing PDF: {str(e)}")
    
    return products


def extract_products_from_word(content: bytes) -> List[dict]:
    """Extract product data from Word document content."""
    try:
        from docx import Document
    except ImportError:
        raise HTTPException(status_code=500, detail="Word document processing library not installed")
    
    products = []
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        try:
            doc = Document(tmp_path)
            # Try to find table in document
            for table in doc.tables:
                if len(table.rows) < 2:
                    continue
                # First row is header
                headers = [cell.text.strip().lower() for cell in table.rows[0].cells]
                name_idx = None
                code_idx = None
                category_idx = None
                cost_idx = None
                price_idx = None
                stock_idx = None
                
                for i, header in enumerate(headers):
                    if 'name' in header or 'product' in header:
                        name_idx = i
                    elif 'code' in header or 'barcode' in header:
                        code_idx = i
                    elif 'category' in header:
                        category_idx = i
                    elif 'cost' in header or 'average cost' in header:
                        cost_idx = i
                    elif 'price' in header or 'selling' in header:
                        price_idx = i
                    elif 'stock' in header or 'quantity' in header:
                        stock_idx = i
                
                # Process data rows
                for row in table.rows[1:]:
                    cells = [cell.text.strip() for cell in row.cells]
                    if len(cells) < 2:
                        continue
                    name = cells[name_idx] if name_idx and name_idx < len(cells) else ""
                    if not name:
                        continue
                    
                    products.append({
                        'name': name,
                        'code': cells[code_idx] if code_idx and code_idx < len(cells) else "",
                        'category': cells[category_idx] if category_idx and category_idx < len(cells) else "",
                        'cost': parse_decimal(cells[cost_idx] if cost_idx and cost_idx < len(cells) else "0"),
                        'price': parse_decimal(cells[price_idx] if price_idx and price_idx < len(cells) else "0"),
                        'stock': parse_float(cells[stock_idx] if stock_idx and stock_idx < len(cells) else "0"),
                    })
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        logging.error(f"Error parsing Word document: {e}")
        raise HTTPException(status_code=400, detail=f"Error parsing Word document: {str(e)}")
    
    return products


@app.post("/api/products/import")
async def import_inventory(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin: User = Depends(auth.get_current_admin_user),
):
    """Import inventory from CSV, PDF, or Word file."""
    from . import import_jobs
    from . import tenant_scope
    from .inventory_upload import parse_inventory_upload
    from .startup_config import IMPORT_ASYNC_MIN_BYTES

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    file_ext = Path(file.filename).suffix.lower()
    content = await file.read()
    tenant_id = tenant_scope.tenant_id_for_row(current_admin)

    # Large uploads: persist bytes and return 202 before CSV/PDF parsing (avoids gateway timeout).
    defer_parse = len(content) >= IMPORT_ASYNC_MIN_BYTES or file_ext in (
        ".pdf",
        ".doc",
        ".docx",
    )
    if defer_parse:
        job_id = import_jobs.create_job_from_bytes(
            db,
            tenant_id=tenant_id,
            user_id=current_admin.id,
            file_name=file.filename,
            file_ext=file_ext,
            content=content,
        )
        import_jobs.kick_job(job_id)
        logging.info(
            "Import job %s accepted (deferred parse, %s bytes) for user %s",
            job_id,
            len(content),
            current_admin.id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "queued",
                "job_id": job_id,
                "total_rows": 0,
                "message": (
                    "Import queued. Parsing and loading products in the background — "
                    "keep this page open until complete."
                ),
            },
        )

    try:
        products_data, import_meta = parse_inventory_upload(content, file_ext)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not products_data:
        raise HTTPException(status_code=400, detail="No products found in file")

    max_import_rows = int(os.environ.get("MAX_IMPORT_ROWS", "10000"))
    if len(products_data) > max_import_rows:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File has {len(products_data)} product rows; maximum is {max_import_rows}. "
                "Split the file into smaller CSVs and import each one."
            ),
        )

    sync_max = int(os.environ.get("SYNC_IMPORT_MAX_ROWS", "15"))
    if len(products_data) > sync_max:
        job_id = import_jobs.create_job(
            db,
            tenant_id=tenant_id,
            user_id=current_admin.id,
            total_rows=len(products_data),
            products_data=products_data,
            import_meta=import_meta,
        )
        import_jobs.kick_job(job_id)
        logging.info(
            "Import job %s accepted (%s rows) for user %s",
            job_id,
            len(products_data),
            current_admin.id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "queued",
                "job_id": job_id,
                "total_rows": len(products_data),
                "message": (
                    f"Importing {len(products_data)} products in the background. "
                    "Keep this page open until complete."
                ),
            },
        )

    from .inventory_import import import_products_into_db

    result = import_products_into_db(
        db,
        current_admin,
        products_data,
        get_or_create_category,
    )
    if import_meta:
        result["columns_mapped"] = import_meta.get("columns_mapped", {})
        if import_meta.get("stock_mode"):
            result["stock_mode"] = import_meta["stock_mode"]
    return result


@app.get("/api/products/import/status/{job_id}")
async def import_inventory_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_admin: User = Depends(auth.get_current_admin_user),
):
    """Poll background inventory import job status."""
    from . import import_jobs

    import_jobs.kick_job(job_id)
    job = import_jobs.get_job(db, job_id)
    if not job or not import_jobs.job_visible_to_user(job, current_admin):
        raise HTTPException(status_code=404, detail="Import job not found")

    status = job["status"]
    if status == "queued":
        status = "processing"

    payload: dict = {
        "job_id": job_id,
        "status": status,
        "total_rows": job.get("total_rows", 0),
        "processed": job.get("processed", 0),
    }
    if job["status"] == "complete":
        payload["status"] = "complete"
        payload["result"] = job.get("result")
    elif job["status"] == "failed":
        payload["status"] = "failed"
        payload["error"] = job.get("error") or "Import failed"
    return payload


class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class CustomerRead(CustomerCreate):
    id: int
    credit_balance: Decimal

    class Config:
        from_attributes = True


@app.get("/api/customers", response_model=List[CustomerRead])
async def list_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    customers = tenant_scope.filter_customers(db, current_user).order_by(Customer.name).all()
    return customers


@app.post("/api/customers", response_model=CustomerRead)
async def create_customer(
    customer: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    db_customer = Customer(**customer.dict(), tenant_id=tenant_scope.tenant_id_for_row(current_user))
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer


class SaleItemInput(BaseModel):
    product_id: int
    quantity: int
    unit_price: Decimal
    discount: Decimal = Decimal("0.00")


class PaymentInput(BaseModel):
    method: str  # cash, mobile_money, card, credit
    amount: Decimal


class SaleCreate(BaseModel):
    customer_id: Optional[int] = None
    items: List[SaleItemInput]
    payments: List[PaymentInput]
    notes: Optional[str] = None
    collection_status: str = "collected"  # "collected" or "to_collect"
    branch_id: Optional[int] = None  # admin override; cashiers use assigned branch


class SaleRead(BaseModel):
    id: int
    created_at: datetime
    subtotal: Decimal
    discount_total: Decimal
    total: Decimal

    class Config:
        from_attributes = True


@app.post("/api/sales", response_model=SaleRead)
async def create_sale(
    sale_data: SaleCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    if not sale_data.items:
        raise HTTPException(status_code=400, detail="No items in sale")

    # Ensure all values are Decimal for consistent calculations
    subtotal = sum(
        (Decimal(str(item.unit_price)) * Decimal(str(item.quantity))) for item in sale_data.items
    )
    discount_total = sum(Decimal(str(item.discount)) for item in sale_data.items)
    total = subtotal - discount_total

    if total <= 0:
        raise HTTPException(status_code=400, detail="Total must be positive")

    # Ensure payments cover total (allow minor rounding differences)
    payment_sum = sum(Decimal(str(p.amount)) for p in sale_data.payments)
    if payment_sum + Decimal("0.01") < total:
        raise HTTPException(status_code=400, detail="Insufficient payment amount")

    if sale_data.customer_id:
        tenant_scope.require_customer(db, sale_data.customer_id, current_user)

    # Get active shift for this cashier
    active_shift = (
        tenant_scope.filter_shifts(db, current_user)
        .filter(
            CashierShift.cashier_id == current_user.id,
            CashierShift.end_time.is_(None),
        )
        .first()
    )

    # Validate collection_status
    if sale_data.collection_status not in ["collected", "to_collect"]:
        raise HTTPException(status_code=400, detail="collection_status must be 'collected' or 'to_collect'")

    sale_branch_id = tenant_scope.resolve_branch_id_for_sale(
        current_user, sale_data.branch_id
    )
    if sale_branch_id is not None:
        from .enterprise_models import Branch

        br = tenant_scope.get_scoped(db, Branch, sale_branch_id, current_user)
        if br is None:
            raise HTTPException(status_code=400, detail="Invalid branch")

    sale = Sale(
        cashier_id=current_user.id,
        customer_id=sale_data.customer_id,
        tenant_id=tenant_scope.tenant_id_for_row(current_user),
        branch_id=sale_branch_id,
        shift_id=active_shift.id if active_shift else None,
        subtotal=subtotal,
        discount_total=discount_total,
        total=total,
        notes=sale_data.notes,
        collection_status=sale_data.collection_status,
    )
    db.add(sale)
    db.flush()  # get sale.id

    # Create sale items and update stock
    for item in sale_data.items:
        product = tenant_scope.require_product(db, item.product_id, current_user)
        item_qty = int(item.quantity)
        if item_qty <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be a positive integer")
        
        # Calculate available stock (stock_qty - reserved_qty)
        # Reserved stock is for items bought but not yet collected
        available_stock = product.stock_qty - (product.reserved_qty or 0.0)
        
        # Check if product is out of stock or has insufficient available stock
        if available_stock <= 0:
            raise HTTPException(status_code=400, detail=f"Product '{product.name}' is out of stock (including reserved items)")
        if available_stock < item_qty:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for '{product.name}'. Available: {available_stock}, Requested: {item_qty} (Total stock: {product.stock_qty}, Reserved: {product.reserved_qty or 0})")

        line_total = (Decimal(str(item.unit_price)) * Decimal(str(item.quantity))) - Decimal(str(item.discount))
        sale_item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=item_qty,
            unit_price=item.unit_price,
            discount=item.discount,
            line_total=line_total,
        )
        db.add(sale_item)

        # Always deduct stock immediately when receipt is printed
        # Collection status is just for tracking, not for stock management
        product.stock_qty -= item_qty
        collection_reason = "Sale (to collect)" if sale_data.collection_status == "to_collect" else "Sale (collected)"
        movement = InventoryMovement(
            product_id=product.id,
            change_qty=-item_qty,
            reason=collection_reason,
        )
        db.add(movement)
        
        # Note: Low stock checks moved to background task for performance
    
    # Flush sale items so they're available for accounting
    db.flush()

    # Update shift totals if shift exists
    if active_shift:
        active_shift.total_sales += total
        active_shift.total_transactions += 1
        active_shift.total_discounts += discount_total
        for p in sale_data.payments:
            amount = Decimal(str(p.amount))
            if p.method == "cash":
                active_shift.total_cash += amount
            elif p.method == "mobile_money":
                active_shift.total_mobile_money += amount
            elif p.method == "card":
                active_shift.total_card += amount
            elif p.method == "credit":
                active_shift.total_credit += amount

    # Payments and customer credit
    for p in sale_data.payments:
        payment = Payment(
            sale_id=sale.id,
            method=p.method,
            amount=p.amount,
        )
        db.add(payment)
        if p.method == "credit" and sale_data.customer_id:
            customer = tenant_scope.require_customer(db, sale_data.customer_id, current_user)
            customer.credit_balance += Decimal(str(p.amount))
    
    # Flush payments so they're available for accounting
    db.flush()

    # Post to accounting (if Chart of Accounts is initialized) - BEFORE commit for atomicity
    try:
        if verify_chart_of_accounts(db):
            accounting_engine = AccountingEngine(db)
            accounting_engine.post_sale(sale)
            logging.info(f"Posted sale {sale.id} to accounting")
        else:
            logging.debug("Chart of Accounts not initialized. Skipping accounting post.")
    except Exception as e:
        # If accounting fails, rollback the entire sale (atomicity requirement)
        db.rollback()
        logging.error(f"Error posting sale to accounting: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing sale: {str(e)}"
        )

    try:
        db.commit()
        db.refresh(sale)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # Schedule receipt printing and low-stock checks as background tasks (non-blocking)
    background_tasks.add_task(print_receipt_background, sale.id)
    background_tasks.add_task(check_low_stock_background, sale.id)

    return sale


# ==================== REFUNDS ====================


class RefundItemInput(BaseModel):
    sale_item_id: int
    quantity: int = Field(ge=1)


class RefundCreate(BaseModel):
    sale_id: int
    reason: str = Field(min_length=1, max_length=500)
    refund_method: str
    notes: Optional[str] = None
    full_refund: bool = False
    items: List[RefundItemInput] = Field(default_factory=list)


class RefundItemRead(BaseModel):
    id: int
    sale_item_id: int
    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal

    class Config:
        from_attributes = True


class RefundRead(BaseModel):
    id: int
    sale_id: int
    refund_number: str
    status: str
    refund_type: str
    amount: Decimal
    reason: str
    refund_method: str
    requested_by_id: int
    requested_by_name: str
    approved_by_id: Optional[int]
    approved_by_name: Optional[str]
    rejected_by_id: Optional[int]
    rejection_reason: Optional[str]
    created_at: datetime
    approved_at: Optional[datetime]
    rejected_at: Optional[datetime]
    notes: Optional[str]
    items: List[RefundItemRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class RefundRejectBody(BaseModel):
    rejection_reason: Optional[str] = None


def _refund_to_read(db: Session, refund: Refund, user: User) -> RefundRead:
    from .refund_service import refunded_quantities_for_sale  # noqa: F401

    req = tenant_scope.get_scoped(db, User, refund.requested_by_id, user)
    appr = tenant_scope.get_scoped(db, User, refund.approved_by_id, user) if refund.approved_by_id else None
    items_out = []
    for ri in refund.items:
        product = tenant_scope.get_scoped(db, Product, ri.product_id, user)
        items_out.append(
            RefundItemRead(
                id=ri.id,
                sale_item_id=ri.sale_item_id,
                product_id=ri.product_id,
                product_name=product.name if product else f"Product #{ri.product_id}",
                quantity=ri.quantity,
                unit_price=ri.unit_price,
                line_total=ri.line_total,
            )
        )
    return RefundRead(
        id=refund.id,
        sale_id=refund.sale_id,
        refund_number=refund.refund_number,
        status=refund.status,
        refund_type=refund.refund_type,
        amount=refund.amount,
        reason=refund.reason,
        refund_method=refund.refund_method,
        requested_by_id=refund.requested_by_id,
        requested_by_name=(req.full_name or req.username) if req else "Unknown",
        approved_by_id=refund.approved_by_id,
        approved_by_name=(appr.full_name or appr.username) if appr else None,
        rejected_by_id=refund.rejected_by_id,
        rejection_reason=refund.rejection_reason,
        created_at=refund.created_at,
        approved_at=refund.approved_at,
        rejected_at=refund.rejected_at,
        notes=refund.notes,
        items=items_out,
    )


@app.get("/api/sales/{sale_id}/refund-summary")
async def get_sale_refund_summary(
    sale_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.REQUEST_REFUNDS)),
):
    """Remaining refundable quantities per line for a sale."""
    from .refund_service import sale_refund_summary

    sale = tenant_scope.require_sale(db, sale_id, current_user)
    return sale_refund_summary(db, sale, current_user)


@app.post("/api/refunds", response_model=RefundRead)
async def create_refund_request(
    body: RefundCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.REQUEST_REFUNDS)),
):
    from .refund_service import RefundLineInput, create_refund

    line_inputs = [RefundLineInput(i.sale_item_id, i.quantity) for i in body.items] if body.items else None
    refund = create_refund(
        db,
        current_user,
        sale_id=body.sale_id,
        reason=body.reason,
        refund_method=body.refund_method,
        notes=body.notes,
        full_refund=body.full_refund,
        items=line_inputs,
    )
    return _refund_to_read(db, refund, current_user)


@app.get("/api/refunds", response_model=List[RefundRead])
async def list_refunds(
    status: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    from .permissions import has_permission

    if not has_permission(current_user, Perm.VIEW_REFUNDS) and not has_permission(
        current_user, Perm.REQUEST_REFUNDS
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    query = tenant_scope.filter_refunds(db, current_user)
    if not has_permission(current_user, Perm.VIEW_REFUNDS):
        query = query.filter(Refund.requested_by_id == current_user.id)
    if status:
        query = query.filter(Refund.status == status.strip().lower())
    refunds = query.order_by(Refund.created_at.desc()).offset(skip).limit(limit).all()
    return [_refund_to_read(db, r, current_user) for r in refunds]


@app.get("/api/refunds/{refund_id}", response_model=RefundRead)
async def get_refund(
    refund_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    from .permissions import has_permission

    refund = tenant_scope.require_refund(db, refund_id, current_user)
    if not has_permission(current_user, Perm.VIEW_REFUNDS) and refund.requested_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")
    return _refund_to_read(db, refund, current_user)


@app.post("/api/refunds/{refund_id}/approve", response_model=RefundRead)
async def approve_refund_route(
    refund_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.APPROVE_REFUNDS)),
):
    from .refund_service import approve_refund

    refund = approve_refund(db, current_user, refund_id)
    return _refund_to_read(db, refund, current_user)


@app.post("/api/refunds/{refund_id}/reject", response_model=RefundRead)
async def reject_refund_route(
    refund_id: int,
    body: RefundRejectBody = Body(default=RefundRejectBody()),
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.APPROVE_REFUNDS)),
):
    from .refund_service import reject_refund

    refund = reject_refund(db, current_user, refund_id, body.rejection_reason)
    return _refund_to_read(db, refund, current_user)


@app.put("/api/sales/{sale_id}/mark-collected", response_model=SaleRead)
async def mark_sale_collected(
    sale_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Mark a sale as collected - moves items from reserved to actual stock deduction."""
    require_permission(current_user, Perm.MANAGE_PENDING_COLLECTION)
    sale = tenant_scope.require_sale(db, sale_id, current_user)
    
    if sale.collection_status == "collected":
        raise HTTPException(status_code=400, detail="Sale is already marked as collected")
    
    if sale.collection_status != "to_collect":
        raise HTTPException(status_code=400, detail=f"Sale has invalid collection status: {sale.collection_status}")
    
    # Update sale status only (stock was already deducted when receipt was printed)
    # No need to deduct stock again since it was deducted immediately upon sale creation
    sale.collection_status = "collected"
    db.commit()
    db.refresh(sale)
    
    return sale


@app.get("/api/sales/pending-collection", response_model=List[dict])
async def get_pending_collection_sales(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get all sales with items pending collection (to_collect status)."""
    require_permission(current_user, Perm.MANAGE_PENDING_COLLECTION)
    pending_sales = (
        tenant_scope.filter_sales(db, current_user)
        .filter(Sale.collection_status == "to_collect")
        .order_by(Sale.created_at.desc())
        .all()
    )
    
    result = []
    for sale in pending_sales:
        # Get customer name
        customer_name = None
        if sale.customer_id:
            customer = db.get(Customer, sale.customer_id)
            if customer:
                customer_name = customer.name
        
        # Get cashier name
        cashier = db.get(User, sale.cashier_id)
        cashier_name = cashier.full_name if cashier and cashier.full_name else (cashier.username if cashier else "Unknown")
        
        # Get sale items
        items = []
        for item in sale.items:
            product = db.get(Product, item.product_id)
            items.append({
                "product_id": item.product_id,
                "product_name": product.name if product else "Unknown",
                "quantity": int(item.quantity),
                "unit_price": float(item.unit_price),
                "line_total": float(item.line_total),
            })
        
        result.append({
            "id": sale.id,
            "created_at": sale.created_at.isoformat(),
            "customer_id": sale.customer_id,
            "customer_name": customer_name,
            "cashier_id": sale.cashier_id,
            "cashier_name": cashier_name,
            "total": float(sale.total),
            "items": items,
        })
    
    return result


@app.get("/pending-collection", response_class=HTMLResponse)
async def pending_collection_page(request: Request, db: Session = Depends(get_db)):
    """Pending collection items page."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    store_name = store_settings.store_name if store_settings else "POS System"
    return templates.TemplateResponse("pending_collection.html", {"request": request, "store_name": store_name})


def print_receipt_background(sale_id: int):
    """Background task to print receipt without blocking the API response."""
    db = SessionLocal()
    try:
        # Optimized query with joins to reduce database round trips
        sale = db.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            logging.error(f"Sale {sale_id} not found for receipt printing")
            return
        
        # Query items with product join in one query
        sale_items = db.query(SaleItem, Product).join(
            Product, SaleItem.product_id == Product.id
        ).filter(SaleItem.sale_id == sale_id)
        if getattr(sale, "tenant_id", None) is not None:
            sale_items = sale_items.filter(Product.tenant_id == sale.tenant_id)
        else:
            sale_items = sale_items.filter(Product.tenant_id.is_(None))
        sale_items = sale_items.all()
        
        items_for_print = [
            {
                    "name": product.name,
                "qty": int(item.quantity),
                "unit_price": float(item.unit_price),
                "line_total": float(item.line_total),
            }
            for item, product in sale_items
        ]
        
        # Query payments
        sale_payments = db.query(Payment).filter(Payment.sale_id == sale_id).all()
        payments_for_print = [
            {"method": p.method, "amount": float(p.amount)} for p in sale_payments
        ]
        
        # Get customer name if available
        customer_name = None
        if sale.customer_id:
            customer = db.get(Customer, sale.customer_id)
            if customer and tenant_scope.same_tenant(
                getattr(sale, "tenant_id", None), getattr(customer, "tenant_id", None)
            ):
                customer_name = customer.name
        
        # Get cashier/admin information
        cashier_name = None
        cashier_role = None
        cashier = db.get(User, sale.cashier_id)
        if cashier and tenant_scope.same_tenant(
            getattr(sale, "tenant_id", None), getattr(cashier, "tenant_id", None)
        ):
            cashier_name = cashier.full_name if cashier.full_name else cashier.username
            cashier_role = cashier.role
        
        # Get store settings for this sale's tenant
        if getattr(sale, "tenant_id", None) is not None:
            store_settings = (
                db.query(StoreSettings).filter(StoreSettings.tenant_id == sale.tenant_id).first()
            )
        else:
            store_settings = (
                db.query(StoreSettings).filter(StoreSettings.tenant_id.is_(None)).first()
            )
        if not store_settings:
            store_settings_name = STORE_NAME
            store_settings_phone = STORE_PHONE if STORE_PHONE else None
            store_settings_location = STORE_LOCATION if STORE_LOCATION else None
        else:
            store_settings_name = store_settings.store_name
            store_settings_phone = store_settings.store_phone
            store_settings_location = store_settings.store_location
        
        print_receipt(
            sale_id=sale.id,
            store_name=store_settings_name,
            items=items_for_print,
            subtotal=Decimal(str(sale.subtotal)),
            discount_total=Decimal(str(sale.discount_total)),
            total=Decimal(str(sale.total)),
            payments=payments_for_print,
            customer_name=customer_name,
            cashier_name=cashier_name,
            cashier_role=cashier_role,
            store_phone=store_settings_phone,
            store_location=store_settings_location,
            collection_status=sale.collection_status,
        )
    except Exception as e:
        logging.error(f"Receipt print error for sale #{sale_id}: {e}", exc_info=True)
    finally:
        db.close()


def check_low_stock_background(sale_id: int):
    """Background task to check low stock without blocking the API response."""
    db = SessionLocal()
    try:
        from .notification_service import NotificationService
        notification_service = NotificationService(db)
        
        sale = db.get(Sale, sale_id)
        sale_tid = getattr(sale, "tenant_id", None) if sale else None
        
        # Get all products from this sale
        sale_items = db.query(SaleItem).filter(SaleItem.sale_id == sale_id).all()
        product_ids = [item.product_id for item in sale_items]
        
        # Check low stock for all products in this sale
        for product_id in product_ids:
            product = db.get(Product, product_id)
            if product and tenant_scope.same_tenant(sale_tid, getattr(product, "tenant_id", None)):
                try:
                    notification_service.check_low_stock(product)
                except Exception as e:
                    logging.warning(f"Error checking low stock for product {product_id}: {e}")
        
        # Send batch email with all low-stock products (only once per sale)
        try:
            notification_service.check_all_products_low_stock()
        except Exception as e:
            logging.warning(f"Error sending low stock email: {e}")
    except Exception as e:
        logging.error(f"Error in low stock check background task for sale #{sale_id}: {e}", exc_info=True)
    finally:
        db.close()


class StoreSettingsRead(BaseModel):
    id: int
    store_name: str
    store_phone: Optional[str]
    store_location: Optional[str]
    notification_email: Optional[str]
    low_stock_email_enabled: bool
    default_low_stock_threshold: float
    updated_at: datetime

    class Config:
        from_attributes = True


class StoreSettingsUpdate(BaseModel):
    store_name: str
    store_phone: Optional[str] = None
    store_location: Optional[str] = None
    notification_email: Optional[str] = None
    low_stock_email_enabled: bool = False
    default_low_stock_threshold: float = 10.0


@app.get("/api/store-settings", response_model=StoreSettingsRead)
async def get_store_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get store settings. Creates default if none exists."""
    settings = tenant_scope.filter_store_settings(db, current_user).first()
    if not settings:
        # Create default settings
        settings = StoreSettings(
            store_name=STORE_NAME,
            store_phone=STORE_PHONE if STORE_PHONE else None,
            store_location=STORE_LOCATION if STORE_LOCATION else None,
            tenant_id=tenant_scope.tenant_id_for_row(current_user),
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@app.put("/api/store-settings", response_model=StoreSettingsRead)
async def update_store_settings(
    settings_data: StoreSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Update store settings. Admin only."""
    settings = tenant_scope.filter_store_settings(db, current_user).first()
    if not settings:
        settings = StoreSettings(
            store_name=settings_data.store_name,
            store_phone=settings_data.store_phone,
            store_location=settings_data.store_location,
            tenant_id=tenant_scope.tenant_id_for_row(current_user),
        )
        db.add(settings)
    else:
        settings.store_name = settings_data.store_name
        settings.store_phone = settings_data.store_phone
        settings.store_location = settings_data.store_location
        settings.notification_email = settings_data.notification_email
        settings.low_stock_email_enabled = settings_data.low_stock_email_enabled
        settings.default_low_stock_threshold = settings_data.default_low_stock_threshold
        settings.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(settings)
    return settings


class UserRead(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
    role: str
    branch_id: Optional[int] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str
    full_name: Optional[str] = None
    password: str
    role: str = "cashier"
    branch_id: Optional[int] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    branch_id: Optional[int] = None
    is_active: Optional[bool] = None


@app.get("/api/users", response_model=List[UserRead])
async def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """List all users. Admin only."""
    users = tenant_scope.filter_users(db, current_user).order_by(User.username).all()
    return users


@app.post("/api/users", response_model=UserRead)
async def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Create a new user (cashier, supervisor, or admin). Admin only."""
    existing = tenant_scope.filter_users(db, current_user).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    if user_data.role not in ["admin", "supervisor", "cashier"]:
        raise HTTPException(status_code=400, detail="Role must be 'admin', 'supervisor', or 'cashier'")
    
    if user_data.branch_id is not None:
        from .enterprise_models import Branch

        if tenant_scope.get_scoped(db, Branch, user_data.branch_id, current_user) is None:
            raise HTTPException(status_code=400, detail="Invalid branch")

    db_user = User(
        username=user_data.username,
        full_name=user_data.full_name,
        role=user_data.role,
        branch_id=user_data.branch_id,
        password_hash=auth.get_password_hash(user_data.password),
        is_active=True,
        tenant_id=tenant_scope.tenant_id_for_row(current_user),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.put("/api/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Update a user. Admin only."""
    db_user = tenant_scope.require_user(db, user_id, current_user)
    
    if user_id == current_user.id and user_data.role and user_data.role != current_user.role:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    
    if user_data.username is not None:
        existing = tenant_scope.filter_users(db, current_user).filter(User.username == user_data.username, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        db_user.username = user_data.username
    
    if user_data.full_name is not None:
        db_user.full_name = user_data.full_name
    
    if user_data.password is not None:
        db_user.password_hash = auth.get_password_hash(user_data.password)
    
    if user_data.role is not None:
        if user_data.role not in ["admin", "supervisor", "cashier"]:
            raise HTTPException(status_code=400, detail="Role must be 'admin', 'supervisor', or 'cashier'")
        db_user.role = user_data.role

    if user_data.branch_id is not None:
        from .enterprise_models import Branch

        if user_data.branch_id and tenant_scope.get_scoped(db, Branch, user_data.branch_id, current_user) is None:
            raise HTTPException(status_code=400, detail="Invalid branch")
        db_user.branch_id = user_data.branch_id
    
    if user_data.is_active is not None:
        db_user.is_active = user_data.is_active
    
    db.commit()
    db.refresh(db_user)
    return db_user


@app.delete("/api/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Delete a user. Admin only."""
    db_user = tenant_scope.require_user(db, user_id, current_user)
    
    # Prevent deleting your own account - show clear warning message
    if user_id == current_user.id:
        role_msg = f"admin '{current_user.username}'" if db_user.role == "admin" else f"'{current_user.username}'"
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete your own account. You are currently logged in as {role_msg}. Please create another admin account, log in with it, and then delete this account."
        )
    
    sales_count = tenant_scope.filter_sales(db, current_user).filter(Sale.cashier_id == user_id).count()
    if sales_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete user with existing sales. Deactivate instead.")
    
    db.delete(db_user)
    db.commit()
    return None


class FactoryResetRequest(BaseModel):
    admin_password: str


@app.post("/api/repair-admin")
async def repair_admin_user(db: Session = Depends(get_db)):
    """
    Repair/create default admin user if missing.
    This endpoint works without authentication to allow recovery.
    """
    try:
        # Check if admin user exists
        admin = db.query(User).filter(User.username == "admin").first()
        
        if admin:
            # Admin exists, verify password works
            if auth.verify_password("admin", admin.password_hash):
                logging.info("Admin user exists and password is correct")
                return {"ok": True, "message": "Admin user already exists with correct password", "username": "admin"}
            else:
                # Reset password
                admin.password_hash = auth.get_password_hash("admin")
                admin.is_active = True
                db.commit()
                logging.info("Admin user password reset to 'admin'")
                return {"ok": True, "message": "Admin user password reset to 'admin'", "username": "admin"}
        else:
            # Create admin user
            admin_password_hash = auth.get_password_hash("admin")
            new_admin = User(
                username="admin",
                full_name="Administrator",
                role="admin",
                password_hash=admin_password_hash,
                is_active=True,
            )
            db.add(new_admin)
            db.commit()
            db.refresh(new_admin)
            
            # Verify creation
            if auth.verify_password("admin", new_admin.password_hash):
                logging.info("Created admin user with password 'admin'")
                return {"ok": True, "message": "Admin user created successfully", "username": "admin"}
            else:
                logging.error("Failed to verify password for newly created admin user")
                return {"ok": False, "message": "Admin user created but password verification failed"}
    except Exception as e:
        logging.error(f"Error repairing admin user: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to repair admin user: {str(e)}"
        )


@app.post("/api/factory-reset")
async def factory_reset(
    request: FactoryResetRequest,
    current_user: User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    Factory reset: Delete all data and reset database to factory defaults.
    Requires admin authentication and password confirmation.
    """
    # Verify admin password
    if not auth.verify_password(request.admin_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin password"
        )
    
    try:
        # Declare global engine at the start of the function
        global engine
        
        # Close all database connections
        db.close()
        engine.dispose()
        
        # Get database file path from DATABASE_URL
        # DATABASE_URL format: "sqlite:///path/to/pos.db"
        db_path_str = DATABASE_URL.replace("sqlite:///", "")
        db_path = Path(db_path_str)
        
        # Delete the database file if it exists
        if db_path.exists():
            os.remove(db_path)
            logging.info(f"Deleted database file: {db_path}")
        
        # Recreate the engine and database
        from sqlalchemy import create_engine as create_sqlalchemy_engine
        from sqlalchemy.orm import sessionmaker
        from . import database
        
        # Create new engine
        new_engine = create_sqlalchemy_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        
        # Update the database module's engine and SessionLocal so all future DB operations use the new engine
        database.engine = new_engine
        database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=new_engine)
        
        # Also update the local reference for consistency
        engine = new_engine
        
        # Recreate all tables
        Base.metadata.create_all(bind=new_engine)
        logging.info("Recreated database tables")
        
        # Initialize with default admin and store settings
        # Note: create_admin_if_missing requires interactive input, so we'll create a default admin directly
        new_db = database.SessionLocal()
        try:
            # Create default admin user (username: admin, password: admin)
            # Since we just deleted the database, there should be no existing admin, but we check anyway
            existing_admin = new_db.query(User).filter(User.role == "admin").first()
            if existing_admin:
                logging.warning("Admin user already exists after factory reset (should not happen), deleting it")
                new_db.delete(existing_admin)
                new_db.flush()
            
            # Create the default admin user
            admin_password_hash = auth.get_password_hash("admin")
            default_admin = User(
                username="admin",
                full_name="Administrator",
                role="admin",
                password_hash=admin_password_hash,
                is_active=True,
            )
            new_db.add(default_admin)
            new_db.flush()  # Flush to ensure the user is in the database
            
            # Verify the admin was created
            created_admin = new_db.query(User).filter(User.username == "admin").first()
            if created_admin:
                logging.info(f"Successfully created default admin user: username=admin, is_active={created_admin.is_active}, role={created_admin.role}")
                # Test password verification
                if auth.verify_password("admin", created_admin.password_hash):
                    logging.info("Password verification test passed for default admin user")
                else:
                    logging.error("WARNING: Password verification test FAILED for default admin user")
            else:
                logging.error("ERROR: Admin user was not found after creation")
            
            # Create store settings
            existing_settings = tenant_scope.first_store_settings_for_tenant(new_db, None)
            if existing_settings:
                logging.warning("Store settings already exist after factory reset (should not happen), deleting them")
                new_db.delete(existing_settings)
                new_db.flush()
            
            settings = StoreSettings(
                store_name=STORE_NAME,
                store_phone=STORE_PHONE if STORE_PHONE else None,
                store_location=STORE_LOCATION if STORE_LOCATION else None,
            )
            new_db.add(settings)
            logging.info("Created default store settings")
            
            new_db.commit()
            logging.info("Committed default admin user and store settings to database")
        finally:
            new_db.close()
        
        return {
            "ok": True,
            "message": "Factory reset completed successfully. Please log in with the default admin credentials."
        }
    except Exception as e:
        logging.error(f"Factory reset failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Factory reset failed: {str(e)}"
        )


class ReportSummary(BaseModel):
    from_date: date
    to_date: date
    sales_count: int
    gross_sales: Decimal
    discounts: Decimal
    net_sales: Decimal
    profit: Decimal
    total_stock_value: Decimal
    expected_profit: Decimal


@app.get("/api/reports/summary", response_model=ReportSummary)
async def report_summary(
    from_date: date,
    to_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_REPORTS)),
):
    sales_q = db.query(
        func.count(Sale.id),
        func.coalesce(func.sum(Sale.subtotal), 0),
        func.coalesce(func.sum(Sale.discount_total), 0),
        func.coalesce(func.sum(Sale.total), 0),
    ).filter(
        Sale.created_at >= datetime.combine(from_date, datetime.min.time()),
        Sale.created_at <= datetime.combine(to_date, datetime.max.time()),
    )
    if current_user.tenant_id is None:
        sales_q = sales_q.filter(Sale.tenant_id.is_(None))
    else:
        sales_q = sales_q.filter(Sale.tenant_id == current_user.tenant_id)
    sales_count, gross_sales, discounts, net_sales = sales_q.one()

    # Profit: sum over (line_total - cost * qty)
    profit_q = (
        db.query(
            func.coalesce(
                func.sum(
                    SaleItem.line_total
                    - (SaleItem.quantity * Product.cost_price)
                ),
                0,
            )
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .join(Product, SaleItem.product_id == Product.id)
        .filter(
            Sale.created_at >= datetime.combine(from_date, datetime.min.time()),
            Sale.created_at <= datetime.combine(to_date, datetime.max.time()),
        )
    )
    if current_user.tenant_id is None:
        profit_q = profit_q.filter(Sale.tenant_id.is_(None), Product.tenant_id.is_(None))
    else:
        profit_q = profit_q.filter(
            Sale.tenant_id == current_user.tenant_id,
            Product.tenant_id == current_user.tenant_id,
        )
    (profit,) = profit_q.one()
    
    # Calculate total stock value (sum of stock_qty * cost_price for all products with stock > 0)
    # Use Python calculation instead of SQL aggregation to handle Numeric types correctly
    products_with_stock = (
        tenant_scope.filter_products(db, current_user)
        .filter(
            Product.stock_qty > 0,
            Product.is_active == True,  # noqa: E712
        )
        .all()
    )
    
    total_stock_value = Decimal("0.00")
    expected_profit = Decimal("0.00")
    
    for product in products_with_stock:
        stock_qty = Decimal(str(product.stock_qty))
        cost_price = Decimal(str(product.cost_price))
        selling_price = Decimal(str(product.selling_price))
        
        # Add to total stock value (at cost)
        total_stock_value += stock_qty * cost_price
        
        # Add to expected profit (selling_price - cost_price) * stock_qty
        expected_profit += stock_qty * (selling_price - cost_price)
    
    # Deduct total withdrawals (daily expenses + company assets) from expected profit
    total_withdrawals = Decimal("0.00")
    for withdrawal in tenant_scope.filter_withdrawals(db, current_user).all():
        total_withdrawals += Decimal(str(withdrawal.amount))
    
    # Subtract withdrawals from expected profit
    expected_profit -= total_withdrawals
    
    return ReportSummary(
        from_date=from_date,
        to_date=to_date,
        sales_count=sales_count,
        gross_sales=gross_sales,
        discounts=discounts,
        net_sales=net_sales,
        profit=profit,
        total_stock_value=total_stock_value,
        expected_profit=expected_profit,
    )


# ==================== SALES ANALYTICS ====================

class ProductSalesStats(BaseModel):
    product_id: int
    product_name: str
    barcode: Optional[str]
    total_quantity_sold: int
    total_revenue: Decimal
    total_profit: Decimal
    sale_count: int

    class Config:
        from_attributes = True


class TopProductResponse(BaseModel):
    product_id: int
    product_name: str
    barcode: Optional[str]
    total_quantity_sold: int
    total_revenue: Decimal
    total_profit: Decimal


class ZeroSalesProduct(BaseModel):
    product_id: int
    product_name: str
    barcode: Optional[str]
    stock_qty: float
    selling_price: Decimal
    last_sale_date: Optional[datetime] = None


@app.get("/api/analytics/top-selling", response_model=TopProductResponse)
async def get_top_selling_product(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_REPORTS)),
):
    """Get the top-selling product by quantity sold in the specified period."""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    result = (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.sum(SaleItem.quantity).label('total_quantity'),
            func.sum(SaleItem.line_total).label('total_revenue'),
            func.sum(SaleItem.line_total - (SaleItem.quantity * Product.cost_price)).label('total_profit')
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.created_at >= cutoff_date)
        .filter(
            and_(
                tenant_scope.sale_tenant_match(current_user),
                tenant_scope.product_tenant_match(current_user),
            )
        )
        .filter(Product.is_active == True)
        .group_by(Product.id, Product.name, Product.barcode)
        .order_by(func.sum(SaleItem.quantity).desc())
        .first()
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="No sales found in the specified period")
    
    return TopProductResponse(
        product_id=result.id,
        product_name=result.name,
        barcode=result.barcode,
        total_quantity_sold=int(result.total_quantity or 0),
        total_revenue=Decimal(str(result.total_revenue or 0)),
        total_profit=Decimal(str(result.total_profit or 0))
    )


@app.get("/api/analytics/least-selling", response_model=TopProductResponse)
async def get_least_selling_product(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_REPORTS)),
):
    """Get the least-selling product by quantity sold in the specified period (among products with sales)."""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    result = (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.sum(SaleItem.quantity).label('total_quantity'),
            func.sum(SaleItem.line_total).label('total_revenue'),
            func.sum(SaleItem.line_total - (SaleItem.quantity * Product.cost_price)).label('total_profit')
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.created_at >= cutoff_date)
        .filter(
            and_(
                tenant_scope.sale_tenant_match(current_user),
                tenant_scope.product_tenant_match(current_user),
            )
        )
        .filter(Product.is_active == True)
        .group_by(Product.id, Product.name, Product.barcode)
        .order_by(func.sum(SaleItem.quantity).asc())
        .first()
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="No sales found in the specified period")
    
    return TopProductResponse(
        product_id=result.id,
        product_name=result.name,
        barcode=result.barcode,
        total_quantity_sold=int(result.total_quantity or 0),
        total_revenue=Decimal(str(result.total_revenue or 0)),
        total_profit=Decimal(str(result.total_profit or 0))
    )


@app.get("/api/analytics/revenue-per-product", response_model=List[ProductSalesStats])
async def get_revenue_per_product(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of products to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_REPORTS)),
):
    """Get revenue statistics per product, sorted by revenue descending."""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    results = (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.sum(SaleItem.quantity).label('total_quantity'),
            func.sum(SaleItem.line_total).label('total_revenue'),
            func.sum(SaleItem.line_total - (SaleItem.quantity * Product.cost_price)).label('total_profit'),
            func.count(Sale.id.distinct()).label('sale_count')
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.created_at >= cutoff_date)
        .filter(
            and_(
                tenant_scope.sale_tenant_match(current_user),
                tenant_scope.product_tenant_match(current_user),
            )
        )
        .filter(Product.is_active == True)
        .group_by(Product.id, Product.name, Product.barcode)
        .order_by(func.sum(SaleItem.line_total).desc())
        .limit(limit)
        .all()
    )
    
    return [
        ProductSalesStats(
            product_id=r.id,
            product_name=r.name,
            barcode=r.barcode,
            total_quantity_sold=int(r.total_quantity or 0),
            total_revenue=Decimal(str(r.total_revenue or 0)),
            total_profit=Decimal(str(r.total_profit or 0)),
            sale_count=int(r.sale_count or 0)
        )
        for r in results
    ]


@app.get("/api/analytics/zero-sales", response_model=List[ZeroSalesProduct])
async def get_zero_sales_products(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to check"),
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_REPORTS)),
):
    """Get products with zero sales in the last N days."""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Get all active products
    all_products = tenant_scope.filter_products(db, current_user).filter(Product.is_active == True).all()  # noqa: E712

    # Get products that have sales in the period
    products_with_sales = (
        tenant_scope.filter_products(db, current_user)
        .with_entities(Product.id)
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.created_at >= cutoff_date,
            tenant_scope.sale_tenant_match(current_user),
        )
        .distinct()
        .all()
    )
    
    sold_product_ids = {p.id for p in products_with_sales}
    
    # Get products with zero sales
    zero_sales_products = [p for p in all_products if p.id not in sold_product_ids]
    
    # For each product, get the last sale date (if any, outside the period)
    result = []
    for product in zero_sales_products:
        last_sale = (
            db.query(Sale.created_at)
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .filter(
                SaleItem.product_id == product.id,
                tenant_scope.sale_tenant_match(current_user),
            )
            .order_by(Sale.created_at.desc())
            .first()
        )
        
        result.append(ZeroSalesProduct(
            product_id=product.id,
            product_name=product.name,
            barcode=product.barcode,
            stock_qty=product.stock_qty,
            selling_price=product.selling_price,
            last_sale_date=last_sale[0] if last_sale else None
        ))
    
    return result


@app.get("/api/analytics/dashboard", response_model=dict)
async def get_analytics_dashboard(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_REPORTS)),
):
    """Get comprehensive analytics dashboard data."""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Top selling product
    top_product = (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.sum(SaleItem.quantity).label('total_quantity'),
            func.sum(SaleItem.line_total).label('total_revenue')
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.created_at >= cutoff_date)
        .filter(
            and_(
                tenant_scope.sale_tenant_match(current_user),
                tenant_scope.product_tenant_match(current_user),
            )
        )
        .filter(Product.is_active == True)
        .group_by(Product.id, Product.name, Product.barcode)
        .order_by(func.sum(SaleItem.quantity).desc())
        .first()
    )
    
    # Least selling product (with sales)
    least_product = (
        db.query(
            Product.id,
            Product.name,
            Product.barcode,
            func.sum(SaleItem.quantity).label('total_quantity'),
            func.sum(SaleItem.line_total).label('total_revenue')
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.created_at >= cutoff_date)
        .filter(
            and_(
                tenant_scope.sale_tenant_match(current_user),
                tenant_scope.product_tenant_match(current_user),
            )
        )
        .filter(Product.is_active == True)
        .group_by(Product.id, Product.name, Product.barcode)
        .order_by(func.sum(SaleItem.quantity).asc())
        .first()
    )
    
    # Total revenue
    total_revenue = (
        db.query(func.coalesce(func.sum(SaleItem.line_total), 0))
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.created_at >= cutoff_date,
            tenant_scope.sale_tenant_match(current_user),
        )
        .scalar()
    )
    
    # Total products sold
    total_products_sold = (
        db.query(func.count(func.distinct(SaleItem.product_id)))
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.created_at >= cutoff_date,
            tenant_scope.sale_tenant_match(current_user),
        )
        .scalar()
    )
    
    # Total active products
    total_active_products = (
        tenant_scope.filter_products(db, current_user)
        .filter(Product.is_active == True)  # noqa: E712
        .with_entities(func.count(Product.id))
        .scalar()
    )
    
    # Products with zero sales
    products_with_sales = (
        db.query(func.count(func.distinct(Product.id)))
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.created_at >= cutoff_date,
            Product.is_active == True,  # noqa: E712
            tenant_scope.sale_tenant_match(current_user),
            tenant_scope.product_tenant_match(current_user),
        )
        .scalar()
    )
    
    zero_sales_count = total_active_products - (products_with_sales or 0)
    
    return {
        "period_days": days,
        "top_selling": {
            "product_id": top_product.id if top_product else None,
            "product_name": top_product.name if top_product else None,
            "barcode": top_product.barcode if top_product else None,
            "quantity_sold": int(top_product.total_quantity or 0) if top_product else 0,
            "revenue": float(top_product.total_revenue or 0) if top_product else 0.0
        },
        "least_selling": {
            "product_id": least_product.id if least_product else None,
            "product_name": least_product.name if least_product else None,
            "barcode": least_product.barcode if least_product else None,
            "quantity_sold": int(least_product.total_quantity or 0) if least_product else 0,
            "revenue": float(least_product.total_revenue or 0) if least_product else 0.0
        },
        "summary": {
            "total_revenue": float(total_revenue or 0),
            "total_products_sold": total_products_sold or 0,
            "total_active_products": total_active_products or 0,
            "zero_sales_count": zero_sales_count
        }
    }


# ==================== AI BUSINESS INTELLIGENCE ====================

@app.get("/api/ai/analyze")
async def get_ai_analysis(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    comparison_days: int = Query(default=30, ge=1, le=365, description="Number of days for comparison period"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """
    Get AI-powered business analysis and insights.
    Analyzes sales data and provides professional accounting advice.
    """
    if not AI_SERVICE_AVAILABLE or not ai_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is not available. Please check server logs for import errors."
        )
    try:
        result = ai_service.analyze_sales_data(
            db=db,
            days=days,
            comparison_days=comparison_days,
            user=current_user,
        )
        return result
    except Exception as e:
        logging.error(f"Error in AI analysis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating AI analysis: {str(e)}"
        )


@app.get("/api/ai/status")
async def get_ai_status(
    current_user: User = Depends(auth.get_current_active_user),
):
    """
    Business Sage is always available: we return available=true when the AI module is loaded.
    Chat uses Ollama when running, otherwise instant/reasoned answers from your data.
    """
    if not AI_SERVICE_AVAILABLE or not ai_service:
        return {
            "ollama_available": False,
            "model": None,
            "base_url": None,
            "error": "AI service module not loaded. Check server logs for import errors."
        }
    
    import asyncio
    
    # Business Sage is always available from the app (Ollama or reasoned fallback)
    # Use detailed check so we can show the user why connection failed
    try:
        is_ollama_running, reason = await asyncio.wait_for(
            asyncio.to_thread(ai_service.check_ollama_with_reason, retries=2),
            timeout=6.0
        )
    except asyncio.TimeoutError:
        is_ollama_running = False
        reason = "Status check timed out (Ollama may be slow). Try refreshing."
    except Exception as e:
        is_ollama_running = False
        reason = str(e)
    
    result = {
        "ollama_available": is_ollama_running,
        "model": getattr(ai_service, "model", None) if is_ollama_running else None,
        "base_url": OLLAMA_BASE_URL if is_ollama_running else None,
    }
    if not is_ollama_running:
        result["error"] = reason
    else:
        result["message"] = reason
    return result


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, description="User's chat message")
    days: int = Field(default=30, ge=1, le=365, description="Number of days of sales data to include in context")


@app.post("/api/ai/chat")
async def chat_with_ai(
    chat_data: ChatMessage,
    current_user: User = Depends(auth.get_current_active_user),
):
    """
    Chat with AI about sales, marketing, and business.
    The AI will have access to recent sales data for context.
    Runs in a thread so the event loop stays responsive and proxy timeouts
    are less likely to hit (instant answers return immediately).
    """
    if not AI_SERVICE_AVAILABLE or not ai_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is not available. Please check server logs for import errors."
        )
    import asyncio
    logging.info("AI chat request: message=%r days=%s", chat_data.message[:80] if chat_data.message else "", chat_data.days)

    def _run_chat(message: str, days: int, user_id: int):
        """Run sync AI chat in a thread with its own DB session (thread-safe)."""
        db = SessionLocal()
        try:
            user = db.get(User, user_id)
            if not user:
                return None
            return ai_service.chat_with_sales_context(
                db=db, user_message=message, days=days, user=user
            )
        finally:
            db.close()

    try:
        response = await asyncio.to_thread(
            _run_chat, chat_data.message, chat_data.days, current_user.id
        )
        
        # Response should never be None for "what should i do" - it should have fallback_advice
        # But if it is None or empty, provide a helpful message
        if not response or not response.strip():
            # Ollama didn't respond in time or returned empty; give a short helpful message
            try:
                from datetime import datetime, timedelta

                from app.models import Sale, Withdrawal

                fallback_db = SessionLocal()
                try:
                    start_date = datetime.now() - timedelta(days=chat_data.days)
                    rev_q = fallback_db.query(func.sum(Sale.total)).filter(Sale.created_at >= start_date)
                    rev_q = rev_q.filter(tenant_scope.sale_tenant_match(current_user))
                    revenue_data = rev_q.first()
                    revenue = float(revenue_data[0] or 0)
                    wdq = fallback_db.query(func.sum(Withdrawal.amount)).filter(
                        Withdrawal.created_at >= start_date
                    )
                    wdq = wdq.filter(tenant_scope.withdrawal_tenant_match(current_user))
                    withdrawals_data = wdq.first()
                    expenses = float(withdrawals_data[0] or 0)
                    profit = revenue - expenses
                    profit_margin = (profit / revenue * 100) if revenue > 0 else 0.0
                    return {
                        "success": True,
                        "response": (
                            f"The AI didn't respond in time. Your last {chat_data.days} days: revenue ${revenue:,.2f}, "
                            f"profit margin {profit_margin:.1f}%. Try asking again in a moment or rephrase your question; "
                            f"Ollama can be slow on this device when thinking."
                        )
                    }
                finally:
                    fallback_db.close()
            except Exception:
                return {
                    "success": True,
                    "response": "The AI didn't respond in time. Try again in a moment or rephrase your question; Ollama can be slow on this device."
                }
        
        return {
            "success": True,
            "response": response
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error in AI chat: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating AI response: {str(e)}"
        )


# ==================== ACCOUNTING REPORTS ====================

@app.get("/api/accounting/trial-balance")
async def get_trial_balance(
    as_of_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    period_name: Optional[str] = Query(None, description="Period name (e.g., '2024-01')"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get Trial Balance report."""
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized. Please initialize accounting system."
        )
    
    try:
        reports = AccountingReports(db)
        as_of = None
        if as_of_date:
            as_of = datetime.fromisoformat(as_of_date)
        
        trial_balance = reports.get_trial_balance(as_of_date=as_of, period_name=period_name)
        return {"success": True, "data": trial_balance}
    except Exception as e:
        logging.error(f"Error generating trial balance: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating trial balance: {str(e)}"
        )


@app.get("/api/accounting/profit-loss")
async def get_profit_loss(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get Profit & Loss Statement."""
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized. Please initialize accounting system."
        )
    
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        
        reports = AccountingReports(db)
        pnl = reports.get_profit_and_loss(start_date=start, end_date=end)
        return {"success": True, "data": pnl}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        logging.error(f"Error generating P&L: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating profit & loss: {str(e)}"
        )


@app.get("/api/accounting/balance-sheet")
async def get_balance_sheet(
    as_of_date: str = Query(..., description="Date in YYYY-MM-DD format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get Balance Sheet."""
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized. Please initialize accounting system."
        )
    
    try:
        as_of = datetime.fromisoformat(as_of_date)
        reports = AccountingReports(db)
        balance_sheet = reports.get_balance_sheet(as_of_date=as_of)
        return {"success": True, "data": balance_sheet}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        logging.error(f"Error generating balance sheet: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating balance sheet: {str(e)}"
        )


@app.get("/api/accounting/vat-report")
async def get_vat_report(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get VAT Report for ZIMRA compliance."""
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized. Please initialize accounting system."
        )
    
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        
        reports = AccountingReports(db)
        vat_report = reports.get_vat_report(start_date=start, end_date=end)
        return {"success": True, "data": vat_report}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        logging.error(f"Error generating VAT report: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating VAT report: {str(e)}"
        )


@app.get("/api/accounting/general-ledger")
async def get_general_ledger(
    account_code: str = Query(..., description="Account code (e.g., '1000')"),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get General Ledger for a specific account."""
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized. Please initialize accounting system."
        )
    
    try:
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
        
        reports = AccountingReports(db)
        ledger = reports.get_general_ledger(
            account_code=account_code,
            start_date=start,
            end_date=end
        )
        return {"success": True, "data": ledger}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Error generating general ledger: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating general ledger: {str(e)}"
        )


# ==================== FIXED ASSETS ====================

class FixedAssetCreate(BaseModel):
    asset_code: str
    name: str
    purchase_date: str  # YYYY-MM-DD
    purchase_cost: Decimal
    useful_life_months: int
    payment_account_code: Optional[str] = "1000"


@app.post("/api/accounting/fixed-assets")
async def create_fixed_asset(
    asset_data: FixedAssetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Create a fixed asset and post purchase transaction."""
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized."
        )
    
    try:
        purchase_date = datetime.fromisoformat(asset_data.purchase_date)
        engine = AccountingEngine(db)
        asset, journal_entry = engine.create_fixed_asset(
            asset_code=asset_data.asset_code,
            name=asset_data.name,
            purchase_date=purchase_date,
            purchase_cost=asset_data.purchase_cost,
            useful_life_months=asset_data.useful_life_months,
            created_by=current_user.id,
            payment_account_code=asset_data.payment_account_code or "1000"
        )
        db.commit()
        
        return {
            "success": True,
            "asset": {
                "id": asset.id,
                "asset_code": asset.asset_code,
                "name": asset.name,
                "purchase_cost": float(asset.purchase_cost),
                "current_value": float(asset.current_value)
            },
            "journal_entry_number": journal_entry.entry_number
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logging.error(f"Error creating fixed asset: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating fixed asset: {str(e)}"
        )


@app.post("/api/accounting/fixed-assets/{asset_id}/depreciation")
async def post_asset_depreciation(
    asset_id: int,
    period: str = Query(..., description="Period in YYYY-MM format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Post monthly depreciation for a fixed asset."""
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized."
        )
    
    if not tenant_scope.filter_fixed_assets(db, current_user).filter(FixedAsset.id == asset_id).first():
        raise HTTPException(status_code=404, detail="Asset not found")
    
    try:
        engine = AccountingEngine(db)
        schedule, journal_entry = engine.post_depreciation(
            asset_id=asset_id,
            period=period,
            created_by=current_user.id
        )
        db.commit()
        
        return {
            "success": True,
            "depreciation_amount": float(schedule.depreciation_amount),
            "journal_entry_number": journal_entry.entry_number
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logging.error(f"Error posting depreciation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error posting depreciation: {str(e)}"
        )


@app.get("/api/accounting/fixed-assets")
async def list_fixed_assets(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """List all fixed assets."""
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized."
        )
    
    assets = tenant_scope.filter_fixed_assets(db, current_user).order_by(FixedAsset.created_at.desc()).all()
    return {
        "success": True,
        "assets": [
            {
                "id": a.id,
                "asset_code": a.asset_code,
                "name": a.name,
                "purchase_date": a.purchase_date.isoformat(),
                "purchase_cost": float(a.purchase_cost),
                "useful_life_months": a.useful_life_months,
                "accumulated_depreciation": float(a.accumulated_depreciation),
                "current_value": float(a.current_value),
                "is_disposed": a.is_disposed
            }
            for a in assets
        ]
    }


# ==================== ACCOUNTING BACKFILL ====================

@app.post("/api/accounting/backfill")
async def backfill_accounting(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """
    Backfill journal entries for historical sales and layby payments.
    This will create accounting entries for all transactions that occurred
    before the accounting system was enabled.
    """
    if not verify_chart_of_accounts(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart of Accounts not initialized. Please initialize accounting system first."
        )
    
    try:
        stats = backfill_historical_transactions(db, created_by=current_user.id)
        return {
            "success": True,
            "message": "Backfill completed",
            "stats": stats
        }
    except Exception as e:
        logging.error(f"Error during accounting backfill: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during backfill: {str(e)}"
        )


# ==================== GOOGLE SHEETS BACKUP ====================

class BackupConfigUpdate(BaseModel):
    enabled: bool
    web_app_url: str
    api_key: str = ""


@app.get("/api/backup/config")
async def get_backup_config(
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Get backup configuration."""
    backup_service = get_backup_service()
    return backup_service.config


@app.put("/api/backup/config")
async def update_backup_config(
    config: BackupConfigUpdate,
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Update backup configuration."""
    # Reset the global backup service instance to force reload
    import app.backup_service as backup_module
    backup_module._backup_service = None
    
    # Get fresh instance and update config
    backup_service = get_backup_service()
    backup_service.config = config.dict()
    backup_service._save_config()
    # Reinitialize client with new config
    backup_service._initialize_client()
    return {"ok": True, "message": "Backup configuration updated"}


@app.post("/api/backup/sync-all")
async def sync_all_to_backup(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Manually sync all products to Google Sheets."""
    backup_service = get_backup_service()
    result = backup_service.sync_all_products(db)
    return result


@app.post("/api/backup/process-queue")
async def process_backup_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Process offline changes queue."""
    backup_service = get_backup_service()
    result = backup_service.process_offline_queue(db)
    return result


@app.post("/api/backup/import")
async def import_from_backup(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Import products from Google Sheets CSV (restore after factory reset)."""
    # For Apps Script method, user needs to download CSV from Google Sheets and use the import feature
    return {
        "success": False,
        "message": "Please download CSV from Google Sheets and use the 'Import Inventory' feature instead"
    }


@app.get("/api/backup/status")
async def get_backup_status(
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Get backup service status."""
    backup_service = get_backup_service()
    import socket
    has_internet = False
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        has_internet = True
    except OSError:
        pass
    
    queue = backup_service._load_offline_queue()
    
    return {
        "enabled": backup_service.is_enabled(),
        "has_internet": has_internet,
        "pending_changes": len(queue),
        "configured": backup_service.config.get("enabled", False) and bool(backup_service.config.get("web_app_url"))
    }


# ==================== LAYBY MANAGEMENT ====================

class LaybyCustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    layby_item_name: Optional[str] = None


class LaybyCustomerRead(LaybyCustomerCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    active_items: Optional[str] = None  # Comma-separated list of active layby items

    class Config:
        from_attributes = True


class LaybyTransactionCreate(BaseModel):
    customer_id: int
    product_id: int
    quantity: int = 1
    notes: Optional[str] = None


class LaybyTransactionRead(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    status: str
    created_at: datetime
    completed_at: Optional[datetime]
    notes: Optional[str]

    class Config:
        from_attributes = True


class LaybyPaymentCreate(BaseModel):
    transaction_id: int
    amount: Decimal
    payment_method: str
    notes: Optional[str] = None


class LaybyPaymentRead(BaseModel):
    id: int
    transaction_id: int
    amount: Decimal
    payment_method: str
    cashier_id: int
    cashier_name: str
    receipt_number: Optional[str]
    created_at: datetime
    notes: Optional[str]

    class Config:
        from_attributes = True


@app.get("/layby", response_class=HTMLResponse)
async def layby_page(request: Request, db: Session = Depends(get_db)):
    """Layby management page."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("layby.html", {"request": request, "store_name": store_name})


@app.get("/debts/outstanding", response_class=HTMLResponse)
async def outstanding_debts_page(request: Request, db: Session = Depends(get_db)):
    """Outstanding debts page."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("outstanding_debts.html", {"request": request, "store_name": store_name})


@app.get("/withdrawals/history", response_class=HTMLResponse)
async def withdrawal_history_page(request: Request, db: Session = Depends(get_db)):
    """Withdrawal history page."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("withdrawal_history.html", {"request": request, "store_name": store_name})


@app.get("/refunds", response_class=HTMLResponse)
async def refunds_page(request: Request, db: Session = Depends(get_db)):
    """Refund management — request, track, and approve refunds."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("refunds.html", {"request": request, "store_name": store_name})


@app.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request, db: Session = Depends(get_db)):
    """Subscription management & Paynow / EcoCash billing."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    store_name = store_settings.store_name.upper() if store_settings else STORE_NAME.upper()
    return templates.TemplateResponse("billing.html", {"request": request, "store_name": store_name})


@app.get("/enterprise", response_class=HTMLResponse)
async def enterprise_hub_page(request: Request, db: Session = Depends(get_db)):
    """Enterprise inventory: suppliers, purchasing, branches, audit."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    store_name = store_settings.store_name.upper() if store_settings else STORE_NAME.upper()
    return templates.TemplateResponse("enterprise.html", {"request": request, "store_name": store_name})


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, db: Session = Depends(get_db)):
    """Sales Analytics dashboard page."""
    store_settings = tenant_scope.first_store_settings_for_tenant(db, None)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    return templates.TemplateResponse("analytics.html", {"request": request, "store_name": store_name})


@app.get("/layby/customer/{customer_id}", response_class=HTMLResponse)
async def customer_history_page(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Customer payment history page."""
    customer = tenant_scope.get_scoped(db, LaybyCustomer, customer_id, current_user)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    store_settings = tenant_scope.filter_store_settings(db, current_user).first()
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    
    return templates.TemplateResponse(
        "customer_history.html",
        {
            "request": request,
            "store_name": store_name,
            "customer_id": customer_id,
            "customer_name": customer.name,
        },
    )


@app.get("/layby/transaction/{transaction_id}/payments", response_class=HTMLResponse)
async def transaction_payment_history_page(
    transaction_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Transaction payment history page."""
    # Verify transaction exists (no auth required for HTML page, API endpoints handle auth)
    transaction = db.get(LaybyTransaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    cust = db.get(LaybyCustomer, transaction.customer_id)
    tid = getattr(cust, "tenant_id", None) if cust else None
    store_settings = tenant_scope.first_store_settings_for_tenant(db, tid)
    if store_settings:
        store_name = store_settings.store_name.upper()
    else:
        store_name = STORE_NAME.upper()
    
    return templates.TemplateResponse(
        "transaction_payment_history.html",
        {
            "request": request,
            "store_name": store_name,
            "transaction_id": transaction_id,
        },
    )


@app.get("/api/layby/customers", response_model=List[LaybyCustomerRead])
async def list_layby_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """List all layby customers with their active layby items."""
    customers = tenant_scope.filter_layby_customers(db, current_user).order_by(LaybyCustomer.name).all()
    result = []
    for customer in customers:
        # Get active layby transactions for this customer
        active_transactions = db.query(LaybyTransaction).filter(
            LaybyTransaction.customer_id == customer.id,
            LaybyTransaction.status == "active"
        ).all()
        
        # Build list of active items
        active_items = []
        for txn in active_transactions:
            active_items.append(f"{txn.product_name} (x{txn.quantity})")
        
        customer_dict = {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
            "address": customer.address,
            "layby_item_name": customer.layby_item_name,
            "created_at": customer.created_at,
            "updated_at": customer.updated_at,
            "active_items": ", ".join(active_items) if active_items else None,
        }
        result.append(LaybyCustomerRead(**customer_dict))
    return result


@app.post("/api/layby/customers", response_model=LaybyCustomerRead)
async def create_layby_customer(
    customer: LaybyCustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Create a new layby customer."""
    db_customer = LaybyCustomer(
        **customer.dict(),
        tenant_id=tenant_scope.tenant_id_for_row(current_user),
    )
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    
    # Return with active_items
    active_transactions = db.query(LaybyTransaction).filter(
        LaybyTransaction.customer_id == db_customer.id,
        LaybyTransaction.status == "active"
    ).all()
    active_items = ", ".join([f"{txn.product_name} (x{txn.quantity})" for txn in active_transactions]) if active_transactions else None
    
    customer_dict = {
        "id": db_customer.id,
        "name": db_customer.name,
        "phone": db_customer.phone,
        "email": db_customer.email,
        "address": db_customer.address,
        "layby_item_name": db_customer.layby_item_name,
        "created_at": db_customer.created_at,
        "updated_at": db_customer.updated_at,
        "active_items": active_items,
    }
    return LaybyCustomerRead(**customer_dict)


@app.put("/api/layby/customers/{customer_id}", response_model=LaybyCustomerRead)
async def update_layby_customer(
    customer_id: int,
    customer: LaybyCustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Update a layby customer."""
    logging.info(f"Updating layby customer {customer_id} by user {current_user.username}")
    logging.info(f"Update data: name={customer.name}, phone={customer.phone}, email={customer.email}, address={customer.address}, layby_item_name={customer.layby_item_name}")
    
    db_customer = tenant_scope.get_scoped(db, LaybyCustomer, customer_id, current_user)
    if not db_customer:
        logging.error(f"Customer {customer_id} not found")
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Store old values for logging
    old_name = db_customer.name
    
    # Update fields
    db_customer.name = customer.name
    db_customer.phone = customer.phone
    db_customer.email = customer.email
    db_customer.address = customer.address
    db_customer.layby_item_name = customer.layby_item_name
    
    db.commit()
    db.refresh(db_customer)
    
    logging.info(f"Customer {customer_id} updated: {old_name} -> {db_customer.name}, layby_item_name={db_customer.layby_item_name}")
    
    # Return with active_items
    active_transactions = db.query(LaybyTransaction).filter(
        LaybyTransaction.customer_id == db_customer.id,
        LaybyTransaction.status == "active"
    ).all()
    active_items = ", ".join([f"{txn.product_name} (x{txn.quantity})" for txn in active_transactions]) if active_transactions else None
    
    customer_dict = {
        "id": db_customer.id,
        "name": db_customer.name,
        "phone": db_customer.phone,
        "email": db_customer.email,
        "address": db_customer.address,
        "layby_item_name": db_customer.layby_item_name,
        "created_at": db_customer.created_at,
        "updated_at": db_customer.updated_at,
        "active_items": active_items,
    }
    return LaybyCustomerRead(**customer_dict)


@app.get("/api/layby/customers/{customer_id}", response_model=LaybyCustomerRead)
async def get_layby_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get a layby customer by ID."""
    customer = tenant_scope.get_scoped(db, LaybyCustomer, customer_id, current_user)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    active_transactions = db.query(LaybyTransaction).filter(
        LaybyTransaction.customer_id == customer.id,
        LaybyTransaction.status == "active",
    ).all()
    active_items = ", ".join([f"{txn.product_name} (x{txn.quantity})" for txn in active_transactions]) if active_transactions else None
    return LaybyCustomerRead(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        email=customer.email,
        address=customer.address,
        layby_item_name=customer.layby_item_name,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
        active_items=active_items,
    )


class DeleteCustomerRequest(BaseModel):
    admin_password: str


@app.post("/api/layby/customers/{customer_id}/delete")
async def delete_layby_customer(
    customer_id: int,
    request: DeleteCustomerRequest,
    db: Session = Depends(get_db),
):
    """Delete a layby customer. Requires admin password verification (no auth token needed)."""
    customer = db.get(LaybyCustomer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    cust_tid = getattr(customer, "tenant_id", None)
    admin_q = db.query(User).filter(User.role == "admin", User.is_active == True)  # noqa: E712
    if cust_tid is None:
        admin_q = admin_q.filter(User.tenant_id.is_(None))
    else:
        admin_q = admin_q.filter(User.tenant_id == cust_tid)
    admin_user = admin_q.first()
    if not admin_user:
        raise HTTPException(status_code=500, detail="No active admin user found in system")
    
    if not auth.verify_password(request.admin_password, admin_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid admin password")
    
    # Delete customer (cascade will delete all transactions and payments)
    customer_name = customer.name
    db.delete(customer)
    db.commit()
    
    logging.info(f"Layby customer {customer_id} ({customer_name}) deleted")
    return {"ok": True, "message": "Customer deleted successfully"}


@app.post("/api/backup/sync-debtors")
async def sync_debtors_to_backup(
    db: Session = Depends(get_db),
    current_admin: User = Depends(auth.get_current_admin_user),
):
    """Sync all debtors to Google Sheets backup."""
    try:
        backup_service = get_backup_service()
        if not backup_service.is_enabled():
            raise HTTPException(status_code=400, detail="Backup is not enabled")
        
        result = backup_service.sync_all_debtors(db)
        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get("message", "Sync failed"))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error syncing debtors to backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/backup/sync-withdrawals")
async def sync_withdrawals_to_backup(
    db: Session = Depends(get_db),
    current_admin: User = Depends(auth.get_current_admin_user),
):
    """Sync all withdrawals to Google Sheets backup."""
    try:
        backup_service = get_backup_service()
        if not backup_service.is_enabled():
            raise HTTPException(status_code=400, detail="Backup is not enabled")
        
        result = backup_service.sync_all_withdrawals(db)
        if result.get("success"):
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get("message", "Sync failed"))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error syncing withdrawals to backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/debts/outstanding")
async def get_outstanding_debts(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get all customers with outstanding debts (regular customers with credit_balance and layby customers with balances)."""
    debts = []
    grand_total = Decimal("0.00")
    
    # Get regular customers with credit_balance > 0
    regular_customers = (
        tenant_scope.filter_customers(db, current_user).filter(Customer.credit_balance > 0).all()
    )
    for customer in regular_customers:
        debt_amount = Decimal(str(customer.credit_balance))
        debts.append({
            "customer_id": customer.id,
            "customer_name": customer.name,
            "phone": customer.phone or "",
            "address": customer.address or "",
            "debt_type": "credit_sale",
            "debt_amount": float(debt_amount),
        })
        grand_total += debt_amount
    
    # Get layby customers with outstanding balances
    layby_customers = tenant_scope.filter_layby_customers(db, current_user).all()
    for layby_customer in layby_customers:
        # Get all active transactions for this customer
        active_transactions = db.query(LaybyTransaction).filter(
            LaybyTransaction.customer_id == layby_customer.id,
            LaybyTransaction.status == "active"
        ).all()
        
        customer_total_balance = Decimal("0.00")
        for txn in active_transactions:
            customer_total_balance += Decimal(str(txn.balance))
        
        if customer_total_balance > 0:
            debts.append({
                "customer_id": layby_customer.id,
                "customer_name": layby_customer.name,
                "phone": layby_customer.phone or "",
                "address": layby_customer.address or "",
                "debt_type": "layby",
                "debt_amount": float(customer_total_balance),
            })
            grand_total += customer_total_balance
    
    # Sort by debt amount (highest first)
    debts.sort(key=lambda x: x["debt_amount"], reverse=True)
    
    return {
        "debts": debts,
        "grand_total": float(grand_total),
        "count": len(debts)
    }


@app.get("/api/layby/transactions", response_model=List[LaybyTransactionRead])
async def list_layby_transactions(
    customer_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """List layby transactions, optionally filtered by customer or status."""
    query = tenant_scope.filter_layby_transactions(db, current_user)
    if customer_id:
        lc = tenant_scope.get_scoped(db, LaybyCustomer, customer_id, current_user)
        if lc is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        query = query.filter(LaybyTransaction.customer_id == customer_id)
    if status:
        query = query.filter(LaybyTransaction.status == status)
    transactions = query.order_by(LaybyTransaction.created_at.desc()).all()
    
    result = []
    for txn in transactions:
        result.append(LaybyTransactionRead(
            id=txn.id,
            customer_id=txn.customer_id,
            customer_name=txn.customer.name,
            product_id=txn.product_id,
            product_name=txn.product_name,
            quantity=txn.quantity,
            unit_price=txn.unit_price,
            total_amount=txn.total_amount,
            paid_amount=txn.paid_amount,
            balance=txn.balance,
            status=txn.status,
            created_at=txn.created_at,
            completed_at=txn.completed_at,
            notes=txn.notes,
        ))
    return result


@app.post("/api/layby/transactions", response_model=LaybyTransactionRead)
async def create_layby_transaction(
    transaction: LaybyTransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Create a new layby transaction."""
    customer = tenant_scope.get_scoped(db, LaybyCustomer, transaction.customer_id, current_user)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    product = tenant_scope.require_product(db, transaction.product_id, current_user)
    
    # Check available stock (accounting for reserved items and layby)
    available_stock = product.stock_qty - (product.reserved_qty or 0.0)
    if available_stock <= 0:
        raise HTTPException(status_code=400, detail=f"Product '{product.name}' is out of stock (including reserved items)")
    if available_stock < transaction.quantity:
        raise HTTPException(status_code=400, detail=f"Insufficient stock for '{product.name}'. Available: {available_stock}, Requested: {transaction.quantity} (Total stock: {product.stock_qty}, Reserved: {product.reserved_qty or 0})")
    
    total_amount = product.selling_price * transaction.quantity
    balance = total_amount
    
    # Create transaction with status="active" - all new transactions are active by default
    # Transaction remains active until balance is fully paid (balance <= 0)
    db_transaction = LaybyTransaction(
        customer_id=transaction.customer_id,
        product_id=transaction.product_id,
        product_name=product.name,
        quantity=transaction.quantity,
        unit_price=product.selling_price,
        total_amount=total_amount,
        paid_amount=Decimal("0"),
        balance=balance,
        status="active",  # All new transactions start as active
        notes=transaction.notes,
    )
    db.add(db_transaction)
    
    # Check available stock (accounting for reserved items)
    available_stock = product.stock_qty - (product.reserved_qty or 0.0)
    if available_stock <= 0:
        raise HTTPException(status_code=400, detail=f"Product '{product.name}' is out of stock (including reserved items)")
    if available_stock < transaction.quantity:
        raise HTTPException(status_code=400, detail=f"Insufficient stock for '{product.name}'. Available: {available_stock}, Requested: {transaction.quantity} (Total stock: {product.stock_qty}, Reserved: {product.reserved_qty or 0})")
    
    # Reserve stock for layby (add to reserved_qty, don't deduct from stock_qty)
    # Stock is physically still there but reserved for layby customer
    product.reserved_qty = (product.reserved_qty or 0.0) + transaction.quantity
    db.add(InventoryMovement(
        product_id=product.id,
        change_qty=0,  # No actual stock change, just reservation
        reason=f"Layby reservation (Transaction #{db_transaction.id})",
    ))
    
    # Check for low stock after layby reservation
    try:
        from .notification_service import NotificationService
        notification_service = NotificationService(db)
        notification_service.check_low_stock(product)
        # Send batch email with all low-stock products
        notification_service.check_all_products_low_stock()
    except Exception as e:
        logging.warning(f"Error checking low stock for product {product.id}: {e}")
    
    db.commit()
    db.refresh(db_transaction)
    
    return LaybyTransactionRead(
        id=db_transaction.id,
        customer_id=db_transaction.customer_id,
        customer_name=customer.name,
        product_id=db_transaction.product_id,
        product_name=db_transaction.product_name,
        quantity=db_transaction.quantity,
        unit_price=db_transaction.unit_price,
        total_amount=db_transaction.total_amount,
        paid_amount=db_transaction.paid_amount,
        balance=db_transaction.balance,
        status=db_transaction.status,
        created_at=db_transaction.created_at,
        completed_at=db_transaction.completed_at,
        notes=db_transaction.notes,
    )


@app.post("/api/layby/payments", response_model=LaybyPaymentRead)
async def create_layby_payment(
    payment: LaybyPaymentCreate,
    db: Session = Depends(get_db),
):
    """Record a payment for a layby transaction and print receipt. Accessible without authentication."""
    transaction = db.get(LaybyTransaction, payment.transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    layby_customer = db.get(LaybyCustomer, transaction.customer_id)
    cust_tid = getattr(layby_customer, "tenant_id", None) if layby_customer else None
    
    if transaction.status != "active":
        raise HTTPException(status_code=400, detail="Transaction is not active")
    
    if payment.amount > transaction.balance:
        raise HTTPException(status_code=400, detail="Payment amount exceeds balance")
    
    # Cashier for receipt: prefer an admin in the same tenant as the layby customer
    admin_q = db.query(User).filter(User.role == "admin", User.is_active == True)  # noqa: E712
    if cust_tid is None:
        admin_q = admin_q.filter(User.tenant_id.is_(None))
    else:
        admin_q = admin_q.filter(User.tenant_id == cust_tid)
    cashier_user = admin_q.first()
    if not cashier_user:
        any_q = db.query(User).filter(User.is_active == True)  # noqa: E712
        if cust_tid is None:
            any_q = any_q.filter(User.tenant_id.is_(None))
        else:
            any_q = any_q.filter(User.tenant_id == cust_tid)
        cashier_user = any_q.first()
    if not cashier_user:
        raise HTTPException(status_code=500, detail="No active user found for this store")
    
    # Generate receipt number
    receipt_number = f"LAYBY-{transaction.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    # Create payment record
    db_payment = LaybyPayment(
        transaction_id=payment.transaction_id,
        amount=payment.amount,
        payment_method=payment.payment_method,
        cashier_id=cashier_user.id,
        receipt_number=receipt_number,
        notes=payment.notes,
    )
    db.add(db_payment)
    
    # Store amounts BEFORE updating (for receipt display)
    total_amount = transaction.total_amount
    paid_amount_before = transaction.paid_amount
    outstanding_before = transaction.balance
    
    # Store transaction data before potential deletion (for receipt)
    transaction_id = transaction.id
    product_name = transaction.product_name
    product_quantity = transaction.quantity
    unit_price = transaction.unit_price
    customer_name = transaction.customer.name
    
    # Update transaction
    transaction.paid_amount += payment.amount
    transaction.balance -= payment.amount
    
    # Check if this is the final payment (balance fully paid)
    is_final_payment = transaction.balance <= 0
    new_paid_total = transaction.paid_amount
    
    if is_final_payment:
        # Layby completed - move from reserved to actual stock deduction
        # Customer has fully paid, so deduct from stock_qty and remove from reserved_qty
        product = db.get(Product, transaction.product_id)
        if product and tenant_scope.same_tenant(cust_tid, getattr(product, "tenant_id", None)):
            # Remove from reserved_qty
            if (product.reserved_qty or 0.0) >= transaction.quantity:
                product.reserved_qty = (product.reserved_qty or 0.0) - transaction.quantity
            else:
                product.reserved_qty = 0.0
            
            # Deduct from actual stock (product delivered to customer)
            product.stock_qty -= transaction.quantity
            db.add(InventoryMovement(
                product_id=product.id,
                change_qty=-transaction.quantity,
                reason=f"Layby transaction #{transaction.id} completed - product delivered",
            ))
    
    # Commit the payment and transaction update
    db.commit()
    
    if is_final_payment:
        # Store payment data before deletion (for response)
        cashier_name = cashier_user.full_name if cashier_user.full_name else cashier_user.username
        payment_data_for_response = {
            "id": db_payment.id,
            "transaction_id": db_payment.transaction_id,
            "amount": db_payment.amount,
            "payment_method": db_payment.payment_method,
            "cashier_id": db_payment.cashier_id,
            "cashier_name": cashier_name,
            "receipt_number": db_payment.receipt_number,
            "created_at": db_payment.created_at,
            "notes": db_payment.notes,
        }
        
        # Delete the transaction permanently (cascade will delete all payments including this one)
        db.delete(transaction)
        db.commit()
        
        logging.info(f"Layby transaction #{transaction_id} and all payments permanently deleted after final payment")
    else:
        # Transaction remains active - refresh payment for response
        db.refresh(db_payment)
        payment_data_for_response = None
    
    # Get store settings for receipt (tenant of layby customer)
    store_settings = tenant_scope.first_store_settings_for_tenant(db, cust_tid)
    cashier_name = cashier_user.full_name if cashier_user.full_name else cashier_user.username
    
    # Build detailed footer with outstanding amount information
    footer_lines = [
        "LAYBY PAYMENT",
        f"Receipt: {receipt_number}",
        "",
        "LAYBY SUMMARY:",
        f"Total Amount:      ${total_amount:.2f}",
        f"Paid Before:       ${paid_amount_before:.2f}",
        f"This Payment:      ${payment.amount:.2f}",
        f"Paid Total:        ${new_paid_total:.2f}",
    ]
    
    if is_final_payment:
        footer_lines.append("STATUS:            PAID IN FULL")
    else:
        footer_lines.append(f"OUTSTANDING:        ${outstanding_before - payment.amount:.2f}")
    
    footer = "\n".join(footer_lines)
    
    # Print receipt
    print_success = print_receipt(
        sale_id=0,  # Not a regular sale
        store_name=store_settings.store_name.upper() if store_settings else STORE_NAME.upper(),
        items=[{
            "name": product_name,
            "quantity": product_quantity,
            "unit_price": float(unit_price),
            "line_total": float(unit_price * product_quantity),
        }],
        subtotal=total_amount,
        discount_total=Decimal("0"),
        total=payment.amount,
        payments=[{
            "method": payment.payment_method,
            "amount": payment.amount,
        }],
        customer_name=customer_name,
        cashier_name=cashier_name,
        cashier_role=cashier_user.role,
        store_phone=store_settings.store_phone if store_settings else None,
        store_location=store_settings.store_location if store_settings else None,
        footer=footer,
        collection_status=None,  # Layby payments don't have collection status
    )
    
    if not print_success:
        if is_final_payment:
            logging.warning(f"Failed to print receipt for final layby payment (transaction deleted)")
        else:
            logging.warning(f"Failed to print receipt for layby payment {db_payment.id}")
    
    # Return payment data
    if is_final_payment:
        # Transaction and payments have been deleted, return stored data
        return LaybyPaymentRead(**payment_data_for_response)
    else:
        # Transaction still exists, return from database
        return LaybyPaymentRead(
        id=db_payment.id,
        transaction_id=db_payment.transaction_id,
        amount=db_payment.amount,
        payment_method=db_payment.payment_method,
        cashier_id=db_payment.cashier_id,
        cashier_name=cashier_name,
        receipt_number=db_payment.receipt_number,
        created_at=db_payment.created_at,
        notes=db_payment.notes,
    )


@app.get("/api/layby/payments/{transaction_id}", response_model=List[LaybyPaymentRead])
async def get_layby_payments(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    """Get all payments for a layby transaction. Accessible without authentication."""
    # Verify transaction exists
    transaction = db.get(LaybyTransaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    payments = db.query(LaybyPayment).filter(
        LaybyPayment.transaction_id == transaction_id
    ).order_by(LaybyPayment.created_at).all()
    
    result = []
    for payment in payments:
        cashier = db.get(User, payment.cashier_id)
        cashier_name = cashier.full_name if cashier and cashier.full_name else (cashier.username if cashier else "Unknown")
        result.append(LaybyPaymentRead(
            id=payment.id,
            transaction_id=payment.transaction_id,
            amount=payment.amount,
            payment_method=payment.payment_method,
            cashier_id=payment.cashier_id,
            cashier_name=cashier_name,
            receipt_number=payment.receipt_number,
            created_at=payment.created_at,
            notes=payment.notes,
        ))
    return result


# ==================== WITHDRAWALS ====================

class WithdrawalCreate(BaseModel):
    amount: Decimal = Field(gt=0, description="Withdrawal amount must be greater than 0")
    reason: str = Field(..., min_length=1, max_length=200, description="Reason for withdrawal")
    notes: Optional[str] = None
    salary_details: Optional[dict] = None  # Employee details for salary withdrawals


class WithdrawalRead(BaseModel):
    id: int
    cashier_id: int
    cashier_name: str
    amount: Decimal
    reason: str
    receipt_number: Optional[str]
    created_at: datetime
    notes: Optional[str]

    class Config:
        from_attributes = True


@app.post("/api/withdrawals", response_model=WithdrawalRead)
async def create_withdrawal(
    withdrawal: WithdrawalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Create a withdrawal record and print receipt. Supervisors and admins only."""
    require_permission(current_user, Perm.PROCESS_WITHDRAWALS)
    import random
    import string
    
    # Generate receipt number
    receipt_number = f"WD{''.join(random.choices(string.digits, k=8))}"
    
    # Ensure receipt number is unique within this tenant
    while (
        tenant_scope.filter_withdrawals(db, current_user)
        .filter(Withdrawal.receipt_number == receipt_number)
        .first()
    ):
        receipt_number = f"WD{''.join(random.choices(string.digits, k=8))}"
    
    # Store salary details in notes if provided (as JSON string)
    notes_to_store = withdrawal.notes
    if withdrawal.reason == "Salary" and withdrawal.salary_details:
        import json
        salary_info = {
            "employee_name": withdrawal.salary_details.get("employee_name", ""),
            "employee_id": withdrawal.salary_details.get("employee_id", ""),
            "position": withdrawal.salary_details.get("position", ""),
            "period": withdrawal.salary_details.get("period", ""),
            "additional_notes": withdrawal.salary_details.get("additional_notes", "")
        }
        salary_json = json.dumps(salary_info)
        notes_to_store = f"SALARY_DETAILS:{salary_json}" + (f"\n\nAdditional Notes: {withdrawal.notes}" if withdrawal.notes else "")
    
    db_withdrawal = Withdrawal(
        cashier_id=current_user.id,
        amount=withdrawal.amount,
        reason=withdrawal.reason,
        receipt_number=receipt_number,
        notes=notes_to_store,
        tenant_id=tenant_scope.tenant_id_for_row(current_user),
    )
    db.add(db_withdrawal)
    db.flush()  # Get withdrawal ID before commit
    
    # Post to accounting (if Chart of Accounts is initialized) - BEFORE commit for atomicity
    try:
        if verify_chart_of_accounts(db):
            accounting_engine = AccountingEngine(db)
            
            # If reason is "Buying company assets", create FixedAsset instead of posting as expense
            if withdrawal.reason == "Buying company assets":
                try:
                    # Generate unique asset code
                    last_asset = (
                        tenant_scope.filter_fixed_assets(db, current_user)
                        .order_by(FixedAsset.id.desc())
                        .first()
                    )
                    if last_asset and last_asset.asset_code:
                        try:
                            last_num = int(last_asset.asset_code.split("-")[-1])
                            next_num = last_num + 1
                        except (ValueError, IndexError):
                            next_num = 1
                    else:
                        next_num = 1
                    asset_code = f"FA-{next_num:03d}"
                    
                    # Extract asset name from notes, or use default
                    asset_name = withdrawal.notes.strip() if withdrawal.notes and withdrawal.notes.strip() else f"Company Asset {asset_code}"
                    # Remove "SALARY_DETAILS:" prefix if present (from salary withdrawals)
                    if asset_name.startswith("SALARY_DETAILS:"):
                        asset_name = f"Company Asset {asset_code}"
                    
                    # Default useful life: 60 months (5 years) - can be adjusted later
                    useful_life_months = 60
                    
                    # Create fixed asset (this will post: Dr Fixed Assets, Cr Cash)
                    asset, asset_journal_entry = accounting_engine.create_fixed_asset(
                        asset_code=asset_code,
                        name=asset_name,
                        purchase_date=db_withdrawal.created_at,
                        purchase_cost=Decimal(str(withdrawal.amount)),
                        useful_life_months=useful_life_months,
                        created_by=current_user.id,
                        payment_account_code="1000"  # Cash account
                    )
                    db.flush()  # Ensure asset is saved
                    logging.info(f"Created fixed asset {asset_code} ({asset_name}) from withdrawal {db_withdrawal.id} - Amount: ${withdrawal.amount}")
                except Exception as asset_error:
                    # If asset creation fails, rollback the entire withdrawal (atomicity requirement)
                    db.rollback()
                    logging.error(f"Error creating fixed asset from withdrawal {db_withdrawal.id}: {asset_error}", exc_info=True)
                    raise HTTPException(
                        status_code=500,
                        detail=f"Error creating asset from withdrawal: {str(asset_error)}"
                    )
            else:
                # For other withdrawal reasons, post as normal expense
                accounting_engine.post_withdrawal(db_withdrawal)
                logging.info(f"Posted withdrawal {db_withdrawal.id} to accounting")
        else:
            logging.debug("Chart of Accounts not initialized. Skipping accounting post.")
    except Exception as e:
        # If accounting fails, rollback the entire withdrawal (atomicity requirement)
        db.rollback()
        logging.error(f"Error posting withdrawal to accounting: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing withdrawal: {str(e)}"
        )
    
    db.commit()
    db.refresh(db_withdrawal)
    
    # Get store settings for receipt
    store_settings = tenant_scope.filter_store_settings(db, current_user).first()
    store_name = store_settings.store_name if store_settings else STORE_NAME
    store_phone = store_settings.store_phone if store_settings else STORE_PHONE
    store_location = store_settings.store_location if store_settings else STORE_LOCATION
    
    # Print receipt
    try:
        # Extract salary details if this is a salary withdrawal
        salary_details = None
        if withdrawal.reason == "Salary" and withdrawal.salary_details:
            salary_details = withdrawal.salary_details
        
        print_withdrawal_receipt(
            withdrawal_id=db_withdrawal.id,
            receipt_number=receipt_number,
            store_name=store_name,
            amount=withdrawal.amount,
            reason=withdrawal.reason,
            cashier_name=current_user.full_name or current_user.username,
            notes=notes_to_store,
            store_phone=store_phone,
            store_location=store_location,
            salary_details=salary_details,
        )
    except Exception as e:
        logging.error(f"Error printing withdrawal receipt: {e}")
        # Don't fail the withdrawal if printing fails
    
    # Sync to Google Sheets backup
    try:
        backup_service = get_backup_service()
        if backup_service.is_enabled():
            backup_service.sync_withdrawal_create(db, db_withdrawal)
    except Exception as e:
        logging.error(f"Error syncing withdrawal to backup: {e}")
    
    # Return withdrawal with cashier name
    return WithdrawalRead(
        id=db_withdrawal.id,
        cashier_id=db_withdrawal.cashier_id,
        cashier_name=current_user.full_name or current_user.username,
        amount=db_withdrawal.amount,
        reason=db_withdrawal.reason,
        receipt_number=db_withdrawal.receipt_number,
        created_at=db_withdrawal.created_at,
        notes=db_withdrawal.notes,
    )


@app.get("/api/withdrawals", response_model=List[WithdrawalRead])
async def list_withdrawals(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_WITHDRAWALS)),
):
    """List all withdrawals."""
    withdrawals = (
        tenant_scope.filter_withdrawals(db, current_user)
        .order_by(Withdrawal.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    result = []
    for w in withdrawals:
        cashier = tenant_scope.get_scoped(db, User, w.cashier_id, current_user)
        result.append(WithdrawalRead(
            id=w.id,
            cashier_id=w.cashier_id,
            cashier_name=(cashier.full_name or cashier.username) if cashier else "Unknown",
            amount=w.amount,
            reason=w.reason,
            receipt_number=w.receipt_number,
            created_at=w.created_at,
            notes=w.notes,
        ))
    return result


@app.get("/api/withdrawals/{withdrawal_id}", response_model=WithdrawalRead)
async def get_withdrawal(
    withdrawal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(dep_perm(Perm.VIEW_WITHDRAWALS)),
):
    """Get a specific withdrawal."""
    withdrawal = tenant_scope.require_withdrawal(db, withdrawal_id, current_user)
    
    cashier = tenant_scope.get_scoped(db, User, withdrawal.cashier_id, current_user)
    return WithdrawalRead(
        id=withdrawal.id,
        cashier_id=withdrawal.cashier_id,
        cashier_name=(cashier.full_name or cashier.username) if cashier else "Unknown",
        amount=withdrawal.amount,
        reason=withdrawal.reason,
        receipt_number=withdrawal.receipt_number,
        created_at=withdrawal.created_at,
        notes=withdrawal.notes,
    )


# ==================== CASHIER SHIFTS ====================

class ShiftStart(BaseModel):
    starting_cash: Decimal = Field(default=0, ge=0, description="Starting cash amount")
    notes: Optional[str] = None


class ShiftEnd(BaseModel):
    ending_cash: Decimal = Field(..., ge=0, description="Ending cash amount")
    notes: Optional[str] = None


class VerifyAdminPasswordRequest(BaseModel):
    password: str


class ShiftRead(BaseModel):
    id: int
    cashier_id: int
    cashier_name: str
    start_time: datetime
    end_time: Optional[datetime]
    starting_cash: Decimal
    ending_cash: Optional[Decimal]
    total_sales: Decimal
    total_transactions: int
    total_cash: Decimal
    total_mobile_money: Decimal
    total_card: Decimal
    total_credit: Decimal
    total_discounts: Decimal
    notes: Optional[str]
    report_generated: bool
    report_generated_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ShiftReport(BaseModel):
    shift: ShiftRead
    transactions: List[dict]
    summary: dict


def generate_shift_report(db: Session, shift: CashierShift) -> dict:
    """Generate a detailed report for a shift."""
    stid = getattr(shift, "tenant_id", None)
    # Get all sales for this shift (same tenant as shift)
    if stid is None:
        sales = (
            db.query(Sale)
            .filter(Sale.shift_id == shift.id, Sale.tenant_id.is_(None))
            .order_by(Sale.created_at)
            .all()
        )
    else:
        sales = (
            db.query(Sale)
            .filter(Sale.shift_id == shift.id, Sale.tenant_id == stid)
            .order_by(Sale.created_at)
            .all()
        )

    transactions = []
    for sale in sales:
        # Get payment methods
        payments = db.query(Payment).filter(Payment.sale_id == sale.id).all()
        payment_methods = {p.method: float(p.amount) for p in payments}

        # Get items
        items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()

        def _product_label(pid: int) -> str:
            p = db.get(Product, pid)
            if not p or not tenant_scope.same_tenant(getattr(p, "tenant_id", None), stid):
                return "Unknown"
            return p.name

        def _customer_name(cid: Optional[int]) -> Optional[str]:
            if not cid:
                return None
            c = db.get(Customer, cid)
            if not c or not tenant_scope.same_tenant(getattr(c, "tenant_id", None), stid):
                return None
            return c.name

        items_list = [
            {
                "product_name": _product_label(item.product_id),
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "discount": float(item.discount),
                "line_total": float(item.line_total),
            }
            for item in items
        ]

        transactions.append(
            {
                "id": sale.id,
                "created_at": sale.created_at.isoformat(),
                "customer_name": _customer_name(sale.customer_id),
                "subtotal": float(sale.subtotal),
                "discount_total": float(sale.discount_total),
                "total": float(sale.total),
                "payment_methods": payment_methods,
                "items": items_list,
                "notes": sale.notes,
            }
        )
    
    # Calculate summary
    summary = {
        'total_sales': float(shift.total_sales),
        'total_transactions': shift.total_transactions,
        'total_cash': float(shift.total_cash),
        'total_mobile_money': float(shift.total_mobile_money),
        'total_card': float(shift.total_card),
        'total_credit': float(shift.total_credit),
        'total_discounts': float(shift.total_discounts),
        'expected_cash': float(shift.starting_cash) + float(shift.total_cash),
        'actual_cash': float(shift.ending_cash) if shift.ending_cash else None,
        'cash_difference': float(shift.ending_cash) - (float(shift.starting_cash) + float(shift.total_cash)) if shift.ending_cash else None,
        'shift_duration': str(shift.end_time - shift.start_time) if shift.end_time else None
    }
    
    return {
        'shift': shift,
        'transactions': transactions,
        'summary': summary
    }


@app.post("/api/shifts/start", response_model=ShiftRead)
async def start_shift(
    shift_data: ShiftStart,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Start a new cashier shift."""
    # Check if there's an active shift
    active_shift = (
        tenant_scope.filter_shifts(db, current_user)
        .filter(
            CashierShift.cashier_id == current_user.id,
            CashierShift.end_time.is_(None),
        )
        .first()
    )
    
    if active_shift:
        raise HTTPException(
            status_code=400,
            detail="You already have an active shift. Please end it before starting a new one."
        )
    
    shift = CashierShift(
        cashier_id=current_user.id,
        starting_cash=shift_data.starting_cash,
        notes=shift_data.notes,
        tenant_id=tenant_scope.tenant_id_for_row(current_user),
        branch_id=tenant_scope.resolve_branch_id_for_sale(current_user, None),
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    
    cashier = tenant_scope.get_scoped(db, User, shift.cashier_id, current_user)
    return ShiftRead(
        id=shift.id,
        cashier_id=shift.cashier_id,
        cashier_name=(cashier.full_name or cashier.username) if cashier else "Unknown",
        start_time=shift.start_time,
        end_time=shift.end_time,
        starting_cash=shift.starting_cash,
        ending_cash=shift.ending_cash,
        total_sales=shift.total_sales,
        total_transactions=shift.total_transactions,
        total_cash=shift.total_cash,
        total_mobile_money=shift.total_mobile_money,
        total_card=shift.total_card,
        total_credit=shift.total_credit,
        total_discounts=shift.total_discounts,
        notes=shift.notes,
        report_generated=shift.report_generated,
        report_generated_at=shift.report_generated_at,
        created_at=shift.created_at,
    )


@app.post("/api/shifts/verify-admin-password")
async def verify_admin_password_for_shift(
    request: VerifyAdminPasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """
    Verify admin or supervisor password for accessing shift panel.
    Used when cashiers need to end their shift (requires admin/supervisor authorization).
    Checks against all active admin and supervisor users - accepts any valid admin/supervisor password.
    """
    # Find all active admin or supervisor users in this tenant
    admin_and_supervisors = (
        tenant_scope.filter_users(db, current_user)
        .filter(
            User.role.in_(["admin", "supervisor"]),
            User.is_active == True  # noqa: E712
        )
        .all()
    )
    
    if not admin_and_supervisors:
        raise HTTPException(status_code=404, detail="No active admin or supervisor found in system")
    
    # Verify password against any admin/supervisor user
    for user in admin_and_supervisors:
        if auth.verify_password(request.password, user.password_hash):
            return {"ok": True, "message": "Password verified successfully"}
    
    # If we get here, password didn't match any admin/supervisor
    raise HTTPException(status_code=401, detail="Invalid admin/supervisor password")


@app.post("/api/shifts/{shift_id}/end", response_model=ShiftReport)
async def end_shift(
    shift_id: int,
    shift_data: ShiftEnd,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """End a cashier shift and generate report."""
    shift = tenant_scope.require_shift(db, shift_id, current_user)
    
    if shift.cashier_id != current_user.id and not has_permission(current_user, Perm.MANAGE_SHIFTS):
        raise HTTPException(status_code=403, detail="You can only end your own shifts")
    
    if shift.end_time:
        raise HTTPException(status_code=400, detail="Shift is already ended")
    
    # Calculate shift totals from sales
    sales = tenant_scope.filter_sales(db, current_user).filter(Sale.shift_id == shift.id).all()
    
    total_sales = sum(Decimal(str(sale.total)) for sale in sales)
    total_transactions = len(sales)
    total_cash = Decimal(0)
    total_mobile_money = Decimal(0)
    total_card = Decimal(0)
    total_credit = Decimal(0)
    total_discounts = sum(Decimal(str(sale.discount_total)) for sale in sales)
    
    for sale in sales:
        payments = db.query(Payment).filter(Payment.sale_id == sale.id).all()
        for payment in payments:
            amount = Decimal(str(payment.amount))
            if payment.method == "cash":
                total_cash += amount
            elif payment.method == "mobile_money":
                total_mobile_money += amount
            elif payment.method == "card":
                total_card += amount
            elif payment.method == "credit":
                total_credit += amount
    
    # Update shift
    shift.end_time = datetime.utcnow()
    shift.ending_cash = shift_data.ending_cash
    shift.total_sales = total_sales
    shift.total_transactions = total_transactions
    shift.total_cash = total_cash
    shift.total_mobile_money = total_mobile_money
    shift.total_card = total_card
    shift.total_credit = total_credit
    shift.total_discounts = total_discounts
    if shift_data.notes:
        shift.notes = (shift.notes or "") + "\n" + shift_data.notes if shift.notes else shift_data.notes
    shift.report_generated = True
    shift.report_generated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(shift)
    
    # Generate report
    report = generate_shift_report(db, shift)
    
    cashier = tenant_scope.get_scoped(db, User, shift.cashier_id, current_user)
    shift_read = ShiftRead(
        id=shift.id,
        cashier_id=shift.cashier_id,
        cashier_name=(cashier.full_name or cashier.username) if cashier else "Unknown",
        start_time=shift.start_time,
        end_time=shift.end_time,
        starting_cash=shift.starting_cash,
        ending_cash=shift.ending_cash,
        total_sales=shift.total_sales,
        total_transactions=shift.total_transactions,
        total_cash=shift.total_cash,
        total_mobile_money=shift.total_mobile_money,
        total_card=shift.total_card,
        total_credit=shift.total_credit,
        total_discounts=shift.total_discounts,
        notes=shift.notes,
        report_generated=shift.report_generated,
        report_generated_at=shift.report_generated_at,
        created_at=shift.created_at,
    )
    
    return ShiftReport(
        shift=shift_read,
        transactions=report['transactions'],
        summary=report['summary']
    )


@app.get("/api/shifts/active", response_model=Optional[ShiftRead])
async def get_active_shift(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get the active shift for the current cashier."""
    shift = (
        tenant_scope.filter_shifts(db, current_user)
        .filter(
            CashierShift.cashier_id == current_user.id,
            CashierShift.end_time.is_(None),
        )
        .first()
    )
    
    if not shift:
        return None
    
    cashier = tenant_scope.get_scoped(db, User, shift.cashier_id, current_user)
    return ShiftRead(
        id=shift.id,
        cashier_id=shift.cashier_id,
        cashier_name=(cashier.full_name or cashier.username) if cashier else "Unknown",
        start_time=shift.start_time,
        end_time=shift.end_time,
        starting_cash=shift.starting_cash,
        ending_cash=shift.ending_cash,
        total_sales=shift.total_sales,
        total_transactions=shift.total_transactions,
        total_cash=shift.total_cash,
        total_mobile_money=shift.total_mobile_money,
        total_card=shift.total_card,
        total_credit=shift.total_credit,
        total_discounts=shift.total_discounts,
        notes=shift.notes,
        report_generated=shift.report_generated,
        report_generated_at=shift.report_generated_at,
        created_at=shift.created_at,
    )


@app.get("/api/shifts", response_model=List[ShiftRead])
async def list_shifts(
    cashier_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """List all shifts. Users with manage_shifts see all; others see only their own."""
    query = tenant_scope.filter_shifts(db, current_user)
    
    if not has_permission(current_user, Perm.MANAGE_SHIFTS):
        query = query.filter(CashierShift.cashier_id == current_user.id)
    elif cashier_id:
        query = query.filter(CashierShift.cashier_id == cashier_id)
    
    shifts = query.order_by(CashierShift.start_time.desc()).offset(skip).limit(limit).all()
    
    result = []
    for shift in shifts:
        cashier = tenant_scope.get_scoped(db, User, shift.cashier_id, current_user)
        result.append(ShiftRead(
            id=shift.id,
            cashier_id=shift.cashier_id,
            cashier_name=(cashier.full_name or cashier.username) if cashier else "Unknown",
            start_time=shift.start_time,
            end_time=shift.end_time,
            starting_cash=shift.starting_cash,
            ending_cash=shift.ending_cash,
            total_sales=shift.total_sales,
            total_transactions=shift.total_transactions,
            total_cash=shift.total_cash,
            total_mobile_money=shift.total_mobile_money,
            total_card=shift.total_card,
            total_credit=shift.total_credit,
            total_discounts=shift.total_discounts,
            notes=shift.notes,
            report_generated=shift.report_generated,
            report_generated_at=shift.report_generated_at,
            created_at=shift.created_at,
        ))
    
    return result


@app.get("/api/shifts/{shift_id}", response_model=ShiftRead)
async def get_shift(
    shift_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get a specific shift."""
    shift = tenant_scope.require_shift(db, shift_id, current_user)
    
    if shift.cashier_id != current_user.id and not has_permission(current_user, Perm.MANAGE_SHIFTS):
        raise HTTPException(status_code=403, detail="You can only view your own shifts")
    
    cashier = tenant_scope.get_scoped(db, User, shift.cashier_id, current_user)
    return ShiftRead(
        id=shift.id,
        cashier_id=shift.cashier_id,
        cashier_name=(cashier.full_name or cashier.username) if cashier else "Unknown",
        start_time=shift.start_time,
        end_time=shift.end_time,
        starting_cash=shift.starting_cash,
        ending_cash=shift.ending_cash,
        total_sales=shift.total_sales,
        total_transactions=shift.total_transactions,
        total_cash=shift.total_cash,
        total_mobile_money=shift.total_mobile_money,
        total_card=shift.total_card,
        total_credit=shift.total_credit,
        total_discounts=shift.total_discounts,
        notes=shift.notes,
        report_generated=shift.report_generated,
        report_generated_at=shift.report_generated_at,
        created_at=shift.created_at,
    )


@app.get("/api/shifts/{shift_id}/report", response_model=ShiftReport)
async def get_shift_report(
    shift_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get detailed report for a shift."""
    shift = tenant_scope.require_shift(db, shift_id, current_user)
    
    if shift.cashier_id != current_user.id and not has_permission(current_user, Perm.MANAGE_SHIFTS):
        raise HTTPException(status_code=403, detail="You can only view your own shift reports")
    
    # Generate report
    report = generate_shift_report(db, shift)
    
    cashier = tenant_scope.get_scoped(db, User, shift.cashier_id, current_user)
    shift_read = ShiftRead(
        id=shift.id,
        cashier_id=shift.cashier_id,
        cashier_name=(cashier.full_name or cashier.username) if cashier else "Unknown",
        start_time=shift.start_time,
        end_time=shift.end_time,
        starting_cash=shift.starting_cash,
        ending_cash=shift.ending_cash,
        total_sales=shift.total_sales,
        total_transactions=shift.total_transactions,
        total_cash=shift.total_cash,
        total_mobile_money=shift.total_mobile_money,
        total_card=shift.total_card,
        total_credit=shift.total_credit,
        total_discounts=shift.total_discounts,
        notes=shift.notes,
        report_generated=shift.report_generated,
        report_generated_at=shift.report_generated_at,
        created_at=shift.created_at,
    )
    
    return ShiftReport(
        shift=shift_read,
        transactions=report['transactions'],
        summary=report['summary']
    )


# ==================== NOTIFICATIONS ====================

class NotificationRead(BaseModel):
    id: int
    type: str
    message: str
    product_id: Optional[int]
    is_read: bool
    created_at: datetime
    product_name: Optional[str] = None

    class Config:
        from_attributes = True


@app.get("/api/notifications", response_model=List[NotificationRead])
async def get_notifications(
    unread_only: bool = Query(default=False, description="Return only unread notifications"),
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get all notifications, sorted by newest first."""
    query = tenant_scope.filter_notifications(db, current_user)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    
    notifications = query.order_by(Notification.created_at.desc()).all()
    
    result = []
    for notif in notifications:
        product_name = None
        if notif.product_id:
            product = db.get(Product, notif.product_id)
            if product:
                product_name = product.name
        
        result.append(NotificationRead(
            id=notif.id,
            type=notif.type,
            message=notif.message,
            product_id=notif.product_id,
            is_read=notif.is_read,
            created_at=notif.created_at,
            product_name=product_name
        ))
    
    return result


@app.get("/api/notifications/unread-count")
async def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Get count of unread notifications."""
    from .notification_service import NotificationService
    notification_service = NotificationService(db)
    count = notification_service.get_unread_count(current_user)
    return {"count": count}


@app.put("/api/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Mark a notification as read."""
    from .notification_service import NotificationService
    notification_service = NotificationService(db)
    success = notification_service.mark_notification_read(notification_id, current_user)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True}


@app.put("/api/notifications/mark-all-read")
async def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Mark all notifications as read."""
    from .notification_service import NotificationService
    notification_service = NotificationService(db)
    count = notification_service.mark_all_read(current_user)
    return {"success": True, "count": count}


@app.post("/api/notifications/check-all")
async def check_all_products_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_active_user),
):
    """Manually check all products and create notifications for out-of-stock and qty <= 5 items."""
    from .notification_service import NotificationService
    
    try:
        notification_service = NotificationService(db)
        count = notification_service.check_all_products_and_create_notifications(current_user)

        return {
            "success": True,
            "message": f"Checked all products. Created {count} new notification(s).",
            "notifications_created": count
        }
    except Exception as e:
        logging.error(f"Error checking products for notifications: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error checking products: {str(e)}"
        )


@app.post("/api/notifications/test-email")
async def test_email_notification(
    db: Session = Depends(get_db),
    current_user: User = Depends(auth.get_current_admin_user),
):
    """Send a test email with real low-stock and out-of-stock products from the database."""
    from .email_service import email_service
    from .models import StoreSettings
    from .notification_service import NotificationService
    
    # Check if email service is configured
    if not email_service.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Email service is not configured. Please set SMTP environment variables (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD)."
        )
    
    # Get notification email from settings
    settings = tenant_scope.filter_store_settings(db, current_user).first()
    if not settings or not settings.notification_email:
        raise HTTPException(
            status_code=400,
            detail="Notification email address is not configured. Please set it in Store Settings."
        )
    
    # Get real low-stock and out-of-stock products from database
    notification_service = NotificationService(db)
    
    # Get all active products
    products = tenant_scope.filter_products(db, current_user).filter(Product.is_active == True).all()  # noqa: E712
    
    low_stock_products = []
    
    for product in products:
        threshold = notification_service.get_threshold(product)
        
        # Include products that are at or below threshold (including out of stock)
        if product.stock_qty <= threshold:
            low_stock_products.append({
                'name': product.name,
                'current_stock': product.stock_qty,
                'threshold': threshold
            })
    
    # Sort by stock quantity (lowest first) to show most critical items first
    low_stock_products.sort(key=lambda x: x['current_stock'])
    
    store_name = settings.store_name or "Store"
    
    if not low_stock_products:
        return {
            "success": True,
            "message": f"No low-stock or out-of-stock products found. All products are above their thresholds. Email not sent.",
            "products_count": 0
        }
    
    try:
        success = email_service.send_low_stock_batch_alert(
            to_email=settings.notification_email,
            products=low_stock_products,
            store_name=store_name
        )
        
        if success:
            return {
                "success": True,
                "message": f"Test email sent successfully to {settings.notification_email} with {len(low_stock_products)} low-stock/out-of-stock product(s). Please check your inbox.",
                "products_count": len(low_stock_products)
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to send test email. Check your SMTP configuration and server logs."
            )
    except Exception as e:
        logging.error(f"Error sending test email: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error sending test email: {str(e)}"
        )


try:
    from .quotation_endpoints import register_quotation_endpoints

    register_quotation_endpoints(app)
    logging.info("Quotation endpoints registered")
except ImportError as e:
    logging.warning(f"Could not import quotation endpoints: {e}")
except Exception as e:
    logging.error(f"Error registering quotation endpoints: {e}", exc_info=True)
