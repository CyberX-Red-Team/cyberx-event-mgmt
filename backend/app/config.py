"""Application configuration management."""
from pydantic_settings import BaseSettings
from functools import lru_cache


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
    TEST_EMAIL_OVERRIDE: str = ""  # If set, all emails go to this address instead

    # PowerDNS (optional - only needed if using PowerDNS integration)
    POWERDNS_API_URL: str = ""
    POWERDNS_USERNAME: str = ""
    POWERDNS_PASSWORD: str = ""

    # VPN Server Configuration (optional - only needed if using VPN features)
    VPN_SERVER_PUBLIC_KEY: str = ""
    VPN_SERVER_ENDPOINT: str = ""
    VPN_DNS_SERVERS: str = "10.20.200.1"
    VPN_ALLOWED_IPS: str = "10.0.0.0/8,fd00:a::/32"

    # Session Configuration
    SESSION_EXPIRY_HOURS: int = 24

    # Email Job
    BULK_EMAIL_INTERVAL_MINUTES: int = 45

    # Invitation Reminder Configuration
    REMINDER_1_DAYS_AFTER_INVITE: int = 7  # First reminder: 7 days after initial invitation
    REMINDER_1_MIN_DAYS_BEFORE_EVENT: int = 14  # Don't send if event is less than 14 days away
    REMINDER_2_DAYS_AFTER_INVITE: int = 14  # Second reminder: 14 days after initial invitation
    REMINDER_2_MIN_DAYS_BEFORE_EVENT: int = 7  # Don't send if event is less than 7 days away
    REMINDER_3_DAYS_BEFORE_EVENT: int = 3  # Final reminder: 3 days before event starts
    REMINDER_CHECK_INTERVAL_HOURS: int = 24  # How often to check for reminders to send

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
