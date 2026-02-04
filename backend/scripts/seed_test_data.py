#!/usr/bin/env python3
"""
Seed test data for staging environment.

Creates test users for manual testing:
- 5 admin users
- 10 sponsor users
- 20 invitee users (randomly assigned to sponsors)
- 1000 VPN credentials (for load testing)

All users have predictable passwords for easy testing.
"""
import asyncio
import sys
import random
import json
import base64
import secrets
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.vpn import VPNCredential
from app.utils.security import hash_password


# Test user data with deterministic credentials
ADMIN_USERS = [
    {"email": "admin1@cyberxtest.org", "first_name": "Admin", "last_name": "One", "country": "USA"},
    {"email": "admin2@cyberxtest.org", "first_name": "Admin", "last_name": "Two", "country": "USA"},
    {"email": "admin3@cyberxtest.org", "first_name": "Admin", "last_name": "Three", "country": "Canada"},
    {"email": "admin4@cyberxtest.org", "first_name": "Admin", "last_name": "Four", "country": "UK"},
    {"email": "admin5@cyberxtest.org", "first_name": "Admin", "last_name": "Five", "country": "Australia"},
]

SPONSOR_USERS = [
    {"email": "sponsor1@cyberxtest.org", "first_name": "Sponsor", "last_name": "Alpha", "country": "USA"},
    {"email": "sponsor2@cyberxtest.org", "first_name": "Sponsor", "last_name": "Beta", "country": "USA"},
    {"email": "sponsor3@cyberxtest.org", "first_name": "Sponsor", "last_name": "Gamma", "country": "Canada"},
    {"email": "sponsor4@cyberxtest.org", "first_name": "Sponsor", "last_name": "Delta", "country": "UK"},
    {"email": "sponsor5@cyberxtest.org", "first_name": "Sponsor", "last_name": "Epsilon", "country": "Germany"},
    {"email": "sponsor6@cyberxtest.org", "first_name": "Sponsor", "last_name": "Zeta", "country": "France"},
    {"email": "sponsor7@cyberxtest.org", "first_name": "Sponsor", "last_name": "Eta", "country": "Spain"},
    {"email": "sponsor8@cyberxtest.org", "first_name": "Sponsor", "last_name": "Theta", "country": "Italy"},
    {"email": "sponsor9@cyberxtest.org", "first_name": "Sponsor", "last_name": "Iota", "country": "Japan"},
    {"email": "sponsor10@cyberxtest.org", "first_name": "Sponsor", "last_name": "Kappa", "country": "Brazil"},
]

INVITEE_USERS = [
    {"email": "invitee1@cyberxtest.org", "first_name": "Invitee", "last_name": "Smith", "country": "USA"},
    {"email": "invitee2@cyberxtest.org", "first_name": "Invitee", "last_name": "Johnson", "country": "USA"},
    {"email": "invitee3@cyberxtest.org", "first_name": "Invitee", "last_name": "Williams", "country": "Canada"},
    {"email": "invitee4@cyberxtest.org", "first_name": "Invitee", "last_name": "Brown", "country": "UK"},
    {"email": "invitee5@cyberxtest.org", "first_name": "Invitee", "last_name": "Jones", "country": "Australia"},
    {"email": "invitee6@cyberxtest.org", "first_name": "Invitee", "last_name": "Garcia", "country": "Spain"},
    {"email": "invitee7@cyberxtest.org", "first_name": "Invitee", "last_name": "Miller", "country": "Germany"},
    {"email": "invitee8@cyberxtest.org", "first_name": "Invitee", "last_name": "Davis", "country": "France"},
    {"email": "invitee9@cyberxtest.org", "first_name": "Invitee", "last_name": "Rodriguez", "country": "Mexico"},
    {"email": "invitee10@cyberxtest.org", "first_name": "Invitee", "last_name": "Martinez", "country": "Argentina"},
    {"email": "invitee11@cyberxtest.org", "first_name": "Invitee", "last_name": "Hernandez", "country": "Colombia"},
    {"email": "invitee12@cyberxtest.org", "first_name": "Invitee", "last_name": "Lopez", "country": "Peru"},
    {"email": "invitee13@cyberxtest.org", "first_name": "Invitee", "last_name": "Gonzalez", "country": "Chile"},
    {"email": "invitee14@cyberxtest.org", "first_name": "Invitee", "last_name": "Wilson", "country": "New Zealand"},
    {"email": "invitee15@cyberxtest.org", "first_name": "Invitee", "last_name": "Anderson", "country": "Sweden"},
    {"email": "invitee16@cyberxtest.org", "first_name": "Invitee", "last_name": "Thomas", "country": "Norway"},
    {"email": "invitee17@cyberxtest.org", "first_name": "Invitee", "last_name": "Taylor", "country": "Denmark"},
    {"email": "invitee18@cyberxtest.org", "first_name": "Invitee", "last_name": "Moore", "country": "Finland"},
    {"email": "invitee19@cyberxtest.org", "first_name": "Invitee", "last_name": "Jackson", "country": "Ireland"},
    {"email": "invitee20@cyberxtest.org", "first_name": "Invitee", "last_name": "Martin", "country": "Portugal"},
]

