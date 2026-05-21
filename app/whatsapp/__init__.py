"""Multi-tenant WhatsApp Cloud API chatbot.

A single platform-owned WhatsApp Business number serves every tenant.
The state machine in ``router`` welcomes new customers, lets them choose
a business (numeric pick or keyword), persists the choice in a
``WhatsAppSession`` row, and dispatches subsequent messages to handlers
scoped to that tenant.

Phase 1 (this module): webhook + signature verification + welcome menu +
keyword routing + tenant-scoped product search + human handover fallback.

Phase 2 will add: OpenAI Q&A grounded on tenant catalog/KB, quotation
generation + PDF delivery via the existing quotation_service, and admin
analytics.
"""

from . import config, models, signature  # noqa: F401  (eager import for SQLAlchemy)
