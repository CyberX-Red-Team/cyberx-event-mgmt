#!/usr/bin/env python3
"""
Seed test data for staging environment.

Creates test users for manual testing:
- 5 admin users
- 10 sponsor users
- 20 invitee users (randomly assigned to sponsors)
- 1 email template (plain invitation)
- 1000 VPN credentials (for load testing)

All users have predictable passwords for easy testing.
"""
import asyncio
import sys
import random
import json
import base64
import secrets
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.vpn import VPNCredential
from app.models.email_template import EmailTemplate
from app.utils.security import hash_password


# Test user data with deterministic credentials
ADMIN_USERS = [
    {"email": "admin1@cyberxtest.org", "first_name": "Admin", "last_name": "One", "country": "United States"},
    {"email": "admin2@cyberxtest.org", "first_name": "Admin", "last_name": "Two", "country": "United States"},
    {"email": "admin3@cyberxtest.org", "first_name": "Admin", "last_name": "Three", "country": "Canada"},
    {"email": "admin4@cyberxtest.org", "first_name": "Admin", "last_name": "Four", "country": "United Kingdom"},
    {"email": "admin5@cyberxtest.org", "first_name": "Admin", "last_name": "Five", "country": "United States"},
]

SPONSOR_USERS = [
    {"email": "sponsor1@cyberxtest.org", "first_name": "Sponsor", "last_name": "Alpha", "country": "United States"},
    {"email": "sponsor2@cyberxtest.org", "first_name": "Sponsor", "last_name": "Beta", "country": "United States"},
    {"email": "sponsor3@cyberxtest.org", "first_name": "Sponsor", "last_name": "Gamma", "country": "Canada"},
    {"email": "sponsor4@cyberxtest.org", "first_name": "Sponsor", "last_name": "Delta", "country": "United Kingdom"},
    {"email": "sponsor5@cyberxtest.org", "first_name": "Sponsor", "last_name": "Epsilon", "country": "Canada"},
    {"email": "sponsor6@cyberxtest.org", "first_name": "Sponsor", "last_name": "Zeta", "country": "United Kingdom"},
    {"email": "sponsor7@cyberxtest.org", "first_name": "Sponsor", "last_name": "Eta", "country": "United States"},
    {"email": "sponsor8@cyberxtest.org", "first_name": "Sponsor", "last_name": "Theta", "country": "Canada"},
    {"email": "sponsor9@cyberxtest.org", "first_name": "Sponsor", "last_name": "Iota", "country": "United Kingdom"},
    {"email": "sponsor10@cyberxtest.org", "first_name": "Sponsor", "last_name": "Kappa", "country": "United States"},
]

INVITEE_USERS = [
    {"email": "invitee1@cyberxtest.org", "first_name": "Invitee", "last_name": "Smith", "country": "United States"},
    {"email": "invitee2@cyberxtest.org", "first_name": "Invitee", "last_name": "Johnson", "country": "United States"},
    {"email": "invitee3@cyberxtest.org", "first_name": "Invitee", "last_name": "Williams", "country": "Canada"},
    {"email": "invitee4@cyberxtest.org", "first_name": "Invitee", "last_name": "Brown", "country": "United Kingdom"},
    {"email": "invitee5@cyberxtest.org", "first_name": "Invitee", "last_name": "Jones", "country": "United States"},
    {"email": "invitee6@cyberxtest.org", "first_name": "Invitee", "last_name": "Garcia", "country": "United States"},
    {"email": "invitee7@cyberxtest.org", "first_name": "Invitee", "last_name": "Miller", "country": "Canada"},
    {"email": "invitee8@cyberxtest.org", "first_name": "Invitee", "last_name": "Davis", "country": "United Kingdom"},
    {"email": "invitee9@cyberxtest.org", "first_name": "Invitee", "last_name": "Rodriguez", "country": "Canada"},
    {"email": "invitee10@cyberxtest.org", "first_name": "Invitee", "last_name": "Martinez", "country": "United Kingdom"},
    {"email": "invitee11@cyberxtest.org", "first_name": "Invitee", "last_name": "Hernandez", "country": "United States"},
    {"email": "invitee12@cyberxtest.org", "first_name": "Invitee", "last_name": "Lopez", "country": "Canada"},
    {"email": "invitee13@cyberxtest.org", "first_name": "Invitee", "last_name": "Gonzalez", "country": "United Kingdom"},
    {"email": "invitee14@cyberxtest.org", "first_name": "Invitee", "last_name": "Wilson", "country": "United States"},
    {"email": "invitee15@cyberxtest.org", "first_name": "Invitee", "last_name": "Anderson", "country": "Canada"},
    {"email": "invitee16@cyberxtest.org", "first_name": "Invitee", "last_name": "Thomas", "country": "United Kingdom"},
    {"email": "invitee17@cyberxtest.org", "first_name": "Invitee", "last_name": "Taylor", "country": "United States"},
    {"email": "invitee18@cyberxtest.org", "first_name": "Invitee", "last_name": "Moore", "country": "Canada"},
    {"email": "invitee19@cyberxtest.org", "first_name": "Invitee", "last_name": "Jackson", "country": "United Kingdom"},
    {"email": "invitee20@cyberxtest.org", "first_name": "Invitee", "last_name": "Martin", "country": "United States"},
]

