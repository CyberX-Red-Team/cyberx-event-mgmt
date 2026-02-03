"""Custom CSRF protection middleware compatible with FastAPI/Starlette."""
from typing import List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.datastructures import MutableHeaders
from itsdangerous import URLSafeTimedSerializer, BadSignature
import secrets


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
    ):
        """
        Initialize CSRF middleware.
        
        Args:
            app: The ASGI application
            secret_key: Secret key for signing tokens
            exempt_urls: List of URL paths exempt from CSRF checks
            cookie_name: Name of the CSRF cookie
            header_name: Name of the CSRF header
            cookie_secure: Whether to set Secure flag on cookie
            cookie_samesite: SameSite cookie policy
            cookie_httponly: Whether to set HttpOnly flag
            cookie_path: Cookie path
            token_max_age: Max age of tokens in seconds
        """
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
    
    def _generate_token(self) -> str:
        """Generate a new CSRF token."""
        random_value = secrets.token_urlsafe(32)
        return self.serializer.dumps(random_value)
    
    def _validate_token(self, token: str) -> bool:
        """
        Validate a CSRF token.
        
        Args:
            token: The token to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            self.serializer.loads(token, max_age=self.token_max_age)
            return True
        except (BadSignature, Exception):
            return False
    
    def _is_exempt(self, path: str) -> bool:
        """Check if a path is exempt from CSRF protection."""
        return path in self.exempt_urls
    
    def _requires_csrf_check(self, method: str) -> bool:
        """Check if HTTP method requires CSRF validation."""
        return method.upper() in ["POST", "PUT", "DELETE", "PATCH"]
    
    async def dispatch(self, request: Request, call_next):
        """Process request with CSRF protection."""
        # Get or create CSRF token
        csrf_token = request.cookies.get(self.cookie_name)
        
        if not csrf_token:
            # Generate new token if none exists
            csrf_token = self._generate_token()
        
        # Check if request requires CSRF validation
        if (
            self._requires_csrf_check(request.method)
            and not self._is_exempt(request.url.path)
        ):
            # Get token from header or form data
            token_from_header = request.headers.get(self.header_name)
            
            # Validate token
            if not token_from_header:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing"}
                )
            
            if not self._validate_token(token_from_header):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token invalid or expired"}
                )
            
            # Verify token matches cookie
            if token_from_header != csrf_token:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token mismatch"}
                )
        
        # Process request
        response = await call_next(request)
        
        # Set CSRF cookie on response
        if not request.cookies.get(self.cookie_name):
            # Build cookie value
            cookie_value = f"{self.cookie_name}={csrf_token}; Path={self.cookie_path}"
            
            if self.cookie_secure:
                cookie_value += "; Secure"
            
            if self.cookie_samesite:
                cookie_value += f"; SameSite={self.cookie_samesite}"
            
            if self.cookie_httponly:
                cookie_value += "; HttpOnly"
            
            # Add cookie to response
            if isinstance(response, Response):
                response.headers.append("Set-Cookie", cookie_value)
        
        return response
