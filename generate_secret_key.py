#!/usr/bin/env python3
"""
Generate a secure JWT secret key for the POS system.
Run this script and add the output to your .env file as JWT_SECRET_KEY
"""

import secrets

if __name__ == "__main__":
    secret_key = secrets.token_urlsafe(32)
    print("=" * 50)
    print("Generated JWT Secret Key:")
    print("=" * 50)
    print(secret_key)
    print("=" * 50)
    print("\nAdd this to your .env file:")
    print(f"JWT_SECRET_KEY={secret_key}")
    print("\nOr set it as an environment variable:")
    print(f"export JWT_SECRET_KEY={secret_key}")
    print("=" * 50)

