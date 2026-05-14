#!/usr/bin/env python3
"""
Test script for email configuration.
Run this to verify your SMTP settings are working.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ Loaded .env file (if present)")
except ImportError:
    print("ℹ python-dotenv not installed (optional)")

from app.email_service import email_service

def test_email_config():
    """Test email configuration."""
    print("\n" + "="*50)
    print("Email Configuration Test")
    print("="*50)
    
    # Check configuration
    print(f"\nSMTP Host: {email_service.smtp_host}")
    print(f"SMTP Port: {email_service.smtp_port}")
    print(f"SMTP User: {email_service.smtp_user or '(not set)'}")
    print(f"SMTP Password: {'*' * len(email_service.smtp_password) if email_service.smtp_password else '(not set)'}")
    print(f"Use TLS: {email_service.smtp_use_tls}")
    print(f"From Email: {email_service.from_email or '(not set)'}")
    
    if not email_service.is_configured():
        print("\n❌ Email service is NOT configured!")
        print("\nPlease set the following environment variables:")
        print("  export SMTP_HOST=smtp.gmail.com")
        print("  export SMTP_PORT=587")
        print("  export SMTP_USER=your-email@gmail.com")
        print("  export SMTP_PASSWORD=your-app-password")
        print("\nOr create a .env file with these variables.")
        return False
    
    print("\n✓ Email service is configured")
    
    # Get test email from user
    test_email = input("\nEnter test email address (or press Enter to skip): ").strip()
    if not test_email:
        print("Skipping email send test.")
        return True
    
    # Ask user which type of email to test
    print("\nSelect email type:")
    print("1) Single product alert (old format)")
    print("2) Batch alert with multiple products (new format)")
    choice = input("Enter choice (1 or 2, default 2): ").strip() or "2"
    
    if choice == "1":
        # Send single product test email
        print(f"\nSending single product test email to {test_email}...")
        success = email_service.send_low_stock_alert(
            to_email=test_email,
            product_name="Test Product",
            current_stock=5.0,
            threshold=10.0,
            store_name="Test Store"
        )
    else:
        # Send batch test email with multiple products
        print(f"\nSending batch test email to {test_email}...")
        test_products = [
            {"name": "Lithium Battery", "current_stock": 3.0, "threshold": 5.0},
            {"name": "Phone Charger", "current_stock": 2.0, "threshold": 5.0},
            {"name": "USB Cable", "current_stock": 4.0, "threshold": 5.0},
            {"name": "Power Bank", "current_stock": 1.0, "threshold": 5.0},
        ]
        success = email_service.send_low_stock_batch_alert(
            to_email=test_email,
            products=test_products,
            store_name="Test Store"
        )
    
    if success:
        print("\n✅ Email sent successfully!")
        print(f"Check your inbox at {test_email}")
        return True
    else:
        print("\n❌ Email failed to send.")
        print("Check your SMTP configuration and server logs.")
        return False

if __name__ == "__main__":
    try:
        test_email_config()
    except KeyboardInterrupt:
        print("\n\nTest cancelled.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

