#!/usr/bin/env python3
"""
Verify that password encryption is working correctly.

This script:
1. Checks if passwords are encrypted in the database
2. Verifies they can be decrypted via the User model
3. Tests setting new passwords
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.config import get_settings
from app.utils.encryption import init_encryptor, is_field_encrypted


class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


async def verify_encryption():
    """Verify password encryption is working."""
    print(f"\n{Colors.BOLD}Password Encryption Verification{Colors.RESET}")
    print("=" * 80)

    # Initialize encryptor
    settings = get_settings()
    encryption_key = settings.ENCRYPTION_KEY or settings.SECRET_KEY

    try:
        init_encryptor(encryption_key)
        print(f"{Colors.GREEN}✓ Encryptor initialized{Colors.RESET}")
    except Exception:
        # Fallback to derived key
        import hashlib
        import base64
        key_material = hashlib.sha256(encryption_key.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_material)
        init_encryptor(fernet_key.decode())
        print(f"{Colors.GREEN}✓ Encryptor initialized (derived key){Colors.RESET}")

    # Connect to database
    async with AsyncSessionLocal() as session:
        # Get users with passwords
        result = await session.execute(
            select(User).where(User._pandas_password_encrypted.isnot(None)).limit(5)
        )
        users = result.scalars().all()

        if not users:
            print(f"\n{Colors.YELLOW}No users with passwords found{Colors.RESET}")
            return

        print(f"\n{Colors.BOLD}Testing {len(users)} users with passwords:{Colors.RESET}")
        print("=" * 80)

        all_passed = True

        for user in users:
            print(f"\n{Colors.BOLD}User: {user.email} (ID: {user.id}){Colors.RESET}")

            # Check if database value is encrypted
            db_value = user._pandas_password_encrypted
            is_encrypted = is_field_encrypted(db_value)

            if is_encrypted:
                print(f"  {Colors.GREEN}✓ Database value is encrypted{Colors.RESET}")
            else:
                print(f"  {Colors.RED}✗ Database value is NOT encrypted (plaintext!){Colors.RESET}")
                all_passed = False
                continue

            # Try to decrypt via model property
            try:
                decrypted_password = user.pandas_password
                if decrypted_password:
                    print(f"  {Colors.GREEN}✓ Successfully decrypted: {decrypted_password[:3]}***{Colors.RESET}")
                else:
                    print(f"  {Colors.YELLOW}⚠ Decrypted to None{Colors.RESET}")
            except Exception as e:
                print(f"  {Colors.RED}✗ Decryption failed: {e}{Colors.RESET}")
                all_passed = False

        # Test setting a new password
        print(f"\n{Colors.BOLD}Testing password encryption on write:{Colors.RESET}")
        print("=" * 80)

        test_user = users[0]
        original_password = test_user.pandas_password
        test_password = "TestP@ssw0rd123"

        print(f"  Setting test password for {test_user.email}...")
        test_user.pandas_password = test_password

        # Check if it was encrypted
        if is_field_encrypted(test_user._pandas_password_encrypted):
            print(f"  {Colors.GREEN}✓ Password was encrypted{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ Password was NOT encrypted{Colors.RESET}")
            all_passed = False

        # Check if we can read it back
        if test_user.pandas_password == test_password:
            print(f"  {Colors.GREEN}✓ Decryption works correctly{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ Decryption returned wrong value{Colors.RESET}")
            all_passed = False

        # Restore original password
        test_user.pandas_password = original_password
        await session.rollback()  # Don't save test changes
        print(f"  {Colors.BLUE}ℹ Test changes rolled back{Colors.RESET}")

    # Summary
    print("\n" + "=" * 80)
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}✓ ALL CHECKS PASSED{Colors.RESET}")
        print(f"\n{Colors.GREEN}Password encryption is working correctly!{Colors.RESET}")
        print(f"  • Passwords are encrypted in the database")
        print(f"  • Decryption via model properties works")
        print(f"  • Setting passwords automatically encrypts")
    else:
        print(f"{Colors.RED}{Colors.BOLD}✗ SOME CHECKS FAILED{Colors.RESET}")
        print(f"\n{Colors.YELLOW}Please review the errors above{Colors.RESET}")


if __name__ == "__main__":
    asyncio.run(verify_encryption())
