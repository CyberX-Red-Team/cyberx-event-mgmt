"""Standalone FastAPI application for the Redirector Manager.

Runs independently of cyberx-event-mgmt. Includes a full browser UI with
cyberpunk-themed login, redirector management dashboard, and error log viewer.

Authentication:
  - Web UI: bcrypt + JWT session cookie (set at POST /api/web/login)
  - API automation: X-API-Key header (backward compatible)

TLS: handled by nginx reverse proxy (see nginx/nginx.conf).
     For local dev without nginx, run with --ssl-keyfile/--ssl-certfile.

Setup:
    docker compose up -d postgres
    cp redirector_app/.env.example redirector_app/.env
    # Edit .env — fill in all required secrets (see .env.example for commands)
    pip install -r redirector_app/requirements.txt
    PYTHONPATH=backend uvicorn redirector_app.main:app --host 0.0.0.0 --port 8080

Environment variables (see redirector_app/.env.example for full list):
    FERNET_KEY              SSH key encryption (REQUIRED)
    API_KEY                 X-API-Key header secret (REQUIRED)
    ADMIN_USERNAME          Web UI login username (default: admin)
    ADMIN_PASSWORD_HASH     bcrypt hash of web UI password (REQUIRED)
    SECRET_KEY              JWT signing secret (REQUIRED)
    CSRF_SECRET_KEY         CSRF token signing secret (default: SECRET_KEY)
    SESSION_EXPIRY_MINUTES  JWT lifetime in minutes (default: 480)
    DATABASE_URL            PostgreSQL async URL (REQUIRED)
    APP_ENV                 "production" enables Secure cookie flag
    CORS_ORIGINS            JSON array of allowed origins (default: [])
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

load_dotenv()

# ---------------------------------------------------------------------------
# Startup secret validation — fail fast before any handler is registered
# ---------------------------------------------------------------------------
_REQUIRED_VARS = ("FERNET_KEY", "SECRET_KEY", "API_KEY", "ADMIN_PASSWORD_HASH")
for _var in _REQUIRED_VARS:
    if not os.environ.get(_var, "").strip():
        raise RuntimeError(
            f"Required environment variable {_var!r} is not set. "
            "See redirector_app/.env.example for setup instructions."
        )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_is_production = os.environ.get("APP_ENV", "").lower() == "production"


# ---------------------------------------------------------------------------
# Security headers middleware (defense-in-depth; nginx also sets these)
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Install memory log handler first — captures startup messages
    from redirector_app.web.log_buffer import install_memory_handler
    install_memory_handler()

    # 2. Initialize field encryption (both standalone and backend encryptors)
    fernet_key = os.environ["FERNET_KEY"]
    from redirector_app.encryption import init_encryptor
    init_encryptor(fernet_key)
    from app.utils.encryption import init_encryptor as backend_init_encryptor
    backend_init_encryptor(fernet_key)
    logger.info("Field encryption initialized.")

    # 3. Create DB tables (idempotent)
    from redirector_app.database import create_tables
    await create_tables()
    logger.info("Database tables ready.")

    logger.info("CyberX Redirector Manager standalone app started.")
    yield
    logger.info("CyberX Redirector Manager standalone app shutting down.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CyberX Redirector Manager",
    description=(
        "Manage nginx stream proxy configurations on remote redirector servers "
        "via SSH. Authenticate via the web UI or X-API-Key header."
    ),
    version="1.0.0",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    lifespan=lifespan,
)

# Security headers (defense-in-depth alongside nginx)
app.add_middleware(SecurityHeadersMiddleware)

# CSRF protection — exempt API key endpoints and read-only paths
_csrf_secret = os.environ.get("CSRF_SECRET_KEY", "").strip() or os.environ["SECRET_KEY"]


def _validate_api_key(key: str) -> bool:
    """Return True only if the key matches the configured API_KEY (timing-safe)."""
    import hmac
    configured_key = os.environ.get("API_KEY", "")
    return bool(configured_key) and hmac.compare_digest(key, configured_key)


from redirector_app.web.middleware import CSRFMiddleware
app.add_middleware(
    CSRFMiddleware,
    secret_key=_csrf_secret,
    exempt_urls=[
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/web/login",       # Login exempt — no CSRF cookie on first visit
    ],
    cookie_secure=_is_production,
    api_key_validator=_validate_api_key,
)

# CORS — restrict to explicitly configured origins
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] if _cors_origins_raw else []

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "X-CSRF-Token", "Content-Type"],
)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

_static_dir = Path(__file__).parent / "web" / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# ---------------------------------------------------------------------------
# Dependency overrides — standalone versions replace cyberx-event-mgmt ones
# ---------------------------------------------------------------------------

from app.api.routes import redirectors as redirectors_api
from app.dependencies import get_current_admin_user as _main_get_admin
from app.dependencies import get_current_active_user as _main_get_active
from app.dependencies import get_db as _main_get_db
from redirector_app.dependencies import get_current_admin_user as _sa_get_admin
from redirector_app.database import get_db as _sa_get_db

import app.utils.encryption as _main_enc
import redirector_app.encryption as _sa_enc
_main_enc.encrypt_field = _sa_enc.encrypt_field
_main_enc.decrypt_field = _sa_enc.decrypt_field

app.dependency_overrides[_main_get_admin]  = _sa_get_admin
app.dependency_overrides[_main_get_active] = _sa_get_admin  # require_permission uses this
app.dependency_overrides[_main_get_db]     = _sa_get_db

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# REST API (X-API-Key + session cookie auth via dependency override above)
app.include_router(redirectors_api.router)

# Web UI (HTML pages + login/logout)
from redirector_app.web import pages as web_pages
app.include_router(web_pages.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "app": "cyberx-redirector-manager"}


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
