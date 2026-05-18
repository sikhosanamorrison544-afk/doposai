#!/usr/bin/env python3
"""Create subscriptions, subscription_payments, billing_logs tables."""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, inspect, text

from app.config import DATABASE_URL
from app.database import Base

import app.billing.models  # noqa: F401 — register tables


def main() -> int:
    engine = create_engine(DATABASE_URL)
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    needed = {"subscriptions", "subscription_payments", "billing_logs"}
    missing = needed - existing
    if not missing:
        print("Billing tables already exist.")
        return 0
    print("Creating billing tables:", ", ".join(sorted(missing)))
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Base.metadata.tables["subscriptions"],
            Base.metadata.tables["subscription_payments"],
            Base.metadata.tables["billing_logs"],
        ],
    )
    try:
        from alembic.config import Config
        from alembic import command

        command.stamp(Config("alembic.ini"), "head")
        print("Stamped Alembic revision to head.")
    except Exception as exc:
        print("Note: could not stamp Alembic (tables still created):", exc)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