# Shared test password for all test users
TEST_PASSWORD = "CyberX2026!"

# VPN configuration
NUM_VPN_CONFIGS = 1000
VPN_BASE_IP = "10.20.200."
VPN_ENDPOINT = "staging-vpn.cyberxtest.org:51820"

# Email template configuration (plain invitation email)
INVITE_EMAIL_TEMPLATE = {
    "name": "sg_test_hacker_theme",
    "display_name": "Event Invitation",
    "description": "Plain invitation email for CyberX events",
    "subject": "Invitation to {{event_name}}",
    "html_content": """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
<h1 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">You're Invited!</h1>

<p>Hello {{first_name}},</p>

<p>You have been invited to attend <strong>{{event_name}}</strong>.</p>

<div style="background: #f4f4f4; padding: 20px; margin: 20px 0; border-left: 4px solid #3498db;">
<h3 style="margin-top: 0; color: #2c3e50;">Event Details</h3>
<p><strong>Event:</strong> {{event_name}}</p>
<p><strong>Date:</strong> {{event_date_range}}</p>
<p><strong>Time:</strong> {{event_time}}</p>
<p><strong>Location:</strong> {{event_location}}</p>
</div>

<p>Please confirm your attendance by clicking the button below:</p>

<div style="text-align: center; margin: 30px 0;">
<a href="{{confirmation_url}}" style="display: inline-block; background: #3498db; color: white; padding: 12px 30px; text-decoration: none; border-radius: 4px; font-weight: bold;">Confirm Attendance</a>
</div>

<p style="font-size: 14px; color: #7f8c8d;">This invitation link will expire in 14 days. If you have any questions, please contact us at events@cyberxredteam.org</p>

<hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

<p style="font-size: 12px; color: #95a5a6; text-align: center;">
CyberX Red Team<br>
You are receiving this email because you were invited to {{event_name}}
</p>
</body>
</html>""",
    "text_content": """You're Invited!

Hello {{first_name}},

You have been invited to attend {{event_name}}.

EVENT DETAILS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Event: {{event_name}}
Date: {{event_date_range}}
Time: {{event_time}}
Location: {{event_location}}

Please confirm your attendance by visiting:
{{confirmation_url}}

This invitation link will expire in 14 days. If you have any questions, please contact us at events@cyberxredteam.org

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CyberX Red Team
You are receiving this email because you were invited to {{event_name}}
""",
    "available_variables": [
        "event_name",
        "event_date_range",
        "event_time",
        "event_location",
        "confirmation_url",
        "first_name",
        "last_name",
        "email"
    ],
    "is_active": True,
    "is_system": True
}


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


