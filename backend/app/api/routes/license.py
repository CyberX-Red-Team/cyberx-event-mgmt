"""License management API routes.

Product CRUD and dashboard endpoints use session-based admin auth.
VM-facing endpoints (blob, queue/acquire, queue/release) use Bearer token auth
and are CSRF-exempt.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_admin_user
from app.api.exceptions import not_found, bad_request, conflict, unauthorized, server_error
from app.api.utils.dependencies import get_license_service
from app.models.user import User
from app.services.license_service import LicenseService
from app.schemas.license import (
    LicenseProductCreate,
    LicenseProductUpdate,
    LicenseProductResponse,
    LicenseProductDetailResponse,
    LicenseProductListResponse,
    QueueAcquireRequest,
    QueueReleaseRequest,
    LicenseQueueStatus,
    LicenseStats,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/license", tags=["License Management"])


# ── Helper: Extract Bearer token ───────────────────────────

def _extract_bearer_token(authorization: str = Header(...)) -> str:
    """Extract Bearer token from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise unauthorized("Invalid authorization header")
    token = authorization[7:]
    if not token:
        raise unauthorized("Missing bearer token")
    return token


# ── Product Management (admin, session auth) ───────────────

@router.get("/products", response_model=LicenseProductListResponse)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_admin_user),
    service: LicenseService = Depends(get_license_service),
):
    """List license products (paginated)."""
    products, total = await service.list_products(page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size

    return LicenseProductListResponse(
        items=[LicenseProductResponse.model_validate(p) for p in products],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/products", response_model=LicenseProductDetailResponse, status_code=201)
async def create_product(
    data: LicenseProductCreate,
    current_user: User = Depends(get_current_admin_user),
    service: LicenseService = Depends(get_license_service),
):
    """Create a new license product."""
    try:
        product = await service.create_product(
            name=data.name,
            license_blob=data.license_blob,
            description=data.description,
            max_concurrent=data.max_concurrent,
            slot_ttl=data.slot_ttl,
            token_ttl=data.token_ttl,
            download_filename=data.download_filename,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise conflict(f"Product with name '{data.name}' already exists")
        raise

    return LicenseProductDetailResponse.model_validate(product)


@router.get("/products/{product_id}", response_model=LicenseProductDetailResponse)
async def get_product(
    product_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: LicenseService = Depends(get_license_service),
):
    """Get product detail (includes license_blob)."""
    product = await service.get_product(product_id)
    if not product:
        raise not_found("License product", product_id)
    return LicenseProductDetailResponse.model_validate(product)


@router.put("/products/{product_id}", response_model=LicenseProductDetailResponse)
async def update_product(
    product_id: int,
    data: LicenseProductUpdate,
    current_user: User = Depends(get_current_admin_user),
    service: LicenseService = Depends(get_license_service),
):
    """Update a license product."""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise bad_request("No fields to update")

    product = await service.update_product(product_id, **update_data)
    if not product:
        raise not_found("License product", product_id)

    return LicenseProductDetailResponse.model_validate(product)


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: LicenseService = Depends(get_license_service),
):
    """Delete a license product."""
    ok = await service.delete_product(product_id)
    if not ok:
        raise not_found("License product", product_id)
    return {"success": True, "message": "Product deleted"}


# ── VM-facing Endpoints (Bearer token auth, CSRF-exempt) ──

@router.get("/blob")
async def get_license_blob(
    request: Request,
    authorization: str = Header(...),
    service: LicenseService = Depends(get_license_service),
):
    """Get license blob using a single-use Bearer token.

    Called by VMs during cloud-init to retrieve the license file.
    Token is consumed on use and cannot be replayed.
    """
    token = _extract_bearer_token(authorization)
    client_ip = request.client.host if request.client else "unknown"

    license_blob = await service.validate_and_consume_token(token, client_ip)
    if not license_blob:
        raise unauthorized("Invalid, expired, or already-used token")

    return {"license": license_blob}


@router.post("/queue/acquire")
async def acquire_slot(
    data: QueueAcquireRequest,
    request: Request,
    authorization: str = Header(...),
    service: LicenseService = Depends(get_license_service),
):
    """Acquire an install slot for a product.

    Called by VMs to enter the concurrency-limited installation queue.
    Returns {status: "granted", slot_id} or {status: "wait", retry_after}.
    """
    _extract_bearer_token(authorization)
    client_ip = request.client.host if request.client else "unknown"

    result = await service.acquire_slot(
        product_id=data.product_id,
        hostname=data.hostname or "unknown",
        ip=client_ip,
    )

    if result["status"] == "error":
        raise bad_request(result.get("message", "Failed to acquire slot"))

    return result


@router.post("/queue/release")
async def release_slot(
    data: QueueReleaseRequest,
    authorization: str = Header(...),
    service: LicenseService = Depends(get_license_service),
):
    """Release an install slot after completion.

    Called by VMs when installation finishes (success or failure).
    """
    _extract_bearer_token(authorization)

    ok = await service.release_slot(
        slot_id=data.slot_id,
        result=data.result,
        elapsed=data.elapsed,
    )

    if not ok:
        raise not_found("Slot not found")

    return {"success": True, "message": "Slot released"}


# ── Admin Dashboard Endpoints (session auth) ───────────────

@router.get("/queue/status", response_model=list[LicenseQueueStatus])
async def get_queue_status(
    product_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_admin_user),
    service: LicenseService = Depends(get_license_service),
):
    """Get queue status for all or a specific product."""
    statuses = await service.get_queue_status(product_id=product_id)
    return statuses


@router.get("/stats", response_model=LicenseStats)
async def get_license_stats(
    product_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_admin_user),
    service: LicenseService = Depends(get_license_service),
):
    """Get license statistics."""
    stats = await service.get_license_stats(product_id=product_id)
    return LicenseStats(**stats)
