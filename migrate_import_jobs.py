#!/usr/bin/env python3
"""Create import_jobs table only (idempotent). Run: python3 migrate_import_jobs.py"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def migrate():
    from app.database import engine
    from app.models import ImportJob

    ImportJob.__table__.create(bind=engine, checkfirst=True)
    print("Import jobs table ready (import_jobs).")


if __name__ == "__main__":
    migrate()