def generate_wireguard_config_content(
    interface_ip: str,
    private_key: str,
    preshared_key: str,
    endpoint: str,
    server_public_key: str = "test-server-public-key",
    allowed_ips: str = "10.0.0.0/8,fd00:a::/32",
    dns_servers: str = "10.20.200.1"
) -> str:
    """Generate WireGuard configuration file content for testing."""
    # Parse interface IPs (no spaces after commas)
    interface_ips = [ip.strip() for ip in interface_ip.split(",")]
    address_line = ",".join(interface_ips)

    # Build PresharedKey line only if present
    preshared_line = f"PresharedKey = {preshared_key}\n" if preshared_key else ""

    # Match production format
    config = f"""[Peer]
Endpoint = {endpoint}
PublicKey = {server_public_key}
{preshared_line}AllowedIPs = {allowed_ips}
PersistentKeepalive = 25
[Interface]
PrivateKey = {private_key}
Address = {address_line}
DNS = {dns_servers}
"""
    return config


def calculate_sha256(content: str) -> str:
    """Calculate SHA256 hash of string content."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


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

            # Generate confirmation code for testing
            confirmation_code = secrets.token_urlsafe(32)

            if existing_user:
                print(f"  ⚠️  Invitee {invitee_data['email']} already exists, updating...")
                existing_user.password_hash = hash_password(TEST_PASSWORD)
                existing_user.role = UserRole.INVITEE.value
                existing_user.sponsor_id = sponsor_id
                existing_user.is_active = True
                existing_user.confirmed = 'UNKNOWN'
                existing_user.email_status = 'GOOD'
                existing_user.confirmation_code = confirmation_code
                existing_user.confirmation_sent_at = datetime.now(timezone.utc)
                user = existing_user
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
                    confirmation_code=confirmation_code,
                    confirmation_sent_at=datetime.now(timezone.utc)
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
                "sponsor": sponsor.email,
                "confirmation_code": confirmation_code,
                "confirmation_url": f"http://localhost:8000/confirm?code={confirmation_code}"
            })

        await session.commit()

        # Create email template
        print("\nCreating email templates...")
        result = await session.execute(
            select(EmailTemplate).where(EmailTemplate.name == "sg_test_hacker_theme")
        )
        existing_template = result.scalar_one_or_none()

        if existing_template:
            print("  ⚠️  'sg_test_hacker_theme' template already exists, updating...")
            existing_template.display_name = INVITE_EMAIL_TEMPLATE["display_name"]
            existing_template.description = INVITE_EMAIL_TEMPLATE["description"]
            existing_template.subject = INVITE_EMAIL_TEMPLATE["subject"]
            existing_template.html_content = INVITE_EMAIL_TEMPLATE["html_content"]
            existing_template.text_content = INVITE_EMAIL_TEMPLATE["text_content"]
            existing_template.available_variables = INVITE_EMAIL_TEMPLATE["available_variables"]
            existing_template.is_active = INVITE_EMAIL_TEMPLATE["is_active"]
            existing_template.is_system = INVITE_EMAIL_TEMPLATE["is_system"]
        else:
            template = EmailTemplate(**INVITE_EMAIL_TEMPLATE)
            session.add(template)
            print("  ✅ Created plain invitation email template")

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

            # Generate WireGuard config content and calculate SHA256 hash
            config_content = generate_wireguard_config_content(
                interface_ip=interface_ip,
                private_key=private_key,
                preshared_key=preshared_key,
                endpoint=VPN_ENDPOINT
            )
            file_hash = calculate_sha256(config_content)

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
                existing_vpn.file_hash = file_hash
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
                    file_hash=file_hash,
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
    print(f"  - Email Templates: 1 (plain invitation)")
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
    print("INVITEES (Regular users - Status: UNKNOWN, needs confirmation):")
    for invitee in credentials["invitees"]:
        print(f"  • {invitee['email']} - {invitee['name']} (sponsored by {invitee['sponsor']})")
    print()
    print(f"PASSWORD (all users): {TEST_PASSWORD}")
    print()
    print("=" * 80)
    print("CONFIRMATION LINKS (for testing invitee confirmation flow)")
    print("=" * 80)
    print("All invitees have status UNKNOWN and need to confirm via these links:")
    print()
    for invitee in credentials["invitees"]:
        print(f"{invitee['name']} ({invitee['email']}):")
        print(f"  {invitee['confirmation_url']}")
        print()
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
