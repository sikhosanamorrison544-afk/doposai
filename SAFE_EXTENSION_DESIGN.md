# SAFE EXTENSION DESIGN
## Phase 2 - Architecture & Design Document

**Date:** 2024  
**System:** WhatsApp Chatbot + Quotation System Extension  
**Design Status:** ✅ COMPLETE

---

## 1. EXECUTIVE SUMMARY

This document outlines the **additive-only** design for adding:
1. **WhatsApp Chatbot** - Multi-tenant capable WhatsApp integration with AI-powered responses
2. **Quotation System** - Generate and manage product quotations from POS catalog
3. **Admin Panel** - Manage WhatsApp bot configuration and view quotations

All designs follow **SAFE EXTENSION MODE** principles:
- ✅ New modules only (no modifications to existing code)
- ✅ New database tables only (no ALTER TABLE on existing tables)
- ✅ New API endpoints only (no modifications to existing endpoints)
- ✅ New UI pages only (no modifications to existing pages)
- ✅ Feature flags for gradual rollout
- ✅ Offline-first design

---

## 2. HIGH-LEVEL ARCHITECTURE OVERLAY

### 2.1 System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    EXISTING POS SYSTEM                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   FastAPI    │  │   SQLite     │  │   Ollama AI  │      │
│  │   Backend    │  │   Database   │  │   Service    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ (NEW ADDITIONS - ADDITIVE ONLY)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              NEW EXTENSION LAYER (ADDITIVE)                   │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         WhatsApp Service Module                      │   │
│  │  ┌──────────────┐  ┌──────────────┐                │   │
│  │  │ WhatsApp     │  │ Message      │                │   │
│  │  │ Client       │  │ Handler      │                │   │
│  │  │ (whatsapp-   │  │ (routes to   │                │   │
│  │  │  web.js)     │  │  AI/Catalog) │                │   │
│  │  └──────────────┘  └──────────────┘                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Quotation Service Module                      │   │
│  │  ┌──────────────┐  ┌──────────────┐                │   │
│  │  │ Quotation    │  │ Quotation    │                │   │
│  │  │ Generator    │  │ Manager     │                │   │
│  │  │ (from POS    │  │ (CRUD ops)   │                │   │
│  │  │  catalog)    │  │              │                │   │
│  │  └──────────────┘  └──────────────┘                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         AI Integration Layer                          │   │
│  │  ┌──────────────┐  ┌──────────────┐                │   │
│  │  │ WhatsApp AI  │  │ Quotation    │                │   │
│  │  │ Chat Handler │  │ AI Assistant │                │   │
│  │  │ (reuses      │  │ (suggests    │                │   │
│  │  │  Ollama)     │  │  products)   │                │   │
│  │  └──────────────┘  └──────────────┘                │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ (NEW DATABASE TABLES)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              NEW DATABASE TABLES (ADDITIVE)                  │
│  • whatsapp_configs    (tenant WhatsApp settings)           │
│  • whatsapp_messages   (message history)                     │
│  • quotations          (quotation records)                  │
│  • quotation_items     (items in quotations)                │
│  • tenants             (optional: multi-tenant support)      │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

#### WhatsApp Message Flow
```
WhatsApp User → WhatsApp Client → Message Handler → AI Service (Ollama) → Response → WhatsApp User
                                      │
                                      ├─→ Product Catalog Search
                                      ├─→ Quotation Generation
                                      └─→ Database (message history)
```

#### Quotation Generation Flow
```
Admin/Chatbot → Quotation Service → Product Catalog → Calculate Prices → Generate PDF → Store in DB
```

---

## 3. NEW MODULES (ADDITIVE ONLY)

### 3.1 WhatsApp Service Module

**File:** `app/whatsapp_service.py` (NEW)

**Purpose:** Handle WhatsApp integration, message routing, and bot responses

