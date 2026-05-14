# EXISTING POS SYSTEM ANALYSIS
## Phase 1 - Codebase Analysis Report

**Date:** 2024  
**System:** Raspberry Pi Offline-First POS System  
**Analysis Status:** ✅ COMPLETE

---

## 1. EXECUTIVE SUMMARY

This is a **single-tenant, offline-first Point of Sale (POS) system** optimized for Raspberry Pi. The system is built with FastAPI (Python) backend, SQLite database, and vanilla JavaScript frontend. It currently supports product management, sales processing, inventory tracking, layby transactions, accounting, and AI-powered business analytics via Ollama.

**⚠️ CRITICAL FINDING:** The system is **NOT multi-tenant** despite user's description. It is a single-store, single-database system with no tenant isolation mechanisms.

---

## 2. TECHNOLOGY STACK

### Backend
- **Framework:** FastAPI 0.115.0
- **Database:** SQLite (pos.db) with SQLAlchemy ORM 2.0.35
- **Authentication:** JWT (python-jose 3.3.0) with OAuth2PasswordBearer
- **Password Hashing:** pbkdf2_sha256 (via passlib)
- **Server:** Uvicorn (ASGI)
- **Templating:** Jinja2 3.1.4
- **Background Tasks:** FastAPI BackgroundTasks, APScheduler 3.10.4

### Frontend
- **Architecture:** Vanilla JavaScript (no frameworks)
- **HTTP Client:** Fetch API
- **Templating:** Server-side Jinja2 templates
- **Styling:** Custom CSS (style.css)
- **No Build Tools:** Direct HTML/CSS/JS files

### AI Integration
- **Service:** Ollama (local, localhost:11434)
- **Model:** phi:2.7b (configurable)
- **Integration:** HTTP API and subprocess CLI
- **Location:** `app/ai_service.py`

### Additional Services
- **Email:** SMTP via `app/email_service.py` (python-dotenv for config)
- **Printing:** ESC/POS thermal printer via `app/escpos_printer.py`
- **Backup:** Google Sheets sync (optional) via `app/backup_service.py`
- **Scheduling:** APScheduler for periodic tasks

---

## 3. PROJECT STRUCTURE

```
/home/morrison/Desktop/pos/
├── app/                          # Backend application
│   ├── __init__.py
│   ├── main.py                   # FastAPI app, all API endpoints
│   ├── models.py                 # SQLAlchemy ORM models
│   ├── auth.py                   # Authentication & authorization
│   ├── database.py               # Database connection & session
│   ├── config.py                 # Configuration (DB, printer, store info)
│   ├── ai_service.py             # Ollama AI integration (EXISTING)
│   ├── email_service.py           # SMTP email service
│   ├── escpos_printer.py          # Thermal printer integration
│   ├── notification_service.py   # Low-stock & expiry notifications
│   ├── scheduler_service.py       # Background task scheduling
│   ├── backup_service.py         # Google Sheets backup
│   ├── accounting_*.py           # Accounting system modules
│   └── init_db.py                # Database initialization
├── templates/                     # HTML templates (Jinja2)
│   ├── index.html                # Main POS interface
│   ├── admin.html                # Admin panel
│   ├── accounting.html           # Accounting reports
│   ├── layby.html                # Layby management
│   └── *.html                    # Other pages
├── static/
│   ├── css/
│   │   └── style.css             # Global styles
│   └── js/
│       ├── app.js                 # Main POS JavaScript
│       ├── admin.js               # Admin panel JavaScript
│       ├── layby.js               # Layby management JavaScript
│       └── *.js                   # Other page-specific scripts
├── pos.db                         # SQLite database file
├── requirements.txt               # Python dependencies
└── README.md                      # Project documentation
```

---

## 4. DATABASE SCHEMA

### Core Tables (DO NOT MODIFY)

#### `users`
- **Purpose:** User authentication (admin/cashier)
- **Key Fields:** `id`, `username`, `password_hash`, `role`, `is_active`
- **Relationships:** One-to-many with `sales`, `withdrawals`
- **⚠️ DO NOT TOUCH:** Core authentication table

