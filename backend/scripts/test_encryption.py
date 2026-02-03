#!/usr/bin/env python3
"""
Test field encryption utilities.

This script tests the encryption/decryption of pandas_password fields
to ensure the implementation is working correctly.

Usage:
    python scripts/test_encryption.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.encryption import (
    FieldEncryptor,
    generate_encryption_key,
    init_encryptor,
    encrypt_field,
    decrypt_field,
    is_field_encrypted,
    EncryptionError
)


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def test_key_generation():
    """Test encryption key generation."""
    print(f"\n{Colors.BOLD}Test 1: Key Generation{Colors.RESET}")
    try:
        key = generate_encryption_key()
        print(f"  Generated key: {key[:20]}... (truncated)")
        print(f"  Key length: {len(key)} characters")
        print(f"  {Colors.GREEN}✓ PASS{Colors.RESET}")
        return key
    except Exception as e:
        print(f"  {Colors.RED}✗ FAIL: {e}{Colors.RESET}")
        return None


def test_encryptor_initialization(key):
    """Test encryptor initialization."""
    print(f"\n{Colors.BOLD}Test 2: Encryptor Initialization{Colors.RESET}")
    try:
        encryptor = FieldEncryptor(key)
        print(f"  {Colors.GREEN}✓ PASS: Encryptor created{Colors.RESET}")
        return encryptor
    except Exception as e:
        print(f"  {Colors.RED}✗ FAIL: {e}{Colors.RESET}")
        return None


def test_encryption_decryption(encryptor):
    """Test encryption and decryption."""
    print(f"\n{Colors.BOLD}Test 3: Encryption/Decryption{Colors.RESET}")
    test_cases = [
        "simple_password",
        "P@ssw0rd!123",
        "very_long_password_with_many_characters_1234567890",
        "密码",  # Unicode characters
        "",  # Empty string
    ]

    all_passed = True
    for plaintext in test_cases:
        try:
            # Encrypt
            encrypted = encryptor.encrypt(plaintext)
            print(f"  Plaintext: '{plaintext}'")
            print(f"  Encrypted: {encrypted[:40]}... (truncated)")

            # Decrypt
            decrypted = encryptor.decrypt(encrypted)

            if decrypted == plaintext:
                print(f"  {Colors.GREEN}✓ PASS: Decrypted matches original{Colors.RESET}\n")
            else:
                print(f"  {Colors.RED}✗ FAIL: Decrypted doesn't match{Colors.RESET}")
                print(f"    Expected: '{plaintext}'")
                print(f"    Got: '{decrypted}'\n")
                all_passed = False

        except Exception as e:
            print(f"  {Colors.RED}✗ FAIL: {e}{Colors.RESET}\n")
            all_passed = False

    return all_passed


def test_none_handling(encryptor):
    """Test handling of None values."""
    print(f"\n{Colors.BOLD}Test 4: None Handling{Colors.RESET}")
    try:
        encrypted = encryptor.encrypt(None)
        if encrypted is None:
            print(f"  {Colors.GREEN}✓ PASS: encrypt(None) returns None{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ FAIL: encrypt(None) returned {encrypted}{Colors.RESET}")
            return False

        decrypted = encryptor.decrypt(None)
        if decrypted is None:
            print(f"  {Colors.GREEN}✓ PASS: decrypt(None) returns None{Colors.RESET}")
            return True
        else:
            print(f"  {Colors.RED}✗ FAIL: decrypt(None) returned {decrypted}{Colors.RESET}")
            return False

    except Exception as e:
        print(f"  {Colors.RED}✗ FAIL: {e}{Colors.RESET}")
        return False


def test_invalid_token(encryptor):
    """Test decryption with invalid token."""
    print(f"\n{Colors.BOLD}Test 5: Invalid Token Handling{Colors.RESET}")
    try:
        # Try to decrypt invalid data
        result = encryptor.decrypt("invalid_encrypted_data")
        print(f"  {Colors.RED}✗ FAIL: Should have raised EncryptionError{Colors.RESET}")
        return False
    except EncryptionError as e:
        print(f"  {Colors.GREEN}✓ PASS: Raised EncryptionError as expected{Colors.RESET}")
        print(f"    Error message: {e}")
        return True
    except Exception as e:
        print(f"  {Colors.RED}✗ FAIL: Unexpected exception: {e}{Colors.RESET}")
        return False


def test_is_encrypted(encryptor):
    """Test is_encrypted detection."""
    print(f"\n{Colors.BOLD}Test 6: is_encrypted Detection{Colors.RESET}")
    plaintext = "test_password"
    encrypted = encryptor.encrypt(plaintext)

    # Test with encrypted value
    if encryptor.is_encrypted(encrypted):
        print(f"  {Colors.GREEN}✓ PASS: Correctly detected encrypted value{Colors.RESET}")
    else:
        print(f"  {Colors.RED}✗ FAIL: Failed to detect encrypted value{Colors.RESET}")
        return False

    # Test with plaintext value
    if not encryptor.is_encrypted(plaintext):
        print(f"  {Colors.GREEN}✓ PASS: Correctly detected plaintext value{Colors.RESET}")
    else:
        print(f"  {Colors.RED}✗ FAIL: Incorrectly marked plaintext as encrypted{Colors.RESET}")
        return False

    # Test with None
    if not encryptor.is_encrypted(None):
        print(f"  {Colors.GREEN}✓ PASS: Correctly handled None{Colors.RESET}")
        return True
    else:
        print(f"  {Colors.RED}✗ FAIL: Incorrectly marked None as encrypted{Colors.RESET}")
        return False


def test_global_encryptor(key):
    """Test global encryptor functions."""
    print(f"\n{Colors.BOLD}Test 7: Global Encryptor Functions{Colors.RESET}")
    try:
        # Initialize global encryptor
        init_encryptor(key)
        print(f"  {Colors.GREEN}✓ Global encryptor initialized{Colors.RESET}")

        # Test encrypt_field
        plaintext = "test_password_global"
        encrypted = encrypt_field(plaintext)
        print(f"  {Colors.GREEN}✓ encrypt_field() works{Colors.RESET}")

        # Test decrypt_field
        decrypted = decrypt_field(encrypted)
        if decrypted == plaintext:
            print(f"  {Colors.GREEN}✓ decrypt_field() works{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ FAIL: Decryption mismatch{Colors.RESET}")
            return False

        # Test is_field_encrypted
        if is_field_encrypted(encrypted) and not is_field_encrypted(plaintext):
            print(f"  {Colors.GREEN}✓ is_field_encrypted() works{Colors.RESET}")
            return True
        else:
            print(f"  {Colors.RED}✗ FAIL: is_field_encrypted() incorrect{Colors.RESET}")
            return False

    except Exception as e:
        print(f"  {Colors.RED}✗ FAIL: {e}{Colors.RESET}")
        return False


def main():
    """Run all tests."""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}Field Encryption Test Suite{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.RESET}")

    results = []

    # Test 1: Key generation
    key = test_key_generation()
    results.append(key is not None)
    if not key:
        print(f"\n{Colors.RED}Cannot continue without valid key{Colors.RESET}")
        return

    # Test 2: Encryptor initialization
    encryptor = test_encryptor_initialization(key)
    results.append(encryptor is not None)
    if not encryptor:
        print(f"\n{Colors.RED}Cannot continue without encryptor{Colors.RESET}")
        return

    # Test 3: Encryption/Decryption
    results.append(test_encryption_decryption(encryptor))

    # Test 4: None handling
    results.append(test_none_handling(encryptor))

    # Test 5: Invalid token
    results.append(test_invalid_token(encryptor))

    # Test 6: is_encrypted detection
    results.append(test_is_encrypted(encryptor))

    # Test 7: Global encryptor
    results.append(test_global_encryptor(key))

    # Summary
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}Test Summary:{Colors.RESET}")
    passed = sum(results)
    total = len(results)
    print(f"  Passed: {passed}/{total}")

    if passed == total:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ ALL TESTS PASSED{Colors.RESET}")
        print(f"\n{Colors.BOLD}Encryption is ready for use!{Colors.RESET}")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ SOME TESTS FAILED{Colors.RESET}")
        print(f"\n{Colors.YELLOW}Please fix issues before using encryption in production.{Colors.RESET}")


if __name__ == "__main__":
    main()
