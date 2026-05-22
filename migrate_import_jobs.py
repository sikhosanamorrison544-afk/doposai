#!/usr/bin/env python3
"""Create/upgrade import_jobs table (idempotent). Run: python3 migrate_import_jobs.py"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def migrate():
    from sqlalchemy import inspect, text

    from app.database import engine
    from app.models import ImportJob

    ImportJob.__table__.create(bind=engine, checkfirst=True)
    insp = inspect(engine)
    if "import_jobs" not in insp.get_table_names():
        print("Import jobs table created (import_jobs).")
        return

    existing = {c["name"] for c in insp.get_columns("import_jobs")}
    dialect = engine.dialect.name
    alters = []
    if "file_name" not in existing:
        alters.append(
            "ADD COLUMN file_name VARCHAR(255)"
            if dialect != "sqlite"
            else "ADD COLUMN file_name TEXT"
        )
    if "file_ext" not in existing:
        alters.append(
            "ADD COLUMN file_ext VARCHAR(16)"
            if dialect != "sqlite"
            else "ADD COLUMN file_ext TEXT"
        )
    if "file_bytes" not in existing:
        blob = "BYTEA" if dialect == "postgresql" else "BLOB"
        alters.append(f"ADD COLUMN file_bytes {blob}")

    if alters:
        with engine.begin() as conn:
            for clause in alters:
                conn.execute(text(f"ALTER TABLE import_jobs {clause}"))
        print(f"Import jobs table upgraded: {', '.join(alters)}")
    else:
        print("Import jobs table ready (import_jobs).")


if __name__ == "__main__":
    migrate()