**Key Components:**
```python
class WhatsAppService:
    """WhatsApp bot service - handles connection, messages, and routing"""
    
    def __init__(self, db: Session, tenant_id: Optional[int] = None):
        # Initialize WhatsApp client (whatsapp-web.js or baileys)
        # Load tenant configuration
        pass
    
    async def start_client(self, config: WhatsAppConfig) -> bool:
        """Start WhatsApp client for a tenant"""
        pass
    
    async def stop_client(self, tenant_id: int) -> bool:
        """Stop WhatsApp client for a tenant"""
        pass
    
    async def send_message(self, phone: str, message: str) -> bool:
        """Send message to WhatsApp user"""
        pass
    
    async def handle_incoming_message(self, message: dict) -> None:
        """Route incoming message to appropriate handler"""
        # Route to:
        # - AI chat handler (general questions)
        # - Product search handler (product queries)
        # - Quotation handler (quotation requests)
        pass
    
    async def process_ai_chat(self, user_message: str, context: dict) -> str:
        """Process chat message using Ollama AI"""
        # Reuse existing AIService
        pass
    
    async def search_products(self, query: str) -> List[dict]:
        """Search products from POS catalog"""
        pass
    
    async def generate_quotation_via_chat(self, phone: str, items: List[dict]) -> str:
        """Generate quotation from chat and send to user"""
        pass
```

**Dependencies:**
- `whatsapp-web.js` (Node.js) OR `baileys` (Python) OR `twilio` (cloud)
- Existing `AIService` from `app/ai_service.py`
- Existing `Product` model (read-only)

**Integration Points:**
- ✅ Reuses `AIService.chat_with_sales_context()` for AI responses
- ✅ Reads from `Product` table (no modifications)
- ✅ Writes to new `whatsapp_messages` table
- ✅ Reads from new `whatsapp_configs` table

---

### 3.2 Quotation Service Module

**File:** `app/quotation_service.py` (NEW)

**Purpose:** Generate, manage, and convert quotations

**Key Components:**
```python
class QuotationService:
    """Quotation management service"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_quotation(
        self,
        customer_id: Optional[int],
        customer_name: Optional[str],
        customer_phone: Optional[str],
        items: List[dict],
        valid_until: Optional[datetime],
        notes: Optional[str]
    ) -> Quotation:
        """Create a new quotation from product catalog"""
        # Validate products exist
        # Calculate totals
        # Create quotation record
        pass
    
    def get_quotation(self, quotation_id: int) -> Optional[Quotation]:
        """Get quotation by ID"""
        pass
    
    def list_quotations(
        self,
        customer_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Quotation]:
        """List quotations with filters"""
        pass
    
    def convert_to_sale(self, quotation_id: int, cashier_id: int) -> Sale:
        """Convert quotation to actual sale"""
        # Create sale from quotation
        # Mark quotation as converted
        # Update stock
        pass
    
    def generate_pdf(self, quotation_id: int) -> bytes:
        """Generate PDF quotation document"""
        # Use reportlab (already in requirements)
        pass
    
    def expire_quotations(self) -> int:
        """Mark expired quotations (background task)"""
        pass
```

**Dependencies:**
- Existing `Product` model (read-only)
- Existing `Customer` model (read-only, optional)
- Existing `Sale` model (for conversion)
- `reportlab` (already in requirements.txt)

**Integration Points:**
- ✅ Reads from `Product` table (no modifications)
- ✅ Optionally links to `Customer` table (read-only)
- ✅ Creates `Sale` records (uses existing sale creation logic)
- ✅ Writes to new `quotations` and `quotation_items` tables

---

### 3.3 WhatsApp AI Chat Handler

**File:** `app/whatsapp_ai_handler.py` (NEW)

**Purpose:** Handle AI-powered chat responses via WhatsApp

