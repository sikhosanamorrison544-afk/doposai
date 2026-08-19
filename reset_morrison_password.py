#!/usr/bin/env python3
"""
Interactive password reset for a named local user (no hard-coded passwords).

Prefer the general tool:

  python scripts/repair_admin_account.py --username <name> --reset-existing

This script remains as a thin interactive helper and never prints the password.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from sqlalchemy import func

    from app import auth
    from app.database import SessionLocal
    from app.models import User
    from app.security_config import WeakPasswordError, validate_bootstrap_password

    username = (input("Username to reset: ").strip() or "")
    if not username:
        print("ERROR: username is required.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(func.lower(User.username) == func.lower(username))
            .first()
        )
        if not user:
            print(f"ERROR: User '{username}' not found.", file=sys.stderr)
            print("\nAvailable usernames:")
            for u in db.query(User).all():
                print(f"  - {u.username} ({u.role})")
            return 1

        raw1 = getpass.getpass("New password: ")
        raw2 = getpass.getpass("Confirm password: ")
        if raw1 != raw2:
            print("ERROR: passwords do not match.", file=sys.stderr)
            return 2
        try:
            password = validate_bootstrap_password(raw1)
        except WeakPasswordError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

        user.password_hash = auth.get_password_hash(password)
        user.is_active = True
        db.commit()
        print(
            f"Password updated for '{user.username}' "
            f"(role={user.role}; password not shown)."
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
