#!/usr/bin/env python3
"""
Reset password for user 'morrison'
Run this script to reset the password for the morrison admin account.
"""

from app.database import SessionLocal
from app.models import User
from app import auth

def reset_password():
    db = SessionLocal()
    try:
        # Find the morrison user (case-insensitive search)
        from sqlalchemy import func
        user = db.query(User).filter(func.lower(User.username) == "morrison").first()
        
        if not user:
            print("ERROR: User 'morrison' not found in database.")
            print("\nAvailable users:")
            users = db.query(User).all()
            for u in users:
                print(f"  - {u.username} ({u.role})")
            return
        
        # Reset password to 'morrison'
        new_password = "morrison"
        user.password_hash = auth.get_password_hash(new_password)
        user.is_active = True
        db.commit()
        
        print(f"✓ Password reset successfully for user '{user.username}'")
        print(f"  Username: {user.username} (or 'morrison' - login is case-insensitive)")
        print(f"  New Password: {new_password}")
        print(f"\nYou can now log in with:")
        print(f"  Username: {user.username.lower()} (or any case variation)")
        print(f"  Password: {new_password}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reset_password()