**Key Components:**
```python
class WhatsAppAIHandler:
    """AI chat handler for WhatsApp messages"""
    
    def __init__(self, db: Session, ai_service: AIService):
        self.db = db
        self.ai_service = ai_service
    
    async def process_message(self, phone: str, message: str) -> str:
        """Process WhatsApp message and return AI response"""
        # Detect intent:
        # - Product inquiry
        # - Business question (revenue, profit, etc.)
        # - Quotation request
        # - General chat
        
        # Route to appropriate handler
        pass
    
    def _detect_intent(self, message: str) -> str:
        """Detect user intent from message"""
        # Returns: 'product_search', 'business_query', 'quotation', 'chat'
        pass
    
    async def _handle_product_inquiry(self, message: str) -> str:
        """Handle product search/inquiry"""
        pass
    
    async def _handle_business_query(self, message: str) -> str:
        """Handle business questions using existing AI service"""
        # Reuse AIService.chat_with_sales_context()
        pass
    
    async def _handle_quotation_request(self, message: str, phone: str) -> str:
        """Handle quotation generation request"""
        pass
```

**Integration Points:**
- ✅ Reuses `AIService` from `app/ai_service.py`
- ✅ No modifications to existing AI service
- ✅ Extends AI capabilities for WhatsApp context

---

## 4. DATABASE ADDITIONS (NEW TABLES ONLY)

### 4.1 WhatsApp Configuration Table

**Table:** `whatsapp_configs` (NEW)

**Purpose:** Store WhatsApp account configurations per tenant

**Schema:**
```sql
CREATE TABLE whatsapp_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,  -- NULL for single-tenant, or foreign key to tenants table
    phone_number TEXT NOT NULL,  -- WhatsApp phone number
    session_path TEXT,  -- Path to WhatsApp session files
    is_active BOOLEAN DEFAULT 0,  -- Is this WhatsApp account active?
    qr_code TEXT,  -- QR code for initial setup (temporary)
    last_connected_at DATETIME,  -- Last successful connection
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, phone_number)
);
```

**Indexes:**
- `idx_whatsapp_configs_tenant` ON `whatsapp_configs(tenant_id)`
- `idx_whatsapp_configs_active` ON `whatsapp_configs(is_active)`

**Multi-Tenant Support:**
- `tenant_id` is nullable (NULL = single-tenant/default)
- If multi-tenant is needed later, add `tenants` table and make `tenant_id` a foreign key

---

### 4.2 WhatsApp Messages Table

**Table:** `whatsapp_messages` (NEW)

**Purpose:** Store message history for audit and context

**Schema:**
```sql
CREATE TABLE whatsapp_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,  -- NULL for single-tenant
    config_id INTEGER NOT NULL,  -- Foreign key to whatsapp_configs
    phone_number TEXT NOT NULL,  -- Sender/receiver phone number
    direction TEXT NOT NULL,  -- 'inbound' or 'outbound'
    message_text TEXT NOT NULL,
    message_type TEXT DEFAULT 'text',  -- 'text', 'image', 'document', etc.
    ai_processed BOOLEAN DEFAULT 0,  -- Was this processed by AI?
    quotation_id INTEGER,  -- If message is related to a quotation
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (config_id) REFERENCES whatsapp_configs(id),
    FOREIGN KEY (quotation_id) REFERENCES quotations(id)
);
```

**Indexes:**
- `idx_whatsapp_messages_phone` ON `whatsapp_messages(phone_number, created_at)`
- `idx_whatsapp_messages_config` ON `whatsapp_messages(config_id, created_at)`
- `idx_whatsapp_messages_quotation` ON `whatsapp_messages(quotation_id)`

---

### 4.3 Quotations Table

**Table:** `quotations` (NEW)

**Purpose:** Store quotation records

**Schema:**
```sql
CREATE TABLE quotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,  -- NULL for single-tenant
    quotation_number TEXT UNIQUE NOT NULL,  -- Unique quotation number (e.g., Q-2024-001)
    customer_id INTEGER,  -- Optional: link to existing customer
    customer_name TEXT,  -- Customer name (if not in customers table)
    customer_phone TEXT,  -- Customer phone (for WhatsApp delivery)
    customer_email TEXT,  -- Customer email (optional)
    subtotal NUMERIC(10, 2) NOT NULL,
    discount_total NUMERIC(10, 2) DEFAULT 0,
    tax_total NUMERIC(10, 2) DEFAULT 0,
    total NUMERIC(10, 2) NOT NULL,
    status TEXT DEFAULT 'draft',  -- 'draft', 'sent', 'accepted', 'rejected', 'expired', 'converted'
    valid_until DATETIME,  -- Quotation expiry date
    notes TEXT,  -- Additional notes
    created_by INTEGER,  -- User ID who created (foreign key to users.id)
    converted_to_sale_id INTEGER,  -- If converted to sale (foreign key to sales.id)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (converted_to_sale_id) REFERENCES sales(id)
);
```