#### `products`
- **Purpose:** Product catalog
- **Key Fields:** `id`, `name`, `barcode`, `category_id`, `stock_qty`, `cost_price`, `selling_price`, `is_active`, `low_stock_threshold`, `expiry_date`
- **Relationships:** Many-to-one with `categories`, one-to-many with `sale_items`
- **⚠️ DO NOT TOUCH:** Core product table

#### `categories`
- **Purpose:** Product categorization
- **Key Fields:** `id`, `name`, `description`
- **Relationships:** One-to-many with `products`
- **⚠️ DO NOT TOUCH:** Core category table

#### `customers`
- **Purpose:** Customer records
- **Key Fields:** `id`, `name`, `phone`, `email`, `address`, `credit_balance`
- **Relationships:** One-to-many with `sales`
- **⚠️ DO NOT TOUCH:** Core customer table

#### `sales`
- **Purpose:** Sales transactions
- **Key Fields:** `id`, `created_at`, `cashier_id`, `customer_id`, `subtotal`, `discount_total`, `total`, `notes`
- **Relationships:** Many-to-one with `users` (cashier), `customers`; one-to-many with `sale_items`, `payments`
- **⚠️ DO NOT TOUCH:** Core sales table

#### `sale_items`
- **Purpose:** Individual items in a sale
- **Key Fields:** `id`, `sale_id`, `product_id`, `quantity`, `unit_price`, `discount`, `line_total`
- **Relationships:** Many-to-one with `sales`, `products`
- **⚠️ DO NOT TOUCH:** Core sales items table

#### `payments`
- **Purpose:** Payment records for sales
- **Key Fields:** `id`, `sale_id`, `method` (cash/mobile_money/card/credit), `amount`
- **Relationships:** Many-to-one with `sales`
- **⚠️ DO NOT TOUCH:** Core payments table

#### `inventory_movements`
- **Purpose:** Stock change history
- **Key Fields:** `id`, `product_id`, `change_qty`, `reason`, `created_at`
- **Relationships:** Many-to-one with `products`
- **⚠️ DO NOT TOUCH:** Core inventory tracking table

#### `store_settings`
- **Purpose:** Store configuration
- **Key Fields:** `id`, `store_name`, `store_phone`, `store_location`, `notification_email`, `low_stock_email_enabled`, `default_low_stock_threshold`
- **⚠️ DO NOT TOUCH:** Core settings table

### Additional Tables (DO NOT MODIFY)
- `layby_customers`, `layby_transactions`, `layby_payments` - Layby system
- `withdrawals` - Money withdrawal tracking
- `notifications` - System notifications (low stock, expiry)
- `chart_of_accounts`, `journal_entries`, `journal_entry_lines`, `accounting_periods`, `expense_account_mappings`, `fixed_assets`, `asset_depreciation_schedules` - Accounting system

### ✅ SAFE TO ADD
- **New tables only** (no modifications to existing tables)
- Tables for WhatsApp integration
- Tables for quotations
- Tables for tenant isolation (if multi-tenant is required)

---

## 5. AUTHENTICATION & AUTHORIZATION

### Current System
- **Method:** JWT (JSON Web Tokens)
- **Flow:** OAuth2PasswordBearer
- **Token Storage:** Frontend localStorage (`pos_token`)
- **Token Expiry:** 8 hours (480 minutes)
- **Roles:** `admin`, `cashier`
- **Location:** `app/auth.py`

### Key Functions (DO NOT MODIFY)
- `authenticate_user()` - Validates username/password
- `get_current_user()` - Validates JWT token
- `get_current_active_user()` - Ensures user is active
- `get_current_admin_user()` - Ensures user is admin

### API Protection Pattern
```python
@app.get("/api/endpoint")
async def endpoint(
    current_user: User = Depends(auth.get_current_active_user)
):
    # Protected endpoint
```

### ⚠️ TENANT ISOLATION
**CRITICAL:** No tenant isolation exists. All data is shared in a single database. To add multi-tenancy:
- **Option A:** Add `tenant_id` to ALL existing tables (⚠️ BREAKS RULE - modifies existing tables)
- **Option B:** Create new tables with tenant isolation (✅ SAFE - additive only)
- **Option C:** Use separate databases per tenant (✅ SAFE - but requires infrastructure changes)

**RECOMMENDATION:** For Phase 2, design tenant isolation as a new layer without modifying existing tables.

---

## 6. API PATTERNS & CONVENTIONS

