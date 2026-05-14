"""
Simple database initializer.

Creates all tables and an initial admin user if none exists.
"""

from getpass import getpass

from sqlalchemy.orm import Session

from . import auth
from .config import STORE_NAME, STORE_PHONE, STORE_LOCATION
from .database import Base, engine, SessionLocal
from .models import StoreSettings, User


def create_admin_if_missing(db: Session) -> None:
    admin = db.query(User).filter(User.role == "admin").first()
    if admin:
        return

    print("No admin user found. Creating initial admin user.")
    username = input("Admin username [admin]: ").strip() or "admin"
    full_name = input("Full name [Administrator]: ").strip() or "Administrator"
    while True:
        password = getpass("Password: ")
        password2 = getpass("Confirm password: ")
        if password != password2:
            print("Passwords do not match, try again.")
            continue
        if not password:
            print("Password cannot be empty.")
            continue
        break

    admin = User(
        username=username,
        full_name=full_name,
        role="admin",
        password_hash=auth.get_password_hash(password),
        is_active=True,
    )
    db.add(admin)
    db.commit()
    print(f"Admin user '{username}' created.")


def create_store_settings_if_missing(db: Session) -> None:
    settings = (
        db.query(StoreSettings)
        .filter(StoreSettings.tenant_id.is_(None))
        .first()
    )
    if settings:
        return

    print("Creating default store settings...")
    settings = StoreSettings(
        store_name=STORE_NAME,
        store_phone=STORE_PHONE if STORE_PHONE else None,
        store_location=STORE_LOCATION if STORE_LOCATION else None,
        tenant_id=None,
    )
    db.add(settings)
    db.commit()
    print(f"Store settings created with name: {STORE_NAME}")


def main() -> None:
    print("Creating database tables (if not existing)...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        create_admin_if_missing(db)
        create_store_settings_if_missing(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()