**Indexes:**
- `idx_quotations_number` ON `quotations(quotation_number)`
- `idx_quotations_customer` ON `quotations(customer_id)`
- `idx_quotations_status` ON `quotations(status, created_at)`
- `idx_quotations_valid_until` ON `quotations(valid_until)` (for expiry checks)

**Multi-Tenant Support:**
- `tenant_id` is nullable (NULL = single-tenant/default)

---

### 4.4 Quotation Items Table

**Table:** `quotation_items` (NEW)

**Purpose:** Store items in a quotation

**Schema:**
```sql
CREATE TABLE quotation_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,  -- Foreign key to products.id
    product_name TEXT NOT NULL,  -- Snapshot of product name (for historical reference)
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,  -- Snapshot of selling price
    discount NUMERIC(10, 2) DEFAULT 0,
    line_total NUMERIC(10, 2) NOT NULL,
    notes TEXT,  -- Item-specific notes
    FOREIGN KEY (quotation_id) REFERENCES quotations(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
```

**Indexes:**
- `idx_quotation_items_quotation` ON `quotation_items(quotation_id)`
- `idx_quotation_items_product` ON `quotation_items(product_id)`

**Note:** Product snapshots (name, price) are stored to preserve historical data even if product is deleted or price changes.

---

### 4.5 Tenants Table (Optional - For Future Multi-Tenant)

**Table:** `tenants` (NEW, OPTIONAL)

**Purpose:** Support multi-tenant architecture (if needed in future)

**Schema:**
```sql
CREATE TABLE tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,  -- Tenant/store name
    phone TEXT,  -- Contact phone
    email TEXT,  -- Contact email
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Note:** This table is **optional** and only needed if true multi-tenancy is required. For single-tenant, all `tenant_id` fields remain NULL.

---

## 5. API CONTRACTS (NEW ENDPOINTS ONLY)

### 5.1 WhatsApp Management Endpoints

#### 5.1.1 Get WhatsApp Configuration
```
GET /api/whatsapp/config
Authorization: Bearer <admin_token>

Response:
{
    "id": 1,
    "tenant_id": null,
    "phone_number": "+1234567890",
    "is_active": true,
    "last_connected_at": "2024-01-15T10:30:00",
    "created_at": "2024-01-01T00:00:00"
}
```

#### 5.1.2 Create/Update WhatsApp Configuration
```
POST /api/whatsapp/config
PUT /api/whatsapp/config/{id}
Authorization: Bearer <admin_token>

Request Body:
{
    "phone_number": "+1234567890",
    "is_active": true
}

Response:
{
    "id": 1,
    "phone_number": "+1234567890",
    "is_active": true,
    "qr_code": "data:image/png;base64,..."  // Only on initial setup
}
```

#### 5.1.3 Get QR Code for Setup
```
GET /api/whatsapp/qr-code
Authorization: Bearer <admin_token>

Response:
{
    "qr_code": "data:image/png;base64,...",
    "expires_at": "2024-01-15T10:35:00"
}
```

#### 5.1.4 Start/Stop WhatsApp Client
```
POST /api/whatsapp/start
POST /api/whatsapp/stop
Authorization: Bearer <admin_token>

Response:
{
    "success": true,
    "message": "WhatsApp client started successfully"
}
```

#### 5.1.5 Get WhatsApp Status
```
GET /api/whatsapp/status
Authorization: Bearer <admin_token>

Response:
{
    "is_connected": true,
    "phone_number": "+1234567890",
    "last_connected_at": "2024-01-15T10:30:00",
    "unread_messages": 5
}
```

#### 5.1.6 Send Test Message
```
POST /api/whatsapp/send-test
Authorization: Bearer <admin_token>

