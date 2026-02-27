"""Application configuration management."""
from pydantic_settings import BaseSettings
from functools import lru_cache
import subprocess
import logging


class Settings(BaseSettings):
    """Application settings."""

    # Database
    DATABASE_URL: str

    @property
    def async_database_url(self) -> str:
        """Get DATABASE_URL with asyncpg driver for async SQLAlchemy.

        Converts postgresql:// to postgresql+asyncpg:// automatically.
        This allows flexibility in how the DATABASE_URL is provided.
        """
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.DATABASE_URL

    # Application
    ENVIRONMENT: str = "development"  # development, staging, or production
    SECRET_KEY: str = ""  # Required for web service, optional for scripts
    CSRF_SECRET_KEY: str = ""  # If empty, uses SECRET_KEY
    ENCRYPTION_KEY: str = ""  # Field-level encryption key (Fernet), if empty uses SECRET_KEY
    DEBUG: bool = False
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    FRONTEND_URL: str = "http://localhost:8000"  # Base URL for frontend links in emails

    # Default Admin User (optional - for automatic bootstrapping on startup)
    ADMIN_EMAIL: str = ""  # If set, creates/updates admin user on startup
    ADMIN_PASSWORD: str = ""  # Required if ADMIN_EMAIL is set
    ADMIN_FIRST_NAME: str = "Admin"
    ADMIN_LAST_NAME: str = "User"

    # SendGrid (optional - only needed for sending emails)
    SENDGRID_API_KEY: str = ""
    SENDGRID_FROM_EMAIL: str = ""
    SENDGRID_FROM_NAME: str = "CyberX Red Team"
    SENDGRID_SANDBOX_MODE: bool = False  # Enable to validate emails without sending
    SENDGRID_WEBHOOK_VERIFICATION_KEY: str = ""  # Verification key for webhook signature validation
    TEST_EMAIL_OVERRIDE: str = ""  # If set, all emails go to this address instead

    # PowerDNS (optional - only needed if using PowerDNS integration)
    POWERDNS_API_URL: str = ""
    POWERDNS_USERNAME: str = ""
    POWERDNS_PASSWORD: str = ""

    # Render API (optional - only needed for deployment automation)
    RENDER_API_KEY: str = ""

    # VPN Server Configuration (optional - only needed if using VPN features)
    VPN_SERVER_PUBLIC_KEY: str = ""
    VPN_SERVER_ENDPOINT: str = ""
    VPN_DNS_SERVERS: str = "10.20.200.1"
    VPN_ALLOWED_IPS: str = "10.0.0.0/8,fd00:a::/32"

    # Session Configuration
    SESSION_EXPIRY_HOURS: int = 24

    # Email Job
    BULK_EMAIL_INTERVAL_MINUTES: int = 45

    # OpenStack Integration (optional - only needed for instance provisioning)
    OS_AUTH_URL: str = ""
    OS_AUTH_TYPE: str = "v3applicationcredential"  # or "password"
    OS_APPLICATION_CREDENTIAL_ID: str = ""
    OS_APPLICATION_CREDENTIAL_SECRET: str = ""
    OS_USERNAME: str = ""
    OS_PASSWORD: str = ""
    OS_PROJECT_NAME: str = ""
    OS_USER_DOMAIN_NAME: str = "Default"
    OS_PROJECT_DOMAIN_NAME: str = "Default"
    OS_NOVA_URL: str = ""      # Optional, auto-discovered from Keystone catalog
    OS_NEUTRON_URL: str = ""   # Optional, auto-discovered from Keystone catalog
    OS_GLANCE_URL: str = ""    # Optional, auto-discovered from Keystone catalog

    # Default Instance Configuration (optional - can be overridden per-request)
    OS_DEFAULT_FLAVOR_ID: str = ""
    OS_DEFAULT_IMAGE_ID: str = ""
    OS_DEFAULT_NETWORK_ID: str = ""
    OS_DEFAULT_KEY_NAME: str = ""

    # DigitalOcean Integration (optional - only needed for DO provisioning)
    DO_API_TOKEN: str = ""
    DO_DEFAULT_REGION: str = "nyc1"
    DO_DEFAULT_SIZE: str = "s-1vcpu-1gb"
    DO_DEFAULT_IMAGE: str = "ubuntu-22-04-x64"
    DO_SSH_KEY_ID: str = ""  # Optional: DigitalOcean SSH key ID or fingerprint

    # Download Link Generation - Cloudflare R2 (optional)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = ""
    R2_CUSTOM_DOMAIN: str = ""

    # Download Link Generation - nginx secure_link alternative (optional)
    DOWNLOAD_SECRET: str = ""
    DOWNLOAD_BASE_URL: str = ""
    DOWNLOAD_LINK_MODE: str = "r2"     # "r2" or "nginx"
    DOWNLOAD_LINK_EXPIRY: int = 3600   # Default 1 hour

    # Cloud-Init Template Variables
    # Note: License server URL is derived from FRONTEND_URL + "/api/license"
    # Note: license_token is auto-generated per-instance (no config needed)

    # Invitation Reminder Configuration
    REMINDER_1_ENABLED: bool = False
    REMINDER_1_DAYS_AFTER_INVITE: int = 7  # First reminder: 7 days after initial invitation
    REMINDER_1_MIN_DAYS_BEFORE_EVENT: int = 14  # Don't send if event is less than 14 days away
    REMINDER_2_ENABLED: bool = False
    REMINDER_2_DAYS_AFTER_INVITE: int = 14  # Second reminder: 14 days after initial invitation
    REMINDER_2_MIN_DAYS_BEFORE_EVENT: int = 7  # Don't send if event is less than 7 days away
    REMINDER_3_ENABLED: bool = False
    REMINDER_3_DAYS_BEFORE_EVENT: int = 3  # Final reminder: 3 days before event starts
    REMINDER_CHECK_INTERVAL_HOURS: int = 24  # How often to check for reminders to send

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def get_version() -> str:
    """
    Get application version string.

    In staging: Returns version with commit hash (e.g., "v1.0.0+abc1234")
    In production: Returns clean version (e.g., "v1.0.0")
    """
    from app.version import VERSION

    settings = get_settings()
    version_str = f"v{VERSION}"

    # Add commit hash in staging environment
    if settings.ENVIRONMENT == "staging":
        try:
            # Get short commit hash (7 characters)
            commit_hash = subprocess.check_output(
                ["git", "rev-parse", "--short=7", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
            version_str = f"{version_str}+{commit_hash}"
        except (subprocess.CalledProcessError, FileNotFoundError):
            # If git is not available or not a git repo, just return version
            logger = logging.getLogger(__name__)
            logger.warning("Could not retrieve git commit hash for version string")

    return version_str
