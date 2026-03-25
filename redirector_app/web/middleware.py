"""Custom CSRF protection middleware compatible with FastAPI/Starlette.

Copied from cyberx-event-mgmt/backend/app/middleware/csrf.py and adapted for
the standalone redirector manager. The X-API-Key API routes are added to
exempt_urls so API consumers do not need a CSRF token.
"""
from typing import List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
import secrets
from itsdangerous import URLSafeTimedSerializer, BadSignature


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF protection middleware for FastAPI/Starlette.

    Sets a signed CSRF token cookie and validates it on state-changing requests.
    """

    def __init__(
        self,
        app,
        secret_key: str,
        exempt_urls: List[str] = None,
        cookie_name: str = "csrf_token",
        header_name: str = "X-CSRF-Token",
        cookie_secure: bool = True,
        cookie_samesite: str = "lax",
        cookie_httponly: bool = False,
        cookie_path: str = "/",
        token_max_age: int = 3600,  # 1 hour
        api_key_validator=None,
    ):
        super().__init__(app)
        self.secret_key = secret_key
        self.exempt_urls = exempt_urls or []
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.cookie_secure = cookie_secure
        self.cookie_samesite = cookie_samesite
        self.cookie_httponly = cookie_httponly
        self.cookie_path = cookie_path
        self.token_max_age = token_max_age
        self.serializer = URLSafeTimedSerializer(secret_key)
        self.api_key_validator = api_key_validator

    def _generate_token(self) -> str:
        random_value = secrets.token_urlsafe(32)
        return self.serializer.dumps(random_value)

    def _validate_token(self, token: str) -> bool:
        try:
            self.serializer.loads(token, max_age=self.token_max_age)
            return True
        except (BadSignature, Exception):
            return False

    def _is_exempt(self, path: str) -> bool:
        for exempt_pattern in self.exempt_urls:
            if exempt_pattern.endswith("/*"):
                prefix = exempt_pattern[:-2]
                if path.startswith(prefix):
                    return True
            elif path == exempt_pattern:
                return True
        return False

    def _requires_csrf_check(self, method: str) -> bool:
        return method.upper() in ["POST", "PUT", "DELETE", "PATCH"]

    def _set_csrf_cookie(self, response: Response, token: str, needed: bool):
        if not needed:
            return
        cookie_value = f"{self.cookie_name}={token}; Path={self.cookie_path}"
        if self.cookie_secure:
            cookie_value += "; Secure"
        if self.cookie_samesite:
            cookie_value += f"; SameSite={self.cookie_samesite}"
        if self.cookie_httponly:
            cookie_value += "; HttpOnly"
        response.headers.append("Set-Cookie", cookie_value)

    async def dispatch(self, request: Request, call_next):
        # Skip CSRF only if X-API-Key is present AND valid (prevents bypass with garbage key)
        if self.api_key_validator:
            api_key = request.headers.get("X-API-Key")
            if api_key and self.api_key_validator(api_key):
                response = await call_next(request)
                return response

        csrf_token = request.cookies.get(self.cookie_name)
        new_token_needed = False

        if not csrf_token:
            csrf_token = self._generate_token()
            new_token_needed = True
        elif not self._validate_token(csrf_token):
            csrf_token = self._generate_token()
            new_token_needed = True

        if (
            self._requires_csrf_check(request.method)
            and not self._is_exempt(request.url.path)
        ):
            token_from_header = request.headers.get(self.header_name)

            if not token_from_header:
                resp = JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing"},
                )
                self._set_csrf_cookie(resp, csrf_token, new_token_needed)
                return resp

            if not self._validate_token(token_from_header):
                resp = JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token invalid or expired"},
                )
                self._set_csrf_cookie(resp, csrf_token, new_token_needed)
                return resp

            if token_from_header != csrf_token:
                resp = JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token mismatch"},
                )
                self._set_csrf_cookie(resp, csrf_token, new_token_needed)
                return resp

        response = await call_next(request)
        self._set_csrf_cookie(response, csrf_token, new_token_needed)
        return response