# Shared test password for all test users
TEST_PASSWORD = "CyberX2026!"

# VPN configuration
NUM_VPN_CONFIGS = 1000
VPN_BASE_IP = "10.20.200."
VPN_ENDPOINT = "staging-vpn.cyberxtest.org:51820"


def generate_wireguard_key() -> str:
    """Generate a random WireGuard private key (base64 encoded)."""
    # WireGuard keys are 32 bytes, base64 encoded
    key_bytes = secrets.token_bytes(32)
    return base64.b64encode(key_bytes).decode('utf-8')


def generate_ipv6_from_ipv4(ipv4: str) -> tuple[str, str]:
    """
    Generate IPv6 addresses from IPv4.

    Returns:
        Tuple of (link_local, global) IPv6 addresses
    """
    # Extract last octet from IPv4 (e.g., 10.20.200.149 -> 149)
    last_octet = int(ipv4.split('.')[-1])

    # Generate link-local IPv6 (fd00:a:14:c8:XX::XX format)
    link_local = f"fd00:a:14:c8:{last_octet:x}::{last_octet:x}"

    # Generate global IPv6 (fd00:a:14:c8:XX:ffff:a14:c8XX format)
    global_ipv6 = f"fd00:a:14:c8:{last_octet:x}:ffff:a14:c8{last_octet:02x}"

    return link_local, global_ipv6


