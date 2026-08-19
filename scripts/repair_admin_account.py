#!/usr/bin/env python3
"""
Local-only administrator recovery / bootstrap (NOT an HTTP endpoint).

Run on the server that holds the database:

  cd /path/to/pos
  source .venv/bin/activate
  python scripts/repair_admin_account.py --username admin

The script prompts for a new password via getpass (never prints it).
It refuses weak/default passwords and will not overwrite an existing
admin unless --reset-existing is passed.

This replaces the removed unauthenticated POST /api/repair-admin route.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# Allow `python scripts/repair_admin_account.py` from repo root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Secure local admin password reset / create (no HTTP exposure)."
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="Administrator username to repair (default: admin)",
    )
    parser.add_argument(
        "--create-if-missing",
        action="store_true",
        help="Create the user as role=admin if it does not exist",
    )
    parser.add_argument(
        "--reset-existing",
        action="store_true",
        help="Allow resetting the password when the user already exists",
    )
    parser.add_argument(
        "--full-name",
        default="Administrator",
        help="Full name used only when creating a missing admin",
    )
    args = parser.parse_args(argv)

    from app import auth
    from app.database import SessionLocal
    from app.models import User
    from app.security_config import WeakPasswordError, validate_bootstrap_password
    from sqlalchemy import func

    username = (args.username or "").strip()
    if not username:
        print("ERROR: username is required.", file=sys.stderr)
        return 2

    raw1 = getpass.getpass("New administrator password: ")
    raw2 = getpass.getpass("Confirm password: ")
    if raw1 != raw2:
        print("ERROR: passwords do not match.", file=sys.stderr)
        return 2

    try:
        password = validate_bootstrap_password(raw1)
    except WeakPasswordError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(func.lower(User.username) == func.lower(username))
            .first()
        )
        if user is None:
            if not args.create_if_missing:
                print(
                    f"ERROR: user '{username}' not found. "
                    "Re-run with --create-if-missing to create an admin.",
                    file=sys.stderr,
                )
                return 1
            user = User(
                username=username,
                full_name=args.full_name,
                role="admin",
                password_hash=auth.get_password_hash(password),
                is_active=True,
            )
            db.add(user)
            db.commit()
            print(f"Created administrator account '{username}' (password not shown).")
            return 0

        if not args.reset_existing:
            print(
                f"ERROR: user '{user.username}' already exists. "
                "Re-run with --reset-existing to change the password.",
                file=sys.stderr,
            )
            return 1

        user.password_hash = auth.get_password_hash(password)
        user.is_active = True
        if (user.role or "").strip().lower() not in ("admin", "owner"):
            print(
                f"NOTE: user '{user.username}' role is '{user.role}' "
                "(not changed). Use a dedicated admin account if needed."
            )
        db.commit()
        print(
            f"Updated password for user '{user.username}' "
            f"(role={user.role}, active={user.is_active}; password not shown)."
        )
        return 0
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
