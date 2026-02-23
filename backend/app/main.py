"""FastAPI application entry point."""
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.middleware.csrf import CSRFMiddleware
from app.api.routes import auth, admin, vpn, email, webhooks, views, event, public, sponsor, user
from app.api.routes import instances as instances_routes, cloud_init as cloud_init_routes, license as license_routes, cloud_init_vpn
from app.api.routes import instance_templates, participant_instances
from app.api.routes import settings as settings_routes
from app.tasks import start_scheduler, stop_scheduler, list_jobs
from app.utils.encryption import init_encryptor, generate_encryption_key
from cryptography.fernet import Fernet
import base64


# Configure logging - force INFO level even if uvicorn configured it already
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Explicitly set root logger level to ensure INFO logs are visible
logging.getLogger().setLevel(logging.INFO)

# Silence SQLAlchemy query logging (too verbose)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)

# Silence passlib bcrypt version warning (known compatibility issue with bcrypt 4.x)
logging.getLogger('passlib.handlers.bcrypt').setLevel(logging.ERROR)

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("CyberX Event Management API starting...")
    logger.info("  Environment: %s", settings.ENVIRONMENT.upper())
    logger.info("  Database: %s", settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'configured')
    logger.info("  Session expiry: %d hours", settings.SESSION_EXPIRY_HOURS)
    logger.info("  Bulk email interval: %d minutes", settings.BULK_EMAIL_INTERVAL_MINUTES)

    # Initialize field encryptor
    encryption_key = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    # Ensure key is valid Fernet format (32 URL-safe base64 bytes)
    try:
        # Try to use key as-is first
        init_encryptor(encryption_key)
        logger.info("  Field encryption: Initialized with provided key")
    except Exception:
        # If key is not valid Fernet format, derive one from SECRET_KEY
        logger.warning("  Field encryption: Invalid ENCRYPTION_KEY format, deriving from SECRET_KEY")
        # Derive a Fernet key from SECRET_KEY (hash and encode as base64)
        import hashlib
        key_material = hashlib.sha256(encryption_key.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_material)
        init_encryptor(fernet_key.decode())
        logger.info("  Field encryption: Initialized with derived key")

    # Bootstrap default admin user if configured
    # Only runs if NO admin users exist in the system (prevents accidental password resets)
    if settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD:
        try:
            from sqlalchemy import select, or_
            from app.database import AsyncSessionLocal
            from app.models.user import User, UserRole
            from app.utils.security import hash_password

            async with AsyncSessionLocal() as session:
                # Check if ANY admin users exist (by role or is_admin flag)
                result = await session.execute(
                    select(User).where(
                        or_(
                            User.role == UserRole.ADMIN.value,
                            User.is_admin == True
                        )
                    ).limit(1)
                )
                existing_admin = result.scalar_one_or_none()

                if existing_admin:
                    logger.info("  Admin bootstrap: Skipped (admin users already exist)")
                else:
                    # No admins exist - create the initial admin user
                    logger.info("  Admin bootstrap: No admins found, creating initial admin user...")
                    admin_user = User(
                        email=settings.ADMIN_EMAIL,
                        first_name=settings.ADMIN_FIRST_NAME,
                        last_name=settings.ADMIN_LAST_NAME,
                        country="USA",
                        role=UserRole.ADMIN.value,
                        confirmed="YES",
                        email_status="GOOD",
                        is_admin=True,
                        is_active=True,
                        password_hash=hash_password(settings.ADMIN_PASSWORD),
                    )
                    session.add(admin_user)
                    await session.commit()
                    logger.info("  Admin bootstrap: Created initial admin user %s", settings.ADMIN_EMAIL)
        except Exception as e:
            logger.error("  Admin bootstrap: Failed - %s", e)
            # Don't fail startup if admin creation fails
    else:
        logger.info("  Admin bootstrap: Skipped (ADMIN_EMAIL not configured)")

    # Start the background scheduler
    # Runs scheduled jobs for email processing, session cleanup, and reminders
    logger.info("  Background scheduler: Starting...")
    try:
        await start_scheduler()
        logger.info("  Background scheduler: Started successfully")
    except Exception as e:
        logger.error("  Background scheduler: Failed to start - %s", e)
        # Don't fail startup if scheduler fails

    # Start the instance sync scheduler
    # Runs scheduled jobs for syncing instance status from cloud providers
    logger.info("  Instance sync scheduler: Starting...")
    try:
        from app.services.instance_sync_scheduler import get_scheduler
        instance_scheduler = get_scheduler()
        instance_scheduler.initialize()
        instance_scheduler.start()
        logger.info("  Instance sync scheduler: Started successfully")
    except Exception as e:
        logger.error("  Instance sync scheduler: Failed to start - %s", e)
        # Don't fail startup if scheduler fails

    yield  # Application runs

    # Shutdown
    logger.info("CyberX Event Management API shutting down...")
    try:
        await stop_scheduler()
        logger.info("  Background scheduler: Stopped")
    except Exception as e:
        logger.error("  Background scheduler: Error during shutdown - %s", e)

    # Shutdown instance sync scheduler
    try:
        from app.services.instance_sync_scheduler import get_scheduler
        instance_scheduler = get_scheduler()
        instance_scheduler.shutdown()
        logger.info("  Instance sync scheduler: Stopped")
    except Exception as e:
        logger.error("  Instance sync scheduler: Error during shutdown - %s", e)