Request Body:
{
    "phone_number": "+1234567890",
    "message": "Test message"
}

Response:
{
    "success": true,
    "message_id": "msg_123"
}
```

#### 5.1.7 Get Message History
```
GET /api/whatsapp/messages?phone_number=+1234567890&limit=50
Authorization: Bearer <admin_token>

Response:
{
    "messages": [
        {
            "id": 1,
            "phone_number": "+1234567890",
            "direction": "inbound",
            "message_text": "Hello",
            "created_at": "2024-01-15T10:30:00"
        },
        ...
    ],
    "total": 100
}
```

---

### 5.2 Quotation Management Endpoints

#### 5.2.1 Create Quotation
```
POST /api/quotations
Authorization: Bearer <admin_token>

Request Body:
{
    "customer_id": 1,  // Optional
    "customer_name": "John Doe",  // Required if customer_id not provided
    "customer_phone": "+1234567890",  // Optional
    "customer_email": "john@example.com",  // Optional
    "items": [
        {
            "product_id": 1,
            "quantity": 2,
            "unit_price": 10.00,  // Optional, uses product selling_price if not provided
            "discount": 0
        }
    ],
    "valid_until": "2024-02-15T00:00:00",  // Optional
    "notes": "Special pricing for bulk order"
}

Response:
{
    "id": 1,
    "quotation_number": "Q-2024-001",
    "customer_name": "John Doe",
    "total": 20.00,
    "status": "draft",
    "created_at": "2024-01-15T10:30:00"
}
```

#### 5.2.2 Get Quotation
```
GET /api/quotations/{id}
Authorization: Bearer <admin_token>

Response:
{
    "id": 1,
    "quotation_number": "Q-2024-001",
    "customer_id": 1,
    "customer_name": "John Doe",
    "customer_phone": "+1234567890",
    "subtotal": 20.00,
    "discount_total": 0,
    "total": 20.00,
    "status": "sent",
    "valid_until": "2024-02-15T00:00:00",
    "items": [
        {
            "id": 1,
            "product_id": 1,
            "product_name": "Product A",
            "quantity": 2,
            "unit_price": 10.00,
            "line_total": 20.00
        }
    ],
    "created_at": "2024-01-15T10:30:00"
}
```

#### 5.2.3 List Quotations
```
GET /api/quotations?customer_id=1&status=sent&limit=50
Authorization: Bearer <admin_token>

Response:
{
    "quotations": [
        {
            "id": 1,
            "quotation_number": "Q-2024-001",
            "customer_name": "John Doe",
            "total": 20.00,
            "status": "sent",
            "created_at": "2024-01-15T10:30:00"
        },
        ...
    ],
    "total": 100
}
```

#### 5.2.4 Update Quotation
```
PUT /api/quotations/{id}
Authorization: Bearer <admin_token>

Request Body:
{
    "items": [...],  // Updated items
    "notes": "Updated notes",
    "valid_until": "2024-02-20T00:00:00"
}

Response:
{
    "id": 1,
    "quotation_number": "Q-2024-001",
    "total": 25.00,  // Updated total
    ...
}
```

#### 5.2.5 Delete Quotation
```
DELETE /api/quotations/{id}
Authorization: Bearer <admin_token>

Response: 204 No Content
```

#### 5.2.6 Convert Quotation to Sale
```
POST /api/quotations/{id}/convert-to-sale
Authorization: Bearer <admin_token>

Request Body:
{
    "payments": [
        {"method": "cash", "amount": 20.00}
    ]
}

Response:
{
    "sale_id": 123,
    "quotation_id": 1,
    "message": "Quotation converted to sale successfully"
}
```

#### 5.2.7 Send Quotation via WhatsApp
```
POST /api/quotations/{id}/send-whatsapp
Authorization: Bearer <admin_token>

Request Body:
{
    "phone_number": "+1234567890"  // Optional, uses quotation customer_phone if not provided
}

Response:
{
    "success": true,
    "message": "Quotation sent via WhatsApp",
    "whatsapp_message_id": 456
}
```

#### 5.2.8 Download Quotation PDF
```
GET /api/quotations/{id}/pdf
Authorization: Bearer <admin_token>

