#!/usr/bin/env python3
"""Create refunds and refund_items tables. Run: python3 migrate_refunds.py"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from app.database import Base, engine  # noqa: E402
from app import models  # noqa: F401, E402
from app import accounting_models  # noqa: F401, E402
from app import enterprise_models  # noqa: F401, E402
from app.quotation_models import Tenant  # noqa: F401, E402


def migrate():
    Base.metadata.create_all(bind=engine)
    print("Refund tables ready (refunds, refund_items).")


if __name__ == "__main__":
    migrate()
