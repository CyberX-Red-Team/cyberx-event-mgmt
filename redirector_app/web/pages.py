"""HTML page routes and web UI API endpoints for the standalone Redirector Manager.

Routes:
    GET  /login               Render login page (no auth)
    POST /api/web/login       Authenticate and set JWT session cookie
    POST /api/web/logout      Clear session cookie
    GET  /                    Redirect to /redirectors
    GET  /redirectors         Redirector list page
    GET  /redirectors/{id}    Redirector detail page
    GET  /logs                Error log viewer page
    GET  /api/internal/logs   JSON log buffer (auth-gated, ?n= query param)
"""
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from redirector_app.database import get_db
from redirector_app.web.auth import (
    WebAdminUser,
    build_web_admin_user,
    create_session_token,
    decode_session_token,
    get_admin_credentials,
    verify_password,
)
from redirector_app.web.log_buffer import get_recent_logs

router = APIRouter(tags=["Web UI"])

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

_is_production = os.environ.get("APP_ENV", "").lower() == "production"

# ---------------------------------------------------------------------------
# In-memory login rate limiter: max 5 attempts per 15 minutes per IP
# ---------------------------------------------------------------------------
_login_attempts: dict[str, list[datetime]] = defaultdict(list)
_RATE_LIMIT_ATTEMPTS = 5
_RATE_LIMIT_WINDOW = timedelta(minutes=15)


def _check_login_rate_limit(ip: str) -> bool:
    """Return True if the IP has exceeded the login rate limit."""
    now = datetime.utcnow()
    window_start = now - _RATE_LIMIT_WINDOW
    attempts = [t for t in _login_attempts[ip] if t > window_start]
    _login_attempts[ip] = attempts
    return len(attempts) >= _RATE_LIMIT_ATTEMPTS


def _record_login_attempt(ip: str) -> None:
    _login_attempts[ip].append(datetime.utcnow())


# ---------------------------------------------------------------------------
# Auth dependency for web UI pages (redirects to /login on failure)
# ---------------------------------------------------------------------------

def _get_session_user(request: Request) -> Optional[WebAdminUser]:
    """Extract WebAdminUser from session cookie, or None."""
    token = request.cookies.get("session")
    if not token:
        return None
    username = decode_session_token(token)
    if not username:
        return None
    return build_web_admin_user(username)


def _require_web_auth(request: Request) -> WebAdminUser:
    """Dependency: return WebAdminUser or raise 307 redirect to /login."""
    user = _get_session_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )
    return user


# ---------------------------------------------------------------------------
# Template context helper
# ---------------------------------------------------------------------------

def _ctx(request: Request, current_user: WebAdminUser, active_page: str = "", **extra):
    return {
        "request": request,
        "current_user": current_user,
        "active_page": active_page,
        "now": datetime.now(),
        "app_version": os.environ.get("APP_VERSION", "1.0.0"),
        **extra,
    }


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the cyberpunk login page. Redirect to /redirectors if already logged in."""
    user = _get_session_user(request)
    if user:
        return RedirectResponse("/redirectors", status_code=302)
    ctx = {
        "request": request,
        "now": datetime.now(),
    }
    return templates.TemplateResponse("pages/auth/login.html", ctx)


@router.post("/api/web/login")
async def api_login(request: Request):
    """
    Authenticate with username + password. Sets a secure HTTP-only JWT cookie on success.

    Rate-limited: 5 attempts per 15 minutes per IP.
    Returns 200 JSON on success, 401 JSON on failure, 429 JSON on rate limit.
    """
    ip = request.client.host if request.client else "unknown"

    if _check_login_rate_limit(ip):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Too many login attempts. Please wait 15 minutes and try again."},
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid JSON body."},
        )

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        _record_login_attempt(ip)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Username and password are required."},
        )

    try:
        admin_username, admin_password_hash = get_admin_credentials()
    except RuntimeError as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": str(e)},
        )

    if username != admin_username or not verify_password(password, admin_password_hash):
        _record_login_attempt(ip)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid credentials."},
        )

    token = create_session_token(username)
    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok", "redirect": "/redirectors"},
    )
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=_is_production,
        samesite="lax",
        max_age=int(os.environ.get("SESSION_EXPIRY_MINUTES", "480")) * 60,
    )
    return response


@router.post("/api/web/logout")
async def api_logout(
    request: Request,
    current_user: WebAdminUser = Depends(_require_web_auth),
):
    """Clear the session cookie."""
    response = JSONResponse(status_code=200, content={"status": "ok"})
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# Dashboard pages
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def root_redirect(current_user: WebAdminUser = Depends(_require_web_auth)):
    return RedirectResponse("/redirectors", status_code=302)


@router.get("/redirectors", response_class=HTMLResponse)
async def redirectors_list(
    request: Request,
    current_user: WebAdminUser = Depends(_require_web_auth),
):
    return templates.TemplateResponse(
        "pages/redirectors/list.html",
        _ctx(request, current_user, active_page="redirectors"),
    )


@router.get("/redirectors/{redirector_id}", response_class=HTMLResponse)
async def redirector_detail(
    redirector_id: str,
    request: Request,
    current_user: WebAdminUser = Depends(_require_web_auth),
    db: AsyncSession = Depends(get_db),
):
    from app.services.redirector_service import RedirectorService
    svc = RedirectorService(db)
    redirector = await svc.get_redirector(redirector_id)
    if not redirector:
        raise HTTPException(status_code=404, detail="Redirector not found.")
    return templates.TemplateResponse(
        "pages/redirectors/detail.html",
        _ctx(request, current_user, active_page="redirectors", redirector=redirector),
    )


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    current_user: WebAdminUser = Depends(_require_web_auth),
):
    return templates.TemplateResponse(
        "pages/logs.html",
        _ctx(request, current_user, active_page="logs"),
    )


# ---------------------------------------------------------------------------
# Internal log API
# ---------------------------------------------------------------------------

@router.get("/api/internal/logs")
async def api_logs(
    request: Request,
    n: int = Query(default=200, ge=1, le=500),
    current_user: WebAdminUser = Depends(_require_web_auth),
):
    """Return the most recent n log entries as JSON. Newest first."""
    logs = get_recent_logs(n)
    return JSONResponse({"logs": logs, "total": len(logs)})
