"""Request utility functions."""
from typing import Optional, Tuple
from fastapi import Request


def extract_client_metadata(request: Request) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract IP address and user agent from request.

    Args:
        request: FastAPI Request object

    Returns:
        Tuple of (ip_address, user_agent)
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent
