"""CSV import script to migrate SharePoint data to PostgreSQL."""
import asyncio
import csv
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal, engine
from app.models import User, VPNCredential
from app.config import get_settings

settings = get_settings()


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse timestamp from CSV."""
    if not value or value.lower() in ('', 'null', 'none'):
        return None

    # Try different datetime formats
    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%m/%d/%Y %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%m/%d/%Y',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue

    print(f"Warning: Could not parse timestamp: {value}")
    return None


def parse_boolean(value: Optional[str]) -> bool:
    """Parse boolean from CSV."""
    if not value:
        return False
    return value.strip().upper() in ('TRUE', 'YES', '1', 'Y')


async def import_participants(csv_path: str) -> int:
    """Import participants from CSV file."""
    print(f"\n📥 Importing participants from: {csv_path}")

    if not Path(csv_path).exists():
        print(f"❌ File not found: {csv_path}")
        return 0

    async with AsyncSessionLocal() as session:
        count = 0
        skipped = 0

        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            # Read first line to check format
            first_line = f.readline()

            # Skip the complex ListSchema header if present
            if first_line.startswith('ListSchema='):
                print("Detected SharePoint export format, skipping ListSchema line...")
                # The next line should be the CSV header, let DictReader handle it
                reader = csv.DictReader(f)
            else:
                # Regular CSV format - reset to beginning and read normally
                f.seek(0)
                reader = csv.DictReader(f)

            for row in reader:
                try:
                    # Skip rows without email
                    email = row.get('Email', '').strip()
                    if not email:
                        skipped += 1
                        continue

                    # Check if user already exists
                    result = await session.execute(
                        select(User).where(User.email == email)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        print(f"  ⚠️  User already exists: {email}")
                        skipped += 1
                        continue

                    # Create user
                    user = User(
                        email=email,
                        first_name=row.get('FirstName', row.get('Title', 'Unknown')).strip(),
                        last_name=row.get('LastName', '').strip(),
                        country=row.get('Country', 'Unknown').strip(),

                        # Account Status
                        confirmed=row.get('Confirmed', 'UNKNOWN').strip().upper(),
                        email_status=row.get('EmailStatus', 'GOOD').strip().upper(),
                        future_participation=row.get('FutureParticipation', 'UNKNOWN').strip(),
                        remove_permanently=row.get('RemovePermanently', 'UNKNOWN').strip(),

                        # Credentials
                        pandas_username=row.get('PandasUsername', '').strip() or None,
                        pandas_password=row.get('PandasPassword', '').strip() or None,
                        password_phonetic=row.get('PasswordPhonetic', '').strip() or None,

                        # Discord
                        discord_username=row.get('DiscordUsername', '').strip() or None,
                        snowflake_id=row.get('SnowflakeId', '').strip() or None,
                        discord_invite_code=row.get('DiscordInviteCode', '').strip() or None,
                        discord_invite_sent=parse_timestamp(row.get('DiscordInviteSent')),

                        # Communication tracking
                        invite_id=row.get('InviteId', '').strip() or None,
                        invite_sent=parse_timestamp(row.get('InviteSent')),
                        invite_reminder_sent=parse_timestamp(row.get('InviteReminderSent')),
                        last_invite_sent=parse_timestamp(row.get('LastInviteSent')),
                        password_email_sent=parse_timestamp(row.get('PasswordEmailSent')),
                        check_microsoft_email_sent=parse_timestamp(row.get('CheckMicrosoftEmailSent')),
                        survey_email_sent=parse_timestamp(row.get('SurveyEmailSent')),
                        survey_response_timestamp=parse_timestamp(row.get('SurveyResponseTimestamp')),
                        orientation_invite_email_sent=parse_timestamp(row.get('OrientationInviteEmailSent')),
                        in_person_email_sent=parse_timestamp(row.get('InPersonEmailSent')),

                        # In-person attendance
                        slated_in_person=parse_boolean(row.get('SlatedInPerson')),
                        confirmed_in_person=parse_boolean(row.get('ConfirmedInPerson')),

                        # System fields
                        sponsor_email=row.get('SponsorEmail', '').strip() or None,
                        azure_object_id=row.get('AzureObjectId', '').strip() or None,
                        pandas_groups=row.get('PandasGroups', '').strip() or None,
                    )

                    # Parse email_status_timestamp (might be a float/unix timestamp)
                    email_ts = row.get('EmailUpdateTimestamp', '').strip()
                    if email_ts:
                        try:
                            user.email_status_timestamp = int(float(email_ts))
                        except ValueError:
                            pass

                    session.add(user)
                    count += 1

                    if count % 50 == 0:
                        print(f"  ✓ Imported {count} participants...")
                        await session.commit()  # Commit every 50 rows

                except Exception as e:
                    print(f"  ❌ Error importing row: {e}")
                    print(f"     Email: {row.get('Email', 'N/A')}")
                    await session.rollback()  # Rollback on error
                    continue

            # Final commit
            await session.commit()
            print(f"\n✅ Imported {count} participants successfully")
            if skipped > 0:
                print(f"⚠️  Skipped {skipped} rows (duplicates or missing email)")

            return count


async def import_vpn_configs(csv_path: str) -> int:
    """Import VPN configurations from CSV file."""
    print(f"\n📥 Importing VPN configurations from: {csv_path}")

    if not Path(csv_path).exists():
        print(f"❌ File not found: {csv_path}")
        return 0

    async with AsyncSessionLocal() as session:
        count = 0
        skipped = 0

        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            # Read first line to check format
            first_line = f.readline()

            # Skip the complex ListSchema header if present
            if first_line.startswith('ListSchema='):
                print("Detected SharePoint export format, skipping ListSchema line...")
                # The next line should be the CSV header, let DictReader handle it
                reader = csv.DictReader(f)
            else:
                # Regular CSV format - reset to beginning and read normally
                f.seek(0)
                reader = csv.DictReader(f)

            for row in reader:
                try:
                    interface_ip = row.get('InterfaceIp', '').strip()
                    if not interface_ip:
                        skipped += 1
                        continue

                    # Parse comma-separated IPs
                    ips = [ip.strip() for ip in interface_ip.split(',')]
                    ipv4_address = ips[0] if len(ips) > 0 else None
                    ipv6_local = ips[1] if len(ips) > 1 else None
                    ipv6_global = ips[2] if len(ips) > 2 else None

                    # Check if VPN config already exists
                    result = await session.execute(
                        select(VPNCredential).where(VPNCredential.interface_ip == interface_ip)
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        skipped += 1
                        continue

                    # Get assigned username
                    assigned_username = row.get('AssignedToUsername', '').strip() or None

                    # Try to find the user by username to link FK
                    assigned_user_id = None
                    if assigned_username:
                        result = await session.execute(
                            select(User).where(User.pandas_username == assigned_username)
                        )
                        user = result.scalar_one_or_none()
                        if user:
                            assigned_user_id = user.id

                    # Create VPN credential
                    vpn = VPNCredential(
                        interface_ip=interface_ip,
                        ipv4_address=ipv4_address,
                        ipv6_local=ipv6_local,
                        ipv6_global=ipv6_global,

                        # Keys (base64 encoded)
                        private_key=row.get('PrivateKey', '').strip(),
                        preshared_key=row.get('PresharedKey', '').strip(),

                        # Configuration
                        endpoint=row.get('Endpoint', '').strip(),
                        key_type=row.get('KeyType', 'cyber').strip().lower(),

                        # Assignment
                        assigned_to_username=assigned_username,
                        assigned_to_user_id=assigned_user_id,

                        # Tracking
                        file_hash=row.get('FileHash', '').strip() or None,
                        file_id=row.get('FileId', '').strip() or None,
                        run_id=row.get('RunId', '').strip() or None,

                        # Availability
                        is_available=(assigned_username is None),
                    )

                    session.add(vpn)
                    count += 1

                    if count % 100 == 0:
                        print(f"  ✓ Imported {count} VPN configs...")
                        await session.commit()  # Commit every 100 rows

                except Exception as e:
                    print(f"  ❌ Error importing VPN config: {e}")
                    print(f"     IP: {row.get('InterfaceIp', 'N/A')}")
                    await session.rollback()  # Rollback on error
                    continue

            # Final commit
            await session.commit()
            print(f"\n✅ Imported {count} VPN configurations successfully")
            if skipped > 0:
                print(f"⚠️  Skipped {skipped} rows (duplicates or missing data)")

            return count


async def verify_imports(session: AsyncSession):
    """Verify imported data."""
    print("\n📊 Verifying imported data...")

    # Count users
    result = await session.execute(select(User))
    users = result.scalars().all()
    confirmed = sum(1 for u in users if u.confirmed == 'YES')

    # Count VPN assignments (avoid lazy loading)
    result_vpn = await session.execute(
        select(VPNCredential).where(VPNCredential.assigned_to_user_id.isnot(None))
    )
    vpns_assigned = len(result_vpn.scalars().all())

    print(f"  Users: {len(users)} total, {confirmed} confirmed, {vpns_assigned} with VPN")

    # Count VPN credentials
    result = await session.execute(select(VPNCredential))
    vpns = result.scalars().all()
    available = sum(1 for v in vpns if v.is_available)
    cyber = sum(1 for v in vpns if v.key_type == 'cyber')
    kinetic = sum(1 for v in vpns if v.key_type == 'kinetic')

    print(f"  VPN Credentials: {len(vpns)} total, {available} available")
    print(f"    Cyber: {cyber}, Kinetic: {kinetic}")

    # Sample users
    print("\n📝 Sample users:")
    for user in users[:3]:
        print(f"  - {user.email} ({user.first_name} {user.last_name})")
        print(f"    Confirmed: {user.confirmed}, Username: {user.pandas_username}")


async def main():
    """Main import function."""
    print("🚀 CyberX Event Management - CSV Import Script")
    print("=" * 60)

    # Default paths
    base_path = Path(__file__).resolve().parent.parent.parent / "data"
    participants_csv = base_path / "CyberX Master Invite.csv"
    vpn_csv = base_path / "VPN Configs V2.csv"

    # Allow custom paths from command line
    if len(sys.argv) > 1:
        participants_csv = Path(sys.argv[1])
    if len(sys.argv) > 2:
        vpn_csv = Path(sys.argv[2])

    print(f"\n📁 Data files:")
    print(f"  Participants: {participants_csv}")
    print(f"  VPN Configs: {vpn_csv}")

    # Confirm before proceeding
    response = input("\n⚠️  This will import data into the database. Continue? (yes/no): ")
    if response.lower() not in ('yes', 'y'):
        print("❌ Import cancelled")
        return

    try:
        # Import participants first
        participant_count = await import_participants(str(participants_csv))

        # Import VPN configurations
        vpn_count = await import_vpn_configs(str(vpn_csv))

        # Verify imports
        async with AsyncSessionLocal() as session:
            await verify_imports(session)

        print("\n" + "=" * 60)
        print("✅ Import completed successfully!")
        print(f"   Imported {participant_count} participants")
        print(f"   Imported {vpn_count} VPN configurations")

    except Exception as e:
        print(f"\n❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