# Create FastAPI application
app = FastAPI(
    title="CyberX Event Management API",
    description="API for managing CyberX event participants, VPN credentials, and communications",
    version="1.0.0",
    docs_url="/api/docs" if settings.DEBUG else None,  # Disable docs in production
    redoc_url="/api/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  # Restrict methods
    allow_headers=["*"],
)

# CSRF protection
# Exempt endpoints that receive external POSTs (webhooks, public actions)
csrf_exempt_urls = [
    "/api/webhooks/sendgrid",  # SendGrid webhook
    "/api/webhooks/discord",   # Discord OAuth callback
    "/api/public/confirm",     # Public confirmation endpoint
    "/api/public/decline",     # Public decline endpoint
    "/health",                 # Health check
    "/api/license/blob",       # VM-facing license endpoint (Bearer token auth)
    "/api/license/queue/acquire",  # VM-facing queue acquire (Bearer token auth)
    "/api/license/queue/release",  # VM-facing queue release (Bearer token auth)
]

app.add_middleware(
    CSRFMiddleware,
    secret_key=settings.CSRF_SECRET_KEY or settings.SECRET_KEY,
    exempt_urls=csrf_exempt_urls,
    cookie_name="csrf_token",
    cookie_secure=not settings.DEBUG,  # HTTPS only in production
    cookie_samesite="lax",
    cookie_httponly=False,  # JavaScript needs to read this for AJAX requests
    header_name="X-CSRF-Token",
)


# Mount static files
static_path = Path(__file__).parent.parent.parent / "frontend" / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


# Include API routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(sponsor.router)
app.include_router(vpn.router)
app.include_router(email.router)
app.include_router(webhooks.router)
app.include_router(event.router)
app.include_router(public.router)
app.include_router(user.router)
app.include_router(instances_routes.router)
app.include_router(cloud_init_routes.router)
app.include_router(cloud_init_vpn.router)  # Cloud-init VPN config endpoint
app.include_router(license_routes.router)
app.include_router(instance_templates.router)  # Admin instance templates management
app.include_router(participant_instances.router)  # Participant self-service provisioning
app.include_router(settings_routes.router)  # Admin system settings

# Include view routes (HTML pages)
app.include_router(views.router)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Scheduler status endpoint (admin only)
@app.get("/api/admin/scheduler/jobs")
async def get_scheduled_jobs():
    """Get list of scheduled background jobs."""
    return {"jobs": list_jobs()}


# Instance sync scheduler status endpoint (admin only)
@app.get("/api/admin/scheduler/instance-sync-status")
async def get_instance_sync_status():
    """Get instance sync scheduler status and statistics."""
    from app.services.instance_sync_scheduler import get_scheduler as get_instance_scheduler
    instance_scheduler = get_instance_scheduler()

    return {
        "scheduler_initialized": instance_scheduler.scheduler is not None,
        "scheduler_running": instance_scheduler.scheduler.running if instance_scheduler.scheduler else False,
        "stats": instance_scheduler.get_stats(),
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None
            }
            for job in (instance_scheduler.scheduler.get_jobs() if instance_scheduler.scheduler else [])
        ]
    }


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle unexpected exceptions."""
    if settings.DEBUG:
        # In debug mode, show the error details
        import traceback
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "traceback": traceback.format_exc()
            }
        )
    else:
        # In production, return a generic error
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )
