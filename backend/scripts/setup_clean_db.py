#!/usr/bin/env python3
"""
Clean database setup script for CyberX Event Management System.

This script provides a complete, automated setup for a clean database installation.
Suitable for CI/CD pipelines and fresh deployments.

Usage:
    # Interactive mode
    python scripts/setup_clean_db.py

    # Non-interactive mode (CI/CD)
    python scripts/setup_clean_db.py \
        --admin-email admin@example.com \
        --admin-password securepassword \
        --no-prompt

    # With sample data
    python scripts/setup_clean_db.py --seed-data
"""

import asyncio
import sys
import argparse
import subprocess
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User
from app.models.event import Event
from app.models.email_template import EmailTemplate
from app.utils.security import hash_password


class DatabaseSetup:
    """Handles clean database setup and initialization."""

    def __init__(
        self,
        admin_email: str = "admin@cyberxredteam.org",
        admin_password: str = "changeme",
        seed_data: bool = False,
        verbose: bool = True
    ):
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.seed_data = seed_data
        self.verbose = verbose

    def log(self, message: str, emoji: str = "ℹ️"):
        """Print a log message if verbose mode is enabled."""
        if self.verbose:
            print(f"{emoji} {message}")

    async def check_database_connection(self) -> bool:
        """Verify database connection."""
        self.log("Checking database connection...", "🔌")
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            self.log("Database connection successful", "✅")
            return True
        except Exception as e:
            self.log(f"Database connection failed: {e}", "❌")
            return False

    async def run_migrations(self) -> bool:
        """Run Alembic migrations to create/update tables."""
        self.log("Running database migrations...", "📦")
        try:
            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent
            )

            if result.returncode == 0:
                self.log("Migrations completed successfully", "✅")
                if self.verbose and result.stdout:
                    print(result.stdout)
                return True
            else:
                self.log(f"Migration failed: {result.stderr}", "❌")
                return False
        except Exception as e:
            self.log(f"Error running migrations: {e}", "❌")
            return False

    async def verify_tables(self) -> bool:
        """Verify that all required tables exist."""
        self.log("Verifying database tables...", "🔍")

        required_tables = [
            'users',
            'events',
            'event_participations',
            'sessions',
            'vpn_credentials',
            'audit_logs',
            'email_queue',
            'email_templates',
            'email_workflows',
            'app_settings'
        ]

        try:
            async with engine.connect() as conn:
                for table in required_tables:
                    result = await conn.execute(
                        text(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{table}')")
                    )
                    exists = result.scalar()
                    if not exists:
                        self.log(f"Table '{table}' not found", "❌")
                        return False

            self.log(f"All {len(required_tables)} required tables exist", "✅")
            return True
        except Exception as e:
            self.log(f"Error verifying tables: {e}", "❌")
            return False

    async def create_admin_user(self) -> bool:
        """Create initial admin user."""
        self.log(f"Creating admin user: {self.admin_email}", "👤")

        try:
            async with AsyncSessionLocal() as session:
                # Check if admin exists
                result = await session.execute(
                    select(User).where(User.email == self.admin_email)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    self.log("Admin user already exists, updating...", "⚠️")
                    existing.password_hash = hash_password(self.admin_password)
                    existing.is_admin = True
                    existing.is_active = True
                    existing.confirmed = 'YES'
                    existing.email_status = 'GOOD'
                else:
                    # Create new admin user
                    admin = User(
                        email=self.admin_email,
                        first_name="Admin",
                        last_name="User",
                        country="USA",
                        confirmed="YES",
                        email_status="GOOD",
                        pandas_username=f"admin_{self.admin_email.split('@')[0]}",
                        password_hash=hash_password(self.admin_password),
                        is_admin=True,
                        is_active=True,
                    )
                    session.add(admin)

                await session.commit()
                self.log("Admin user created/updated successfully", "✅")
                self.log(f"  Email: {self.admin_email}", "📧")
                self.log(f"  Password: {'*' * len(self.admin_password)}", "🔑")
                return True

        except Exception as e:
            self.log(f"Error creating admin user: {e}", "❌")
            return False

    async def seed_sample_data(self) -> bool:
        """Optionally seed sample data for testing."""
        if not self.seed_data:
            return True

        self.log("Seeding sample data...", "🌱")

        try:
            async with AsyncSessionLocal() as session:
                # Create sample event
                result = await session.execute(
                    select(Event).where(Event.year == 2026)
                )
                existing_event = result.scalar_one_or_none()

                if not existing_event:
                    from datetime import datetime, timedelta

                    sample_event = Event(
                        name="Sample Event 2026",
                        year=2026,
                        start_date=datetime.now() + timedelta(days=90),
                        end_date=datetime.now() + timedelta(days=97),
                        event_location="Virtual",
                        registration_opens=datetime.now(),
                        registration_closes=datetime.now() + timedelta(days=60),
                        max_participants=100,
                        is_active=True,
                        registration_open=True,
                        test_mode=True,
                        vpn_available=False
                    )
                    session.add(sample_event)
                    self.log("Created sample event", "✅")

                # Create sample email templates
                template_types = [
                    ("invitation", "Invitation Email"),
                    ("reminder_1", "First Reminder"),
                    ("reminder_2", "Second Reminder"),
                    ("reminder_3", "Final Reminder"),
                    ("vpn_config", "VPN Configuration"),
                    ("password_reset", "Password Reset")
                ]

                for template_type, template_name in template_types:
                    result = await session.execute(
                        select(EmailTemplate).where(EmailTemplate.name == template_type)
                    )
                    existing_template = result.scalar_one_or_none()

                    if not existing_template:
                        template = EmailTemplate(
                            name=template_type,
                            display_name=template_name,
                            subject=f"{template_name} - CyberX Event",
                            html_content=f"<p>This is a sample {template_name} template.</p>",
                            sendgrid_template_id=f"d-sample-{template_type}",
                            description=f"Sample {template_name} template"
                        )
                        session.add(template)

                await session.commit()
                self.log("Sample data seeded successfully", "✅")
                return True

        except Exception as e:
            self.log(f"Error seeding sample data: {e}", "❌")
            return False

    async def verify_installation(self) -> dict:
        """Verify the installation and return statistics."""
        self.log("Verifying installation...", "🔍")

        stats = {
            'users': 0,
            'events': 0,
            'vpn_credentials': 0,
            'email_templates': 0,
            'audit_logs': 0
        }

        try:
            async with AsyncSessionLocal() as session:
                # Count users
                result = await session.execute(select(User))
                stats['users'] = len(result.scalars().all())

                # Count events
                result = await session.execute(select(Event))
                stats['events'] = len(result.scalars().all())

                # Count VPN credentials
                result = await session.execute(
                    text("SELECT COUNT(*) FROM vpn_credentials")
                )
                stats['vpn_credentials'] = result.scalar()

                # Count email templates
                result = await session.execute(select(EmailTemplate))
                stats['email_templates'] = len(result.scalars().all())

                # Count audit logs
                result = await session.execute(
                    text("SELECT COUNT(*) FROM audit_logs")
                )
                stats['audit_logs'] = result.scalar()

            self.log("Installation verified successfully", "✅")
            return stats

        except Exception as e:
            self.log(f"Error verifying installation: {e}", "❌")
            return stats

    async def run(self) -> bool:
        """Execute the complete setup process."""
        print("\n" + "=" * 70)
        print("🚀 CyberX Event Management System - Clean Database Setup")
        print("=" * 70 + "\n")

        # Step 1: Check database connection
        if not await self.check_database_connection():
            return False

        # Step 2: Run migrations
        if not await self.run_migrations():
            return False

        # Step 3: Verify tables
        if not await self.verify_tables():
            return False

        # Step 4: Create admin user
        if not await self.create_admin_user():
            return False

        # Step 5: Seed sample data (optional)
        if not await self.seed_sample_data():
            return False

        # Step 6: Verify installation
        stats = await self.verify_installation()

        # Print summary
        print("\n" + "=" * 70)
        print("✅ Database setup completed successfully!")
        print("=" * 70)
        print("\n📊 Database Statistics:")
        print(f"   Users: {stats['users']}")
        print(f"   Events: {stats['events']}")
        print(f"   VPN Credentials: {stats['vpn_credentials']}")
        print(f"   Email Templates: {stats['email_templates']}")
        print(f"   Audit Logs: {stats['audit_logs']}")

        print("\n🔐 Admin Credentials:")
        print(f"   Email: {self.admin_email}")
        print(f"   Password: {self.admin_password}")

        print("\n📝 Next Steps:")
        print("   1. Start the application:")
        print("      uvicorn app.main:app --host 0.0.0.0 --port 8000")
        print("   2. Access the API:")
        print("      http://localhost:8000")
        print("   3. View API documentation:")
        print("      http://localhost:8000/api/docs")
        print("   4. Import data (optional):")
        print("      python scripts/import_csv.py <participants.csv> <vpn-configs.csv>")
        print("\n")

        return True


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Clean database setup for CyberX Event Management System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  python scripts/setup_clean_db.py

  # Non-interactive mode (CI/CD)
  python scripts/setup_clean_db.py \\
      --admin-email admin@example.com \\
      --admin-password securepassword \\
      --no-prompt

  # With sample data
  python scripts/setup_clean_db.py --seed-data
        """
    )

    parser.add_argument(
        '--admin-email',
        default='admin@cyberxredteam.org',
        help='Admin user email address (default: admin@cyberxredteam.org)'
    )

    parser.add_argument(
        '--admin-password',
        default='changeme',
        help='Admin user password (default: changeme)'
    )

    parser.add_argument(
        '--seed-data',
        action='store_true',
        help='Seed sample data for testing'
    )

    parser.add_argument(
        '--no-prompt',
        action='store_true',
        help='Run without prompts (for CI/CD)'
    )

    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress verbose output'
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_arguments()

    # Interactive prompts if not in no-prompt mode
    if not args.no_prompt:
        print("🚀 CyberX Event Management System - Database Setup")
        print("=" * 70 + "\n")

        # Get admin email
        email_input = input(f"Admin email (default: {args.admin_email}): ").strip()
        if email_input:
            args.admin_email = email_input

        # Get admin password
        password_input = input(f"Admin password (default: {args.admin_password}): ").strip()
        if password_input:
            args.admin_password = password_input

        # Ask about seed data
        if not args.seed_data:
            seed_input = input("Seed sample data? (y/N): ").strip().lower()
            args.seed_data = seed_input in ('y', 'yes')

        # Confirm
        print(f"\n⚠️  This will initialize the database with:")
        print(f"   Admin email: {args.admin_email}")
        print(f"   Seed data: {'Yes' if args.seed_data else 'No'}")
        confirm = input("\nContinue? (yes/no): ").strip().lower()

        if confirm not in ('yes', 'y'):
            print("❌ Setup cancelled")
            return 1

    # Run setup
    setup = DatabaseSetup(
        admin_email=args.admin_email,
        admin_password=args.admin_password,
        seed_data=args.seed_data,
        verbose=not args.quiet
    )

    try:
        success = await setup.run()
        return 0 if success else 1
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
