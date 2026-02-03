"""Pagination utilities."""
from typing import Tuple


def calculate_pagination(
    total: int,
    page: int,
    page_size: int
) -> Tuple[int, int]:
    """
    Calculate pagination values.

    Args:
        total: Total number of items
        page: Current page number (1-indexed)
        page_size: Items per page

    Returns:
        Tuple of (offset, total_pages)

    Example:
        >>> calculate_pagination(total=100, page=2, page_size=20)
        (20, 5)  # offset=20, total_pages=5
    """
    offset = (page - 1) * page_size
    total_pages = (total + page_size - 1) // page_size
    return offset, total_pages