Response: PDF file (application/pdf)
```

---

### 5.3 WhatsApp Chat Endpoints (Internal)

#### 5.3.1 Webhook for Incoming Messages
```
POST /api/whatsapp/webhook
Authorization: Bearer <webhook_secret>  // Different auth for webhook

Request Body:
{
    "phone_number": "+1234567890",
    "message": "Hello, what products do you have?",
    "message_id": "msg_123",
    "timestamp": "2024-01-15T10:30:00"
}

Response:
{
    "success": true,
    "response": "We have various products available. What are you looking for?",
    "ai_processed": true
}
```

**Note:** This endpoint is called by WhatsApp client library, not directly by users.

---

## 6. UI ADDITIONS (NEW PAGES ONLY)

### 6.1 WhatsApp Management Page

**File:** `templates/whatsapp.html` (NEW)

**Purpose:** Admin interface for managing WhatsApp bot

**Features:**
- View WhatsApp connection status
- Display QR code for initial setup
- Start/Stop WhatsApp client
- View message history
- Send test messages
- Configure WhatsApp settings

**UI Components:**
- Connection status indicator (green/red)
- QR code display (for initial setup)
- Start/Stop button
- Message history table
- Test message form
- Settings form

**JavaScript:** `static/js/whatsapp.js` (NEW)

---

### 6.2 Quotation Management Page

**File:** `templates/quotations.html` (NEW)

**Purpose:** Admin interface for managing quotations

**Features:**
- List all quotations (with filters)
- Create new quotation
- View quotation details
- Edit quotation (before sending)
- Send quotation via WhatsApp/Email
- Convert quotation to sale
- Download quotation PDF
- Delete quotation

**UI Components:**
- Quotation list table (with status filters)
- Create quotation form (product search, quantity, pricing)
- Quotation detail view
- Send quotation modal
- Convert to sale modal

**JavaScript:** `static/js/quotations.js` (NEW)

---

### 6.3 Admin Panel Integration

**Modification:** Add navigation links to admin panel

**File:** `templates/admin.html` (MINOR ADDITION - navigation only)

**Changes:**
- Add "WhatsApp Bot" button/link (opens WhatsApp management page)
- Add "Quotations" button/link (opens quotations page)

**Note:** Only adds navigation, no modifications to existing admin functionality.

---

## 7. FEATURE FLAGS

### 7.1 Configuration

**File:** `app/config.py` (ADDITIVE - new constants only)

```python
# Feature flags for new extensions
WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"
QUOTATIONS_ENABLED = os.getenv("QUOTATIONS_ENABLED", "false").lower() == "true"
MULTI_TENANT_ENABLED = os.getenv("MULTI_TENANT_ENABLED", "false").lower() == "true"
```

### 7.2 Usage

- Check feature flags before enabling endpoints
- Allow gradual rollout
- Easy to disable if issues arise

---

## 8. OFFLINE-FIRST DESIGN

### 8.1 WhatsApp Message Queue

**Design:** Queue messages when WhatsApp is offline

**Implementation:**
- Store outbound messages in `whatsapp_messages` table with `status='pending'`
- Background task processes queue when WhatsApp is online
- Retry failed messages

### 8.2 Quotation Generation

**Design:** Quotations work completely offline

**Implementation:**
- All product data is in local SQLite database
- PDF generation uses local `reportlab` library
- No external API calls required

### 8.3 AI Integration

**Design:** AI works offline (Ollama is local)

**Implementation:**
- Ollama runs on localhost (already configured)
- No internet required for AI responses
- Fallback to rule-based responses if Ollama unavailable

---

## 9. RISK ANALYSIS & MITIGATION

### 9.1 High Risks

#### Risk: WhatsApp Library Dependency
**Description:** WhatsApp integration requires external library (whatsapp-web.js, baileys, or twilio)

**Mitigation:**
- Use feature flag to disable if library unavailable
- Provide multiple library options (whatsapp-web.js for Node.js, baileys for Python)
- Fallback to manual message sending if automated fails
- Document library installation separately

#### Risk: WhatsApp Account Ban
**Description:** WhatsApp may ban accounts using automation

**Mitigation:**
- Use official WhatsApp Business API (Twilio) if possible
- Implement rate limiting
- Add warnings in documentation
- Provide manual fallback

#### Risk: Database Schema Conflicts
**Description:** New tables might conflict with future migrations

**Mitigation:**
- Use unique table names (prefixed with feature name)
- Document all new tables clearly
- Use migration scripts (like existing migrations)
- Test migrations on copy of production database

### 9.2 Medium Risks

#### Risk: AI Response Quality
**Description:** Ollama AI might give incorrect product information

**Mitigation:**
- Validate AI responses against actual product catalog
- Provide fallback to direct product search
- Allow admin to review/correct AI responses
- Log all AI responses for review

#### Risk: Quotation Expiry Logic
**Description:** Expired quotations might cause confusion

**Mitigation:**
- Clear status indicators (expired quotations marked clearly)
- Auto-expire quotations via background task
- Prevent conversion of expired quotations
- Send expiry notifications

#### Risk: Performance Impact
**Description:** New features might slow down existing system

**Mitigation:**
- Use background tasks for heavy operations
- Index all new database tables properly
- Monitor query performance
- Use feature flags to disable if needed

### 9.3 Low Risks

#### Risk: UI Inconsistency
**Description:** New pages might not match existing design

**Mitigation:**
- Reuse existing CSS classes
- Follow existing UI patterns
- Test on same devices (Raspberry Pi, 7-inch screen)

#### Risk: Documentation Gaps
**Description:** New features might not be well documented

**Mitigation:**
- Create separate documentation files
- Include setup instructions
- Document API endpoints
- Provide usage examples

---

## 10. DEPENDENCY INJECTION

### 10.1 Service Initialization

**Pattern:** Initialize services in `app/main.py` startup

```python
# In app/main.py (ADDITIVE - new code only)
from .whatsapp_service import WhatsAppService
from .quotation_service import QuotationService

