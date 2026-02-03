"""Standard HTTP exceptions for common cases."""
from typing import Optional
from fastapi import HTTPException, status


def not_found(resource: str = "Resource", resource_id: Optional[int] = None) -> HTTPException:
    """
    Return 404 Not Found exception.

    Args:
        resource: Name of the resource that wasn't found
        resource_id: Optional ID of the resource

    Returns:
        HTTPException with 404 status code

    Examples:
        raise not_found("Event", 123)  # "Event with ID 123 not found"
        raise not_found("User")         # "User not found"
    """
    detail = f"{resource} not found"
    if resource_id:
        detail = f"{resource} with ID {resource_id} not found"
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail
    )


def forbidden(message: str = "Not authorized to perform this action") -> HTTPException:
    """
    Return 403 Forbidden exception.

    Args:
        message: Custom error message

    Returns:
        HTTPException with 403 status code

    Examples:
        raise forbidden()  # Uses default message
        raise forbidden("Only administrators can perform this action")
    """
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=message
    )


def bad_request(message: str) -> HTTPException:
    """
    Return 400 Bad Request exception.

    Args:
        message: Error message describing what was invalid

    Returns:
        HTTPException with 400 status code

    Examples:
        raise bad_request("Invalid email format")
        raise bad_request("Missing required field: name")
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message
    )


def conflict(message: str) -> HTTPException:
    """
    Return 409 Conflict exception.

    Args:
        message: Error message describing the conflict

    Returns:
        HTTPException with 409 status code

    Examples:
        raise conflict("Email already exists")
        raise conflict("Cannot delete active event")
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=message
    )


def unauthorized(message: str = "Incorrect username or password") -> HTTPException:
    """
    Return 401 Unauthorized exception.

    Args:
        message: Custom error message

    Returns:
        HTTPException with 401 status code

    Examples:
        raise unauthorized()  # Uses default message
        raise unauthorized("Invalid API token")
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message
    )


def server_error(message: str = "Internal server error") -> HTTPException:
    """
    Return 500 Internal Server Error exception.

    Args:
        message: Error message describing what went wrong

    Returns:
        HTTPException with 500 status code

    Examples:
        raise server_error("Failed to connect to database")
        raise server_error("Unexpected error during processing")
    """
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=message
    )


def rate_limited(message: str = "Too many requests. Please try again later.") -> HTTPException:
    """
    Return 429 Too Many Requests exception.

    Args:
        message: Error message describing the rate limit

    Returns:
        HTTPException with 429 status code

    Examples:
        raise rate_limited()  # Uses default message
        raise rate_limited("VPN request limit exceeded. Please wait before requesting more.")
    """
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=message
    )
