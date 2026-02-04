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
from app.api.routes import auth, admin, vpn, email, webhooks, views, event, public, sponsor
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
    logger.info("  Environment: %s", 'Development' if settings.DEBUG else 'Production')
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

    # Start the background scheduler
    await start_scheduler()

    yield  # Application runs

    # Shutdown
    logger.info("CyberX Event Management API shutting down...")
    await stop_scheduler()


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
