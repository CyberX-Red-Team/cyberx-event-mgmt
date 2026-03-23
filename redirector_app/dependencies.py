"""Authentication dependencies for the standalone redirector app.

Supports two auth modes so existing API consumers and the web UI can both work:

  1. X-API-Key header — for automation / API-only clients (backward compatible).
  2. JWT session cookie — for the web browser UI (set at login via /api/web/login).

Both modes return a compatible user object so route signatures in
backend/app/api/routes/redirectors.py do not need modification.

Environment variables:
    API_KEY     Secret key for X-API-Key header auth (REQUIRED)
    SECRET_KEY  HS256 JWT signing secret (REQUIRED for web UI)
"""
import os
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_API_KEY = os.environ.get("API_KEY", "")


class _FakeAdminUser:
    """Minimal stand-in for the cyberx User model used in audit log calls."""

    def __init__(
        self,
        email: str = "api-key-user@standalone",
        first_name: str = "API",
        last_name: str = "Key",
    ):
        self.id = 0
        self.email = email
        self.first_name = first_name
        self.last_name = last_name


async def get_current_admin_user(
    request: Request,
    api_key: str = Security(_api_key_header),
) -> _FakeAdminUser:
    """
    Authenticate the request via X-API-Key header or JWT session cookie.

    Priority:
      1. X-API-Key header (API automation clients)
      2. 'session' HTTP-only cookie (web UI after login)

    Raises HTTP 401 if neither succeeds.
    """
    # --- Mode 1: X-API-Key header ---
    if api_key:
        if not _API_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API_KEY environment variable is not configured.",
            )
        if api_key == _API_KEY:
            return _FakeAdminUser()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-API-Key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # --- Mode 2: JWT session cookie ---
    session_token = request.cookies.get("session")
    if session_token:
        try:
            from redirector_app.web.auth import decode_session_token, build_web_admin_user
            username = decode_session_token(session_token)
            if username:
                user = build_web_admin_user(username)
                return _FakeAdminUser(
                    email=user.email,
                    first_name=user.first_name,
                    last_name=user.last_name,
                )
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide X-API-Key header or log in via the web UI.",
        headers={"WWW-Authenticate": "ApiKey"},
    )
