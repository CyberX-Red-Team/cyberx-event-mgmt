#!/usr/bin/env python3
"""
Encrypt existing plaintext pandas_password values in the database.

This script should be run once to migrate from plaintext to encrypted storage.
It checks each user's pandas_password and encrypts it if it's not already encrypted.

Usage:
    python scripts/encrypt_existing_passwords.py

Requirements:
    - ENCRYPTION_KEY must be set in .env (or will use SECRET_KEY)
    - Database must be accessible
    - Application must be configured
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.config import get_settings
from app.utils.encryption import init_encryptor, encrypt_field, is_field_encrypted
import base64
import hashlib


class Colors:
    """ANSI color codes."""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


async def encrypt_existing_passwords():
    """Encrypt all plaintext pandas_password values."""
    print(f"\n{Colors.BOLD}Encrypting Existing Pandas Passwords{Colors.RESET}")
    print("=" * 80)

    # Initialize encryptor
    settings = get_settings()
    encryption_key = settings.ENCRYPTION_KEY or settings.SECRET_KEY

    # Ensure key is valid Fernet format
    try:
        init_encryptor(encryption_key)
        print(f"{Colors.GREEN}✓ Encryptor initialized with provided key{Colors.RESET}")
    except Exception:
        print(f"{Colors.YELLOW}⚠ Invalid ENCRYPTION_KEY format, deriving from SECRET_KEY{Colors.RESET}")
        key_material = hashlib.sha256(encryption_key.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_material)
        init_encryptor(fernet_key.decode())
        print(f"{Colors.GREEN}✓ Encryptor initialized with derived key{Colors.RESET}")

    # Connect to database
    async with AsyncSessionLocal() as session:
        # Get all users with pandas_password set
        result = await session.execute(
            select(User).where(User._pandas_password_encrypted.isnot(None))
        )
        users = result.scalars().all()

        print(f"\nFound {len(users)} users with pandas_password set")
        print("=" * 80)

        encrypted_count = 0
        already_encrypted_count = 0
        failed_count = 0
        skipped_count = 0

        for user in users:
            password_value = user._pandas_password_encrypted

            # Skip if None or empty
            if not password_value:
                skipped_count += 1
                continue

            # Check if already encrypted
            if is_field_encrypted(password_value):
                already_encrypted_count += 1
                print(f"{Colors.BLUE}⊙ User {user.id} ({user.email}): Already encrypted{Colors.RESET}")
                continue

            # Encrypt the plaintext password
            try:
                encrypted = encrypt_field(password_value)
                user._pandas_password_encrypted = encrypted
                encrypted_count += 1
                print(f"{Colors.GREEN}✓ User {user.id} ({user.email}): Encrypted{Colors.RESET}")
            except Exception as e:
                failed_count += 1
                print(f"{Colors.RED}✗ User {user.id} ({user.email}): Failed - {e}{Colors.RESET}")

        # Commit changes
        if encrypted_count > 0:
            try:
                await session.commit()
                print(f"\n{Colors.GREEN}✓ Successfully committed {encrypted_count} encrypted passwords{Colors.RESET}")
            except Exception as e:
                await session.rollback()
                print(f"\n{Colors.RED}✗ Failed to commit changes: {e}{Colors.RESET}")
                print(f"{Colors.RED}  All changes rolled back{Colors.RESET}")
                return

    # Summary
    print("\n" + "=" * 80)
    print(f"{Colors.BOLD}Summary:{Colors.RESET}")
    print(f"  Total users checked: {len(users)}")
    print(f"  {Colors.GREEN}Encrypted: {encrypted_count}{Colors.RESET}")
    print(f"  {Colors.BLUE}Already encrypted: {already_encrypted_count}{Colors.RESET}")
    print(f"  {Colors.YELLOW}Skipped (empty): {skipped_count}{Colors.RESET}")
    print(f"  {Colors.RED}Failed: {failed_count}{Colors.RESET}")

    if encrypted_count > 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Migration completed successfully!{Colors.RESET}")
        print(f"\n{Colors.YELLOW}Note: All plaintext passwords have been encrypted.{Colors.RESET}")
        print(f"{Colors.YELLOW}The application will now automatically encrypt/decrypt passwords.{Colors.RESET}")
    elif already_encrypted_count > 0:
        print(f"\n{Colors.BLUE}{Colors.BOLD}All passwords are already encrypted.{Colors.RESET}")
    else:
        print(f"\n{Colors.YELLOW}No passwords to encrypt.{Colors.RESET}")


if __name__ == "__main__":
    asyncio.run(encrypt_existing_passwords())