### Endpoint Structure
- **Base URL:** `/api/`
- **Authentication:** Bearer token in `Authorization` header
- **Response Format:** JSON
- **Error Format:** `{"detail": "error message"}`

### Common Endpoints (DO NOT MODIFY)
```
POST   /api/auth/token                    # Login
GET    /api/products                      # List products
POST   /api/products                      # Create product
GET    /api/products/{id}                 # Get product
PUT    /api/products/{id}                 # Update product
DELETE /api/products/{id}                 # Delete product
POST   /api/sales                         # Create sale
GET    /api/customers                     # List customers
POST   /api/customers                     # Create customer
GET    /api/store-settings                # Get settings
PUT    /api/store-settings               # Update settings
GET    /api/reports/summary               # Sales summary
GET    /api/ai/analyze                    # AI business analysis
POST   /api/ai/chat                      # AI chat (EXISTING)
```

### Frontend API Pattern
```javascript
// Standard API call pattern (app.js, admin.js, etc.)
async function api(path, options = {}) {
    const token = localStorage.getItem('pos_token');
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    if (token) {
        headers['Authorization'] = 'Bearer ' + token;
    }
    const res = await fetch(path, { ...options, headers });
    if (!res.ok) {
        if (res.status === 401) {
            // Redirect to login
            window.location.href = '/';
            return;
        }
        throw new Error(await res.text());
    }
    return res.json();
}
```

### ✅ SAFE EXTENSION POINTS
- **New endpoints:** `/api/whatsapp/*`, `/api/quotations/*`
- **New routes:** Can add new routes without modifying existing ones
- **New dependencies:** Can add new FastAPI dependencies

---

## 7. EXISTING AI INTEGRATION

### Current Implementation
- **Service:** `app/ai_service.py`
- **Integration:** Ollama (localhost:11434)
- **Model:** phi:2.7b (configurable)
- **Features:**
  - Business analysis (`/api/ai/analyze`)
  - AI chat with sales context (`/api/ai/chat`)
  - Pre-computed business data caching
  - Fallback analysis when AI unavailable

### Key Functions (CAN REUSE)
- `AIService._check_ollama_available()` - Check if Ollama is running
- `AIService._call_ollama()` - Call Ollama API
- `AIService._call_ollama_chat()` - Chat with Ollama
- `AIService.chat_with_sales_context()` - Chat with business context

### ✅ SAFE TO EXTEND
- Can reuse `AIService` class for WhatsApp chatbot
- Can add new methods to `AIService` without modifying existing ones
- Can create new AI service instances for different purposes

---

## 8. PRODUCT & PRICING LOGIC

### Product Model
- **Fields:** `name`, `barcode`, `category_id`, `stock_qty`, `cost_price`, `selling_price`, `is_active`, `low_stock_threshold`, `expiry_date`
- **Constraints:** `stock_qty >= 0` (enforced by CheckConstraint)

### Pricing Logic
- **Cost Price:** `cost_price` (Numeric 10,2)
- **Selling Price:** `selling_price` (Numeric 10,2)
- **Profit Calculation:** `selling_price - cost_price` (calculated in frontend/backend as needed)

### Stock Management
- **Stock Updates:** Via `inventory_movements` table
- **Stock Checks:** Before sale completion (prevents negative stock)
- **Low Stock:** Notifications when `stock_qty <= threshold`

### ✅ SAFE FOR QUOTATIONS
- Can read products for quotation generation
- Can calculate prices without modifying products
- Can create quotation records without affecting product stock

---

## 9. FRONTEND ARCHITECTURE

### Structure
- **No Framework:** Vanilla JavaScript
- **No Build Tools:** Direct HTML/CSS/JS files
- **No State Management:** Global variables and localStorage
- **No Routing:** Server-side routing (FastAPI templates)

### Key Files
- `static/js/app.js` - Main POS interface logic
- `static/js/admin.js` - Admin panel logic
- `static/js/layby.js` - Layby management logic
- `templates/index.html` - Main POS HTML
- `templates/admin.html` - Admin panel HTML

### Authentication Flow
1. User enters username/password
2. Frontend calls `POST /api/auth/token`
3. Token stored in `localStorage.getItem('pos_token')`
4. Token included in all subsequent API calls
5. On 401, redirect to login