# Initialize services (lazy loading)
whatsapp_service: Optional[WhatsAppService] = None
quotation_service: Optional[QuotationService] = None

@app.on_event("startup")
async def startup_event():
    # ... existing startup code ...
    
    # Initialize new services if enabled
    if WHATSAPP_ENABLED:
        global whatsapp_service
        whatsapp_service = WhatsAppService(SessionLocal())
    
    if QUOTATIONS_ENABLED:
        global quotation_service
        quotation_service = QuotationService(SessionLocal())
```

### 10.2 Dependency Injection in Endpoints

**Pattern:** Use FastAPI dependencies

```python
from fastapi import Depends
from .whatsapp_service import get_whatsapp_service

def get_whatsapp_service(db: Session = Depends(get_db)) -> WhatsAppService:
    return WhatsAppService(db)

@app.post("/api/whatsapp/send-test")
async def send_test_message(
    service: WhatsAppService = Depends(get_whatsapp_service),
    current_admin: User = Depends(auth.get_current_admin_user)
):
    # Use service
    pass
```

---

## 11. INTEGRATION TESTS

### 11.1 Test Structure

**File:** `tests/test_whatsapp.py` (NEW)
**File:** `tests/test_quotations.py` (NEW)

**Test Cases:**

#### WhatsApp Tests
- Test WhatsApp client connection
- Test message sending
- Test message receiving
- Test AI response generation
- Test product search via WhatsApp
- Test quotation generation via WhatsApp

#### Quotation Tests
- Test quotation creation
- Test quotation retrieval
- Test quotation conversion to sale
- Test quotation PDF generation
- Test quotation expiry
- Test quotation filtering

### 11.2 Test Database

**Design:** Use separate test database

**Implementation:**
- Create `pos_test.db` for tests
- Initialize test database with schema
- Clean up after each test

---

## 12. ROLLBACK STRATEGY

### 12.1 Feature Flags

**Strategy:** Disable features via environment variables

```bash
# Disable WhatsApp
export WHATSAPP_ENABLED=false