async def seed_test_data():
    """Seed test data for staging environment."""
    print("=" * 80)
    print("CyberX Event Management - Test Data Seeder")
    print("=" * 80)
    print()

    credentials = {
        "admins": [],
        "sponsors": [],
        "invitees": [],
        "password": TEST_PASSWORD,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }

    async with AsyncSessionLocal() as session:
        # Create admin users
        print("Creating admin users...")
        for admin_data in ADMIN_USERS:
            # Check if user already exists
            result = await session.execute(
                select(User).where(User.email == admin_data["email"])
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                print(f"  ⚠️  Admin {admin_data['email']} already exists, updating...")
                existing_user.password_hash = hash_password(TEST_PASSWORD)
                existing_user.role = UserRole.ADMIN.value
                existing_user.is_admin = True
                existing_user.is_active = True
                existing_user.confirmed = 'YES'
                existing_user.email_status = 'GOOD'
            else:
                user = User(
                    email=admin_data["email"],
                    first_name=admin_data["first_name"],
                    last_name=admin_data["last_name"],
                    country=admin_data["country"],
                    role=UserRole.ADMIN.value,
                    is_admin=True,
                    is_active=True,
                    confirmed='YES',
                    email_status='GOOD',
                    password_hash=hash_password(TEST_PASSWORD),
                )
                session.add(user)
                print(f"  ✅ Created admin: {admin_data['email']}")

            credentials["admins"].append({
                "email": admin_data["email"],
                "role": "admin",
                "name": f"{admin_data['first_name']} {admin_data['last_name']}"
            })

        await session.commit()

        # Create sponsor users and get their IDs
        print("\nCreating sponsor users...")
        sponsor_ids = []
        for sponsor_data in SPONSOR_USERS:
            result = await session.execute(
                select(User).where(User.email == sponsor_data["email"])
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                print(f"  ⚠️  Sponsor {sponsor_data['email']} already exists, updating...")
                existing_user.password_hash = hash_password(TEST_PASSWORD)
                existing_user.role = UserRole.SPONSOR.value
                existing_user.is_active = True
                existing_user.confirmed = 'YES'
                existing_user.email_status = 'GOOD'
                sponsor_ids.append(existing_user.id)
            else:
                user = User(
                    email=sponsor_data["email"],
                    first_name=sponsor_data["first_name"],
                    last_name=sponsor_data["last_name"],
                    country=sponsor_data["country"],
                    role=UserRole.SPONSOR.value,
                    is_active=True,
                    confirmed='YES',
                    email_status='GOOD',
                    password_hash=hash_password(TEST_PASSWORD),
                )
                session.add(user)
                await session.flush()  # Get ID
                sponsor_ids.append(user.id)
                print(f"  ✅ Created sponsor: {sponsor_data['email']}")

            credentials["sponsors"].append({
                "email": sponsor_data["email"],
                "role": "sponsor",
                "name": f"{sponsor_data['first_name']} {sponsor_data['last_name']}"
            })

        await session.commit()

        # Create invitee users and randomly assign to sponsors
        print("\nCreating invitee users...")
        for invitee_data in INVITEE_USERS:
            # Randomly assign to a sponsor
            sponsor_id = random.choice(sponsor_ids)

            result = await session.execute(
                select(User).where(User.email == invitee_data["email"])
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                print(f"  ⚠️  Invitee {invitee_data['email']} already exists, updating...")
                existing_user.password_hash = hash_password(TEST_PASSWORD)
                existing_user.role = UserRole.INVITEE.value
                existing_user.sponsor_id = sponsor_id
                existing_user.is_active = True
                existing_user.confirmed = 'UNKNOWN'
                existing_user.email_status = 'GOOD'
            else:
                user = User(
                    email=invitee_data["email"],
                    first_name=invitee_data["first_name"],
                    last_name=invitee_data["last_name"],
                    country=invitee_data["country"],
                    role=UserRole.INVITEE.value,
                    sponsor_id=sponsor_id,
                    is_active=True,
                    confirmed='UNKNOWN',
                    email_status='GOOD',
                    password_hash=hash_password(TEST_PASSWORD),
                )
                session.add(user)
                print(f"  ✅ Created invitee: {invitee_data['email']}")

            # Get sponsor email for credentials report
            sponsor_result = await session.execute(
                select(User).where(User.id == sponsor_id)
            )
            sponsor = sponsor_result.scalar_one()

            credentials["invitees"].append({
                "email": invitee_data["email"],
                "role": "invitee",
                "name": f"{invitee_data['first_name']} {invitee_data['last_name']}",
                "sponsor": sponsor.email
            })

        await session.commit()

        # Create VPN credentials
        print(f"\nCreating {NUM_VPN_CONFIGS} VPN credentials...")
        vpn_created = 0
        vpn_updated = 0

        for i in range(1, NUM_VPN_CONFIGS + 1):
            # Generate IP addresses
            ipv4 = f"{VPN_BASE_IP}{i}"
            ipv6_local, ipv6_global = generate_ipv6_from_ipv4(ipv4)
            interface_ip = f"{ipv4},{ipv6_local},{ipv6_global}"

            # Generate keys
            private_key = generate_wireguard_key()
            preshared_key = generate_wireguard_key()  # Optional but we'll generate it

            # Check if VPN config already exists for this IP
            result = await session.execute(
                select(VPNCredential).where(VPNCredential.ipv4_address == ipv4)
            )
            existing_vpn = result.scalar_one_or_none()

            if existing_vpn:
                # Update existing
                existing_vpn.interface_ip = interface_ip
                existing_vpn.ipv6_local = ipv6_local
                existing_vpn.ipv6_global = ipv6_global
                existing_vpn.private_key = private_key
                existing_vpn.preshared_key = preshared_key
                existing_vpn.endpoint = VPN_ENDPOINT
                existing_vpn.is_available = True
                existing_vpn.is_active = True
                vpn_updated += 1
            else:
                # Create new
                vpn = VPNCredential(
                    interface_ip=interface_ip,
                    ipv4_address=ipv4,
                    ipv6_local=ipv6_local,
                    ipv6_global=ipv6_global,
                    private_key=private_key,
                    preshared_key=preshared_key,
                    endpoint=VPN_ENDPOINT,
                    key_type="cyber",  # Default to cyber type
                    is_available=True,
                    is_active=True
                )
                session.add(vpn)
                vpn_created += 1

            # Print progress every 100 configs
            if i % 100 == 0:
                print(f"  Progress: {i}/{NUM_VPN_CONFIGS} VPN configs processed...")

        await session.commit()
        print(f"  ✅ Created {vpn_created} new VPN configs")
        print(f"  ⚠️  Updated {vpn_updated} existing VPN configs")

    print("\n" + "=" * 80)
    print("✅ Test data seeding complete!")
    print("=" * 80)
    print(f"\nTotal resources created/updated:")
    print(f"  - Admins: {len(ADMIN_USERS)}")
    print(f"  - Sponsors: {len(SPONSOR_USERS)}")
    print(f"  - Invitees: {len(INVITEE_USERS)}")
    print(f"  - VPN Configs: {NUM_VPN_CONFIGS} ({vpn_created} new, {vpn_updated} updated)")
    print(f"\nShared password for ALL test users: {TEST_PASSWORD}")
    print()

    # Write credentials to JSON file for GitHub Actions artifact
    credentials_file = Path(__file__).parent.parent / "test_credentials.json"
    with open(credentials_file, 'w') as f:
        json.dump(credentials, f, indent=2)

    print(f"📄 Credentials saved to: {credentials_file}")
    print()

    # Print formatted credentials for easy copy-paste
    print("=" * 80)
    print("TEST CREDENTIALS")
    print("=" * 80)
    print()
    print("ADMINS (Full system access):")
    for admin in credentials["admins"]:
        print(f"  • {admin['email']} - {admin['name']}")
    print()
    print("SPONSORS (Can manage their invitees):")
    for sponsor in credentials["sponsors"]:
        print(f"  • {sponsor['email']} - {sponsor['name']}")
    print()
    print("INVITEES (Regular users):")
    for invitee in credentials["invitees"]:
        print(f"  • {invitee['email']} - {invitee['name']} (sponsored by {invitee['sponsor']})")
    print()
    print(f"PASSWORD (all users): {TEST_PASSWORD}")
    print("=" * 80)

    return credentials


async def main():
    """Main function."""
    try:
        credentials = await seed_test_data()

        # Exit successfully
        sys.exit(0)

    except Exception as e:
        print(f"\n❌ Error seeding test data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