### ✅ SAFE EXTENSION POINTS
- **New HTML pages:** Add to `templates/`
- **New JavaScript:** Add to `static/js/`
- **New CSS:** Add to `static/css/style.css` or new file
- **New API endpoints:** Add to `app/main.py` without modifying existing ones

---

## 10. SAFE EXTENSION POINTS

### ✅ CAN ADD (Additive Only)

#### Backend
1. **New modules:**
   - `app/whatsapp_service.py` - WhatsApp integration
   - `app/quotation_service.py` - Quotation management
   - `app/tenant_service.py` - Multi-tenant logic (if needed)

2. **New API endpoints:**
   - `/api/whatsapp/*` - WhatsApp webhook and management
   - `/api/quotations/*` - Quotation CRUD
   - `/api/tenants/*` - Tenant management (if multi-tenant)

3. **New database tables:**
   - `whatsapp_configs` - WhatsApp account configurations
   - `whatsapp_messages` - Message history
   - `quotations` - Quotation records
   - `quotation_items` - Items in quotations
   - `tenants` - Tenant records (if multi-tenant)

4. **New dependencies:**
   - WhatsApp library (e.g., `whatsapp-web.js` or `twilio`)
   - Any other required packages

#### Frontend
1. **New pages:**
   - `templates/whatsapp.html` - WhatsApp bot management
   - `templates/quotations.html` - Quotation management
   - `static/js/whatsapp.js` - WhatsApp frontend logic
   - `static/js/quotations.js` - Quotation frontend logic

2. **New UI components:**
   - WhatsApp bot status indicator
   - Quotation generation form
   - Quotation list/view

### ❌ MUST NOT TOUCH

#### Backend
- **DO NOT modify:** `app/models.py` (existing models)
- **DO NOT modify:** `app/auth.py` (authentication logic)
- **DO NOT modify:** `app/main.py` (existing endpoints)
- **DO NOT modify:** `app/database.py` (database connection)
- **DO NOT modify:** `app/config.py` (core configuration)
- **DO NOT modify:** `app/ai_service.py` (existing AI methods)

#### Database
- **DO NOT alter:** Existing tables (no ALTER TABLE on existing tables)
- **DO NOT drop:** Any existing tables
- **DO NOT rename:** Any existing columns or tables
- **DO NOT modify:** Existing foreign keys or constraints

#### Frontend
- **DO NOT modify:** Existing JavaScript files (app.js, admin.js, layby.js)
- **DO NOT modify:** Existing HTML templates (index.html, admin.html)
- **DO NOT modify:** Existing CSS (unless adding new styles)

---

## 11. EXISTING SERVICES THAT CAN BE REUSED

### ✅ Email Service (`app/email_service.py`)
- **Can reuse:** `EmailService` class for WhatsApp notifications
- **Can extend:** Add WhatsApp notification methods

### ✅ AI Service (`app/ai_service.py`)
- **Can reuse:** `AIService` class for WhatsApp chatbot
- **Can extend:** Add WhatsApp-specific chat methods
- **Already has:** Ollama integration, chat context, fallback logic

### ✅ Notification Service (`app/notification_service.py`)
- **Can reuse:** Notification creation logic
- **Can extend:** Add WhatsApp notification types

### ✅ Database Session (`app/database.py`)
- **Can reuse:** `get_db()` dependency for new endpoints
- **Can reuse:** `SessionLocal` for background tasks

### ✅ Authentication (`app/auth.py`)
- **Can reuse:** `get_current_admin_user` for WhatsApp admin endpoints
- **Can reuse:** JWT token validation

---

## 12. AREAS THAT MUST NOT BE TOUCHED

### Critical Files (READ-ONLY)
1. `app/models.py` - Core database models
2. `app/auth.py` - Authentication system
3. `app/database.py` - Database connection
4. `app/config.py` - Core configuration
5. `app/main.py` - Existing API endpoints (can add new ones)
6. `static/js/app.js` - Main POS logic
7. `static/js/admin.js` - Admin panel logic
8. `templates/index.html` - Main POS interface
9. `templates/admin.html` - Admin panel

### Critical Tables (READ-ONLY)
- All existing tables in `app/models.py`
- No ALTER TABLE statements on existing tables
- No DROP TABLE statements
- No column renames or deletions