# Disable Quotations
export QUOTATIONS_ENABLED=false
```

### 12.2 Database Rollback

**Strategy:** New tables can be dropped if needed

```sql
-- Rollback script (if needed)
DROP TABLE IF EXISTS quotation_items;
DROP TABLE IF EXISTS quotations;
DROP TABLE IF EXISTS whatsapp_messages;
DROP TABLE IF EXISTS whatsapp_configs;
DROP TABLE IF EXISTS tenants;  -- If created
```

**Note:** Since no existing tables are modified, rollback is safe.

### 12.3 Code Rollback

**Strategy:** Remove new files and endpoints

**Steps:**
1. Remove new Python modules (`app/whatsapp_service.py`, etc.)
2. Remove new API endpoints from `app/main.py`
3. Remove new HTML templates
4. Remove new JavaScript files
5. Drop new database tables (if needed)

**Note:** Existing code remains untouched, so rollback is straightforward.

---

## 13. IMPLEMENTATION PHASES

### Phase 3.1: Database Setup
- Create migration scripts for new tables
- Run migrations
- Verify database schema

### Phase 3.2: Backend Services
- Implement `WhatsAppService`
- Implement `QuotationService`
- Implement `WhatsAppAIHandler`
- Add API endpoints

### Phase 3.3: Frontend
- Create WhatsApp management page
- Create Quotation management page
- Add navigation links
- Implement JavaScript logic

### Phase 3.4: Integration
- Integrate WhatsApp with AI service
- Integrate quotations with POS catalog
- Test end-to-end flows

### Phase 3.5: Testing & Documentation
- Write integration tests
- Create user documentation
- Create setup guides

---

## 14. ASSUMPTIONS & DECISIONS

### 14.1 WhatsApp Library Choice

**Decision:** Support multiple options, default to `whatsapp-web.js` (Node.js) or `baileys` (Python)

**Rationale:**
- `whatsapp-web.js` is most popular and well-maintained
- `baileys` is pure Python (no Node.js dependency)
- Allow admin to choose based on their preference

**TODO:** Confirm with user which library to use.

### 14.2 Multi-Tenant Support

**Decision:** Design for multi-tenant but implement as single-tenant initially

**Rationale:**
- User mentioned "multi-tenant" but system is currently single-tenant
- Adding `tenant_id` to new tables allows future multi-tenant without breaking changes
- NULL `tenant_id` = single-tenant mode

**TODO:** Confirm if multi-tenant is actually needed.

### 14.3 Quotation Expiry

**Decision:** Quotations expire after configurable period (default 30 days)

**Rationale:**
- Prevents stale quotations
- Encourages timely conversion
- Configurable per quotation

### 14.4 AI Integration

**Decision:** Reuse existing `AIService` for WhatsApp chatbot

**Rationale:**
- Ollama is already integrated
- Existing AI service has business context
- No need to duplicate AI logic

---

## 15. OPEN QUESTIONS (TODO)

1. **WhatsApp Library:** Which library should we use?
   - `whatsapp-web.js` (Node.js) - Most popular
   - `baileys` (Python) - Pure Python, no Node.js
   - `twilio` (Cloud) - Official API, paid

2. **Multi-Tenant:** Is true multi-tenancy required?
   - If yes, should we add `tenants` table now?
   - If no, can we keep `tenant_id` as NULL?

3. **WhatsApp Setup:** How should admins connect WhatsApp?
   - QR code scan (whatsapp-web.js/baileys)
   - API credentials (Twilio)
   - Manual phone number entry

4. **Quotation Delivery:** How should quotations be delivered?
   - WhatsApp only
   - Email only
   - Both (user choice)

5. **Offline Queue:** Should WhatsApp messages queue when offline?
   - Yes (recommended for offline-first)
   - No (fail immediately)

---

## END OF PHASE 2 DESIGN

**Status:** ✅ COMPLETE  
**Ready for Phase 3:** Implementation  
**Blockers:** Answers to open questions (Section 15)

**Next Steps:**
1. Review design document
2. Answer open questions
3. Approve design
4. Proceed to Phase 3 (Implementation)

