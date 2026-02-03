#!/usr/bin/env python3
"""
Test that password encryption works during user creation.

This verifies that the hybrid property setter is triggered when creating
new User objects, ensuring passwords are encrypted from the start.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.config import get_settings
from app.utils.encryption import init_encryptor, is_field_encrypted
import base64
import hashlib


class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


async def test_user_creation():
    """Test password encryption during user creation."""
    print(f"\n{Colors.BOLD}Testing Password Encryption During User Creation{Colors.RESET}")
    print("=" * 80)

    # Initialize encryptor
    settings = get_settings()
    encryption_key = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    try:
        init_encryptor(encryption_key)
    except Exception:
        key_material = hashlib.sha256(encryption_key.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_material)
        init_encryptor(fernet_key.decode())

    print(f"{Colors.GREEN}✓ Encryptor initialized{Colors.RESET}\n")

    async with AsyncSessionLocal() as session:
        print(f"{Colors.BOLD}Test 1: Creating user with password{Colors.RESET}")
        print("-" * 80)

        # Create a test user (similar to participant_service.py)
        test_password = "TestPassword123!"
        test_user = User(
            email="test_encryption@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            pandas_username="testuser",
            pandas_password=test_password,  # This should trigger encryption
            confirmed="NO",
            email_status="UNKNOWN"
        )

        print(f"  Created User object with password: {test_password}")

        # Check if password was encrypted BEFORE saving to database
        if test_user._pandas_password_encrypted is not None:
            if is_field_encrypted(test_user._pandas_password_encrypted):
                print(f"  {Colors.GREEN}✓ Password was encrypted immediately{Colors.RESET}")
                print(f"  {Colors.BLUE}  Encrypted value: {test_user._pandas_password_encrypted[:50]}...{Colors.RESET}")
            else:
                print(f"  {Colors.RED}✗ Password is still plaintext!{Colors.RESET}")
                print(f"  {Colors.RED}  Value: {test_user._pandas_password_encrypted}{Colors.RESET}")
                return False
        else:
            print(f"  {Colors.RED}✗ Password is None{Colors.RESET}")
            return False

        # Check if we can read it back via the property
        decrypted = test_user.pandas_password
        if decrypted == test_password:
            print(f"  {Colors.GREEN}✓ Can read back original password: {decrypted}{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ Decrypted password doesn't match{Colors.RESET}")
            print(f"  {Colors.RED}  Expected: {test_password}{Colors.RESET}")
            print(f"  {Colors.RED}  Got: {decrypted}{Colors.RESET}")
            return False

        print(f"\n{Colors.BOLD}Test 2: Saving to database and retrieving{Colors.RESET}")
        print("-" * 80)

        # Add and commit to database
        session.add(test_user)
        await session.commit()
        user_id = test_user.id
        print(f"  {Colors.GREEN}✓ User saved to database (ID: {user_id}){Colors.RESET}")

        # Clear session cache
        session.expire_all()

        # Retrieve from database
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        retrieved_user = result.scalar_one_or_none()

        if retrieved_user is None:
            print(f"  {Colors.RED}✗ Failed to retrieve user from database{Colors.RESET}")
            return False

        print(f"  {Colors.GREEN}✓ User retrieved from database{Colors.RESET}")

        # Check if password is still encrypted in database
        if is_field_encrypted(retrieved_user._pandas_password_encrypted):
            print(f"  {Colors.GREEN}✓ Password is encrypted in database{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ Password is plaintext in database!{Colors.RESET}")
            return False

        # Check if we can decrypt it
        retrieved_password = retrieved_user.pandas_password
        if retrieved_password == test_password:
            print(f"  {Colors.GREEN}✓ Decrypted password matches original{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ Decrypted password doesn't match{Colors.RESET}")
            return False

        print(f"\n{Colors.BOLD}Test 3: Updating password{Colors.RESET}")
        print("-" * 80)

        # Update password
        new_password = "NewPassword456!"
        retrieved_user.pandas_password = new_password
        await session.commit()
        print(f"  Set new password: {new_password}")

        # Verify it's encrypted
        if is_field_encrypted(retrieved_user._pandas_password_encrypted):
            print(f"  {Colors.GREEN}✓ New password is encrypted{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ New password is plaintext!{Colors.RESET}")
            return False

        # Verify we can read it back
        if retrieved_user.pandas_password == new_password:
            print(f"  {Colors.GREEN}✓ Can read back new password{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ New password doesn't match{Colors.RESET}")
            return False

        # Cleanup
        await session.delete(retrieved_user)
        await session.commit()
        print(f"\n  {Colors.BLUE}ℹ Test user deleted{Colors.RESET}")

    print("\n" + "=" * 80)
    print(f"{Colors.GREEN}{Colors.BOLD}✓ ALL TESTS PASSED{Colors.RESET}")
    print(f"\n{Colors.GREEN}Password encryption is fully integrated into user creation!{Colors.RESET}")
    print(f"  • Passwords are encrypted immediately when User object is created")
    print(f"  • Encryption persists when saving to database")
    print(f"  • Decryption works when reading from database")
    print(f"  • Updates are automatically encrypted")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_user_creation())
    sys.exit(0 if success else 1)