### Critical Business Logic (READ-ONLY)
- Sale processing logic
- Stock update logic
- Payment processing
- Receipt printing
- Accounting posting
- Inventory movements

---

## 13. MULTI-TENANT CONSIDERATIONS

### Current State
- **Single-tenant system** (no tenant isolation)
- **Single database** (pos.db)
- **No tenant_id** in any tables
- **All data shared** across all users

### Requirements Analysis
User mentioned "multi-tenant POS system" but codebase shows single-tenant. Two approaches:

#### Option A: True Multi-Tenant (BREAKS RULES)
- Add `tenant_id` to ALL existing tables
- Modify ALL queries to filter by tenant
- Modify ALL API endpoints
- **❌ VIOLATES RULE:** Modifies existing tables and logic

#### Option B: Tenant Layer (SAFE)
- Create new `tenants` table
- Create new tables with `tenant_id` for new features
- Keep existing tables unchanged
- Add tenant selection/context for new features only
- **✅ SAFE:** Additive only

#### Option C: Separate Databases (SAFE but Complex)
- One database per tenant
- Tenant selection determines which database to use
- **✅ SAFE:** No modifications to existing code
- **⚠️ COMPLEX:** Requires infrastructure changes

### Recommendation for Phase 2
Design tenant isolation as a **new layer** that:
1. Adds `tenants` table (new)
2. Adds `tenant_id` to new tables only (WhatsApp, quotations)
3. Keeps existing tables unchanged
4. Adds tenant context middleware for new endpoints only
5. Allows gradual migration if needed later

---

## 14. ASSUMPTIONS & CLARIFICATIONS NEEDED

### ⚠️ TODO: Confirm with User

1. **Multi-Tenant Requirement:**
   - Is true multi-tenancy required, or is single-tenant acceptable?
   - If multi-tenant, should existing data be migrated or kept separate?

2. **WhatsApp Integration:**
   - Which WhatsApp library? (`whatsapp-web.js`, `twilio`, `baileys`, other?)
   - Should WhatsApp be per-tenant or global?
   - Should WhatsApp messages be stored in database?

3. **Quotation System:**
   - Should quotations be linked to customers?
   - Should quotations expire after a certain time?
   - Should quotations convert to sales automatically?

4. **Ollama AI:**
   - Should WhatsApp chatbot use the same Ollama instance?
   - Should chatbot have access to all business data or limited?

5. **Offline-First:**
   - Should WhatsApp work offline (queue messages)?
   - Should quotations work offline?

---

## 15. RISK ANALYSIS

### Low Risk (Safe to Proceed)
- ✅ Adding new database tables
- ✅ Adding new API endpoints
- ✅ Adding new frontend pages
- ✅ Extending existing services (new methods only)
- ✅ Adding new dependencies

### Medium Risk (Requires Care)
- ⚠️ Adding tenant isolation (must not modify existing tables)
- ⚠️ Integrating WhatsApp (external dependency, may require internet)
- ⚠️ Background tasks for WhatsApp (must not block existing tasks)

### High Risk (Must Avoid)
- ❌ Modifying existing database tables
- ❌ Modifying existing API endpoints
- ❌ Modifying existing business logic
- ❌ Breaking backward compatibility

---

## 16. SUMMARY

### System Type
- **Single-tenant** (despite user's description)
- **Offline-first** (SQLite, localhost)
- **Raspberry Pi optimized**

### Tech Stack
- **Backend:** FastAPI + SQLAlchemy + SQLite
- **Frontend:** Vanilla JavaScript + HTML + CSS
- **AI:** Ollama (already integrated)
- **Auth:** JWT with role-based access

### Safe Extension Strategy
1. **Additive only:** New tables, new endpoints, new pages
2. **Isolated modules:** WhatsApp and quotation services in separate files
3. **Reuse existing:** AI service, email service, database session
4. **No modifications:** Existing code remains untouched

### Next Steps
- **Phase 2:** Design WhatsApp chatbot, quotation system, and tenant isolation (if needed)
- **Phase 3:** Implement new features following additive-only approach

---

## END OF PHASE 1 ANALYSIS

**Status:** ✅ COMPLETE  
**Ready for Phase 2:** Design & Architecture  
**Blockers:** None (awaiting user confirmation on assumptions)

