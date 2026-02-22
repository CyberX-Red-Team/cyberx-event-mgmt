"""VPN management API routes."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.dependencies import (
    get_db,
    get_current_admin_user,
    get_current_active_user,
    get_current_sponsor_user,
    permissions
)
from app.api.exceptions import not_found, forbidden, bad_request, conflict, unauthorized, server_error, rate_limited
from app.api.utils.request import extract_client_metadata
from app.api.utils.dependencies import (
    get_vpn_service,
    get_participant_service
)
from app.models.user import User
from app.models.vpn import VPNCredential
from app.models.event import Event
from app.models.app_setting import AppSetting
from app.models.audit_log import AuditLog
from app.services.vpn_service import VPNService
from app.services.participant_service import ParticipantService
from app.schemas.vpn import (
    VPNCredentialResponse,
    VPNCredentialListResponse,
    VPNStats,
    VPNAssignRequest,
    VPNAssignResponse,
    VPNConfigResponse,
    VPNBulkAssignRequest,
    VPNBulkAssignResponse,
    VPNRequestRequest,
    VPNRequestResponse,
    VPNImportResponse,
    VPNMyCredentialsResponse,
    VPNBulkDeleteRequest,
    VPNBulkDeleteResponse,
    VPNRequestBatchesResponse,
    VPNUpdateAssignmentTypeRequest,
    VPNUpdateAssignmentTypeResponse,
    VPNBulkUpdateAssignmentTypeRequest,
    VPNBulkUpdateAssignmentTypeResponse,
    VPNInstancePoolStats,
)
from app.config import get_settings


settings = get_settings()
router = APIRouter(prefix="/api/vpn", tags=["VPN Management"])

# Rate limiting storage (in production, use Redis)
_rate_limit_cache: dict = {}


async def build_vpn_response(
    vpn: VPNCredential,
    db: AsyncSession
) -> VPNCredentialResponse:
    """Build VPN credential response with user info."""
    assigned_email = None
    assigned_name = None

    if vpn.assigned_to_user_id:
        result = await db.execute(
            select(User).where(User.id == vpn.assigned_to_user_id)
        )
        user = result.scalar_one_or_none()
        if user:
            assigned_email = user.email
            assigned_name = f"{user.first_name} {user.last_name}"

    return VPNCredentialResponse(
        id=vpn.id,
        interface_ip=vpn.interface_ip,
        ipv4_address=vpn.ipv4_address,
        endpoint=vpn.endpoint,
        file_hash=vpn.file_hash,
        request_batch_id=vpn.request_batch_id,
        is_available=vpn.is_available,
        assigned_to_user_id=vpn.assigned_to_user_id,
        assigned_at=vpn.assigned_at,
        created_at=vpn.created_at,
        assigned_to_email=assigned_email,
        assigned_to_name=assigned_name
    )


def check_rate_limit(user_id: int, window_minutes: int = 5, max_requests: int = 3) -> bool:
    """
    Check if user has exceeded rate limit for VPN requests.

    Returns True if rate limit exceeded, False if OK to proceed.
    """
    now = datetime.now(timezone.utc)
    cache_key = f"vpn_request_{user_id}"

    if cache_key not in _rate_limit_cache:
        _rate_limit_cache[cache_key] = []

    # Clean old entries
    window_start = now - timedelta(minutes=window_minutes)
    _rate_limit_cache[cache_key] = [
        ts for ts in _rate_limit_cache[cache_key] if ts > window_start
    ]

    # Check limit
    if len(_rate_limit_cache[cache_key]) >= max_requests:
        return True

    # Record this request
    _rate_limit_cache[cache_key].append(now)
    return False


async def create_vpn_audit_log(
    db: AsyncSession,
    user_id: int,
    action: str,
    details: dict,
    request: Optional[Request] = None
) -> None:
    """
    Create an audit log entry for VPN-related actions.

    Args:
        db: Database session
        user_id: User performing the action
        action: Action name (e.g., VPN_REQUEST, VPN_REQUEST_RATE_LIMITED, VPN_REQUEST_FAILED)
        details: Additional details to log (JSON-serializable dict)
        request: Optional FastAPI request object for IP and user agent
    """
    ip_address, user_agent = extract_client_metadata(request)
    audit_log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type="VPN",
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(audit_log)
    await db.commit()


# ============== Admin/Sponsor Endpoints ==============

@router.get("/credentials", response_model=VPNCredentialListResponse)
async def list_vpn_credentials(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    is_available: Optional[bool] = Query(None, description="Filter by availability"),
    search: Optional[str] = Query(None, description="Search by IP or username"),
    current_user: User = Depends(get_current_sponsor_user),
    service: VPNService = Depends(get_vpn_service),
    db: AsyncSession = Depends(get_db)
):
    """List all VPN credentials (admin/sponsor only)."""
    credentials, total = await service.list_credentials(
        page=page,
        page_size=page_size,
        is_available=is_available,
        search=search
    )

    items = []
    for vpn in credentials:
        item = await build_vpn_response(vpn, db)
        items.append(item)

    total_pages = (total + page_size - 1) // page_size

    return VPNCredentialListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/stats", response_model=VPNStats)
async def get_vpn_stats(
    current_user: User = Depends(get_current_sponsor_user),
    service: VPNService = Depends(get_vpn_service)
):
    """Get VPN statistics (admin/sponsor only)."""
    stats = await service.get_statistics()
    return VPNStats(**stats)


@router.post("/assign", response_model=VPNAssignResponse)
async def assign_vpn(
    data: VPNAssignRequest,
    current_user: User = Depends(get_current_sponsor_user),
    vpn_service: VPNService = Depends(get_vpn_service),
    participant_service: ParticipantService = Depends(get_participant_service)
):
    """Assign VPN(s) to a participant (admin/sponsor only)."""
    # Verify participant exists
    participant = await participant_service.get_participant(data.participant_id)
    if not participant:
        raise not_found("Participant not found")

    # Check permission to assign VPN to this participant
    permissions.can_assign_vpn_to_participant(current_user, participant)

    # Assign requested number of VPNs
    count, message, vpns = await vpn_service.request_vpns(
        user_id=data.participant_id,
        count=data.count,
        username=participant.pandas_username
    )

    return VPNAssignResponse(
        success=count > 0,
        message=message,
        assigned_count=count,
        participant_id=data.participant_id
    )


@router.post("/bulk-assign", response_model=VPNBulkAssignResponse)
async def bulk_assign_vpn(
    data: VPNBulkAssignRequest,
    current_user: User = Depends(get_current_admin_user),
    vpn_service: VPNService = Depends(get_vpn_service),
    participant_service: ParticipantService = Depends(get_participant_service)
):
    """Bulk assign VPN to multiple participants (admin only)."""
    total_assigned = 0
    failed_ids = []
    errors = []

    for participant_id in data.participant_ids:
        participant = await participant_service.get_participant(participant_id)
        if not participant:
            failed_ids.append(participant_id)
            errors.append(f"Participant {participant_id} not found")
            continue

        count, message, _ = await vpn_service.request_vpns(
            user_id=participant_id,
            count=data.count_per_participant,
            username=participant.pandas_username
        )

        if count > 0:
            total_assigned += count
        else:
            failed_ids.append(participant_id)
            errors.append(f"Participant {participant_id}: {message}")

    return VPNBulkAssignResponse(
        success=total_assigned > 0,
        message=f"Assigned {total_assigned} VPN credentials",
        assigned_count=total_assigned,
        failed_ids=failed_ids,
        errors=errors
    )


@router.post("/import", response_model=VPNImportResponse)
async def import_vpn_configs(
    file: UploadFile = File(..., description="ZIP file containing WireGuard .conf files"),
    endpoint: Optional[str] = Query(None, description="Optional VPN server endpoint override (ip:port)"),
    assignment_type: str = Query("USER_REQUESTABLE", description="Assignment type: USER_REQUESTABLE | INSTANCE_AUTO_ASSIGN | RESERVED"),
    current_user: User = Depends(get_current_admin_user),
    service: VPNService = Depends(get_vpn_service)
):
    """
    Import VPN credentials from a ZIP file (admin only).

    The ZIP file should contain WireGuard .conf files with [Interface], [Peer], and Endpoint sections.
    The endpoint will be parsed from each config file unless an override is provided.

    Assignment types:
    - USER_REQUESTABLE: VPNs available for participant self-service requests (default)
    - INSTANCE_AUTO_ASSIGN: VPNs automatically assigned to instances in events with vpn_available=true
    - RESERVED: VPNs held in reserve, not available for auto-assignment
    """
    # Validate assignment_type
    valid_types = ["USER_REQUESTABLE", "INSTANCE_AUTO_ASSIGN", "RESERVED"]
    if assignment_type not in valid_types:
        raise bad_request(f"Invalid assignment_type. Must be one of: {', '.join(valid_types)}")

    if not file.filename.endswith('.zip'):
        raise bad_request("File must be a ZIP archive")

    # Read file content
    content = await file.read()

    # Limit file size (50MB)
    if len(content) > 50 * 1024 * 1024:
        raise bad_request("File too large (max 50MB)")

    imported, skipped, errors = await service.import_from_zip(content, endpoint, assignment_type)

    return VPNImportResponse(
        success=imported > 0,
        message=f"Imported {imported} VPN credentials, skipped {skipped}",
        imported_count=imported,
        skipped_count=skipped,
        errors=errors[:10]  # Limit error messages
    )


@router.get("/credentials/{vpn_id}", response_model=VPNCredentialResponse)
async def get_vpn_credential(
    vpn_id: int,
    current_user: User = Depends(get_current_sponsor_user),
    service: VPNService = Depends(get_vpn_service),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific VPN credential (admin/sponsor only)."""
    vpn = await service.get_credential(vpn_id)
    if not vpn:
        raise not_found("VPN credential not found")

    return await build_vpn_response(vpn, db)


@router.get("/participant/{participant_id}/credentials")
async def get_participant_vpn_credentials(
    participant_id: int,
    current_user: User = Depends(get_current_sponsor_user),
    vpn_service: VPNService = Depends(get_vpn_service),
    participant_service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """Get all VPN credentials for a participant (admin/sponsor only)."""
    participant = await participant_service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant not found")

    # Check permission
    permissions.can_view_participant(current_user, participant)

    credentials = await vpn_service.get_user_credentials(participant_id)

    items = []
    for vpn in credentials:
        item = await build_vpn_response(vpn, db)
        items.append(item)

    return VPNMyCredentialsResponse(
        credentials=items,
        total=len(items)
    )


@router.get("/participant/{participant_id}/config/download")
async def download_participant_vpn_configs(
    participant_id: int,
    naming_pattern: str = Query("simnet_{ipv4_address}.conf", description="Filename pattern"),
    current_user: User = Depends(get_current_sponsor_user),
    vpn_service: VPNService = Depends(get_vpn_service),
    participant_service: ParticipantService = Depends(get_participant_service)
):
    """Download all WireGuard configs for a participant as ZIP (admin/sponsor only)."""
    import zipfile
    import io

    participant = await participant_service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant not found")

    # Check permission
    permissions.can_view_participant(current_user, participant)

    credentials = await vpn_service.get_user_credentials(participant_id)
    if not credentials:
        raise not_found("Participant does not have any VPN credentials")

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, vpn in enumerate(credentials, 1):
            config = vpn_service.generate_wireguard_config(vpn)
            filename = vpn_service.format_filename(naming_pattern, vpn, participant, i)
            zf.writestr(filename, config)

    zip_buffer.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=vpn_configs_{participant.pandas_username or participant_id}.zip"
        }
    )


# ============== Participant Self-Service Endpoints ==============

@router.post("/request", response_model=VPNRequestResponse)
async def request_vpn_credentials(
    data: VPNRequestRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    service: VPNService = Depends(get_vpn_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Request VPN credentials (participant self-service).

    - Maximum 25 VPNs per request
    - Rate limited to prevent pool exhaustion
    - Requires VPN to be enabled for current active event
    - All requests are audited (success, rate-limited, and failures)
    """
    # Check if VPN is available for current event
    result = await db.execute(
        select(Event).where(Event.is_active == True).order_by(Event.year.desc())
    )
    active_event = result.scalar_one_or_none()

    if not active_event:
        raise forbidden("No active event found. VPN credentials are not currently available.")

    # Check VPN availability
    # Sponsors can request VPN in test mode, everyone else needs vpn_available
    is_sponsor = current_user.role == 'sponsor' or current_user.is_sponsor
    vpn_allowed = active_event.vpn_available or (active_event.test_mode and is_sponsor)

    if not vpn_allowed:
        raise forbidden(f"VPN access for {active_event.name} is not yet available. Please check back closer to the event date.")

    # Check rate limit
    if check_rate_limit(current_user.id):
        # Log rate-limited request
        await create_vpn_audit_log(
            db=db,
            user_id=current_user.id,
            action="VPN_REQUEST_RATE_LIMITED",
            details={
                "requested_count": data.count,
                "event_id": active_event.id,
                "event_name": active_event.name,
                "reason": "Rate limit exceeded (max 3 requests per 5 minutes)"
            },
            request=request
        )
        raise rate_limited("Too many VPN requests. Please wait a few minutes before trying again.")

    count, message, vpns = await service.request_vpns(
        user_id=current_user.id,
        count=data.count,
        username=current_user.pandas_username
    )

    # Get total VPNs for user
    total = await service.get_user_vpn_count(current_user.id)

    # Log the request result
    if count > 0:
        # Successful request
        await create_vpn_audit_log(
            db=db,
            user_id=current_user.id,
            action="VPN_REQUEST_SUCCESS",
            details={
                "requested_count": data.count,
                "assigned_count": count,
                "total_vpns": total,
                "event_id": active_event.id,
                "event_name": active_event.name,
                "vpn_ids": [vpn.id for vpn in vpns],
                "batch_id": vpns[0].request_batch_id if vpns else None
            },
            request=request
        )
    else:
        # Failed request (no credentials available)
        await create_vpn_audit_log(
            db=db,
            user_id=current_user.id,
            action="VPN_REQUEST_FAILED",
            details={
                "requested_count": data.count,
                "assigned_count": 0,
                "reason": "No available VPN credentials in pool",
                "event_id": active_event.id,
                "event_name": active_event.name
            },
            request=request
        )

    return VPNRequestResponse(
        success=count > 0,
        message=message,
        assigned_count=count,
        total_vpns=total
    )


@router.get("/my-credentials", response_model=VPNMyCredentialsResponse)
async def get_my_vpn_credentials(
    current_user: User = Depends(get_current_active_user),
    service: VPNService = Depends(get_vpn_service),
    db: AsyncSession = Depends(get_db)
):
    """Get all VPN credentials assigned to current user."""
    credentials = await service.get_user_credentials(current_user.id)

    items = []
    for vpn in credentials:
        item = await build_vpn_response(vpn, db)
        items.append(item)

    return VPNMyCredentialsResponse(
        credentials=items,
        total=len(items)
    )


@router.get("/my-config", response_model=VPNConfigResponse)
async def get_my_vpn_config(
    current_user: User = Depends(get_current_active_user),
    service: VPNService = Depends(get_vpn_service)
):
    """Get current user's first WireGuard configuration (for backwards compatibility)."""
    vpn = await service.get_user_credential(current_user.id)
    if not vpn:
        raise not_found("You do not have any VPN credentials")

    config = service.generate_wireguard_config(vpn)
    filename = service.get_config_filename(current_user, vpn)

    return VPNConfigResponse(config=config, filename=filename)


@router.get("/my-config/download")
async def download_my_vpn_config(
    vpn_id: Optional[int] = Query(None, description="Specific VPN ID to download"),
    current_user: User = Depends(get_current_active_user),
    service: VPNService = Depends(get_vpn_service)
):
    """Download a specific WireGuard configuration file or the first one if no ID specified."""
    if vpn_id:
        # Download specific VPN by ID
        vpn = await service.get_credential(vpn_id)
        if not vpn:
            raise not_found("VPN credential not found")
        # Verify ownership
        if vpn.assigned_to_user_id != current_user.id:
            raise forbidden("This VPN credential is not assigned to you")
    else:
        # Download first VPN (backwards compatibility)
        vpn = await service.get_user_credential(current_user.id)
        if not vpn:
            raise not_found("You do not have any VPN credentials")

    config = service.generate_wireguard_config(vpn)
    filename = service.get_config_filename(current_user, vpn)

    return PlainTextResponse(
        content=config,
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/my-configs/download")
async def download_all_my_vpn_configs(
    naming_pattern: str = Query("simnet_{ipv4_address}.conf", description="Filename pattern"),
    current_user: User = Depends(get_current_active_user),
    service: VPNService = Depends(get_vpn_service)
):
    """Download all WireGuard configs for current user as ZIP with SHA256 hash file."""
    import zipfile
    import io

    credentials = await service.get_user_credentials(current_user.id)
    if not credentials:
        raise not_found("You do not have any VPN credentials")

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    hash_lines = []

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, vpn in enumerate(credentials, 1):
            config = service.generate_wireguard_config(vpn)
            filename = service.format_filename(naming_pattern, vpn, current_user, i)
            zf.writestr(filename, config)

            # Add hash to list
            if vpn.file_hash:
                hash_lines.append(f"{vpn.file_hash}  {filename}")

        # Add SHA256SUMS file
        if hash_lines:
            zf.writestr("SHA256SUMS", "\n".join(hash_lines) + "\n")

    zip_buffer.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=my_vpn_configs.zip"
        }
    )


@router.get("/my-request-batches", response_model=VPNRequestBatchesResponse)
async def get_my_request_batches(
    current_user: User = Depends(get_current_active_user),
    service: VPNService = Depends(get_vpn_service)
):
    """Get list of VPN request batches for current user."""
    batches = await service.get_user_request_batches(current_user.id)

    from app.schemas.vpn import VPNRequestBatch
    batch_items = [
        VPNRequestBatch(
            batch_id=b['batch_id'],
            requested_at=b['requested_at'],
            count=b['count']
        )
        for b in batches
    ]

    return VPNRequestBatchesResponse(
        batches=batch_items,
        total_batches=len(batch_items)
    )


@router.get("/download-batch/{batch_id}")
async def download_batch_configs(
    batch_id: str,
    naming_pattern: str = Query("simnet_{ipv4_address}.conf", description="Filename pattern"),
    current_user: User = Depends(get_current_active_user),
    service: VPNService = Depends(get_vpn_service)
):
    """Download all VPN configs from a specific request batch as ZIP with SHA256 hash file."""
    import zipfile
    import io

    credentials = await service.get_credentials_by_batch(current_user.id, batch_id)
    if not credentials:
        raise not_found("No VPN credentials found for this batch")

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    hash_lines = []

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, vpn in enumerate(credentials, 1):
            config = service.generate_wireguard_config(vpn)
            filename = service.format_filename(naming_pattern, vpn, current_user, i)
            zf.writestr(filename, config)

            # Add hash to list
            if vpn.file_hash:
                hash_lines.append(f"{vpn.file_hash}  {filename}")

        # Add SHA256SUMS file
        if hash_lines:
            zf.writestr("SHA256SUMS", "\n".join(hash_lines) + "\n")

    zip_buffer.seek(0)

    from fastapi.responses import StreamingResponse
    batch_short = batch_id[:8]  # Use first 8 chars of batch ID in filename
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=vpn_batch_{batch_short}.zip"
        }
    )


@router.get("/available-count")
async def get_available_vpn_count(
    current_user: User = Depends(get_current_active_user),
    service: VPNService = Depends(get_vpn_service)
):
    """Get count of available VPN credentials."""
    count = await service.get_available_count()
    return {"available_count": count}


@router.post("/bulk-delete", response_model=VPNBulkDeleteResponse)
async def bulk_delete_vpn_credentials(
    request: VPNBulkDeleteRequest,
    current_user: User = Depends(get_current_admin_user),
    service: VPNService = Depends(get_vpn_service)
):
    """
    Delete multiple VPN credentials by ID.

    Requires admin role.
    """
    if not request.vpn_ids:
        raise bad_request("No VPN credential IDs provided")

    deleted_count, failed_ids, errors = await service.delete_credentials(request.vpn_ids)

    success = deleted_count > 0
    message = f"Deleted {deleted_count} VPN credential(s)"
    if failed_ids:
        message += f", {len(failed_ids)} failed"

    return VPNBulkDeleteResponse(
        success=success,
        message=message,
        deleted_count=deleted_count,
        failed_ids=failed_ids,
        errors=errors
    )


@router.post("/delete-all", response_model=VPNBulkDeleteResponse)
async def delete_all_vpn_credentials(
    current_user: User = Depends(get_current_admin_user),
    service: VPNService = Depends(get_vpn_service)
):
    """
    Delete all VPN credentials.

    Requires admin role.
    """
    deleted_count = await service.delete_all_credentials()

    return VPNBulkDeleteResponse(
        success=True,
        message=f"Deleted all {deleted_count} VPN credential(s)",
        deleted_count=deleted_count,
        failed_ids=[],
        errors=[]
    )


@router.get("/naming-pattern")
async def get_vpn_naming_pattern(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the global VPN filename naming pattern.

    Available to all authenticated users.
    """
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == 'vpn_naming_pattern')
    )
    setting = result.scalar_one_or_none()

    # Return default if not found
    pattern = setting.value if setting else 'simnet_{ipv4_address}.conf'

    return {"pattern": pattern}


@router.post("/naming-pattern")
async def set_vpn_naming_pattern(
    pattern: str = Query(..., description="Naming pattern for VPN config files"),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Set the global VPN filename naming pattern.

    Requires admin role. This pattern will be used by all participants when downloading VPN configs.
    """
    from sqlalchemy.dialects.postgresql import insert

    # Upsert the setting
    stmt = insert(AppSetting).values(
        key='vpn_naming_pattern',
        value=pattern,
        description='Default filename pattern for VPN config downloads'
    ).on_conflict_do_update(
        index_elements=['key'],
        set_={'value': pattern, 'updated_at': func.now()}
    )

    await db.execute(stmt)
    await db.commit()

    return {"success": True, "pattern": pattern}


# ─── VPN Assignment Type Management ─────────────────────────────────────────


@router.patch("/credentials/{vpn_id}/assignment-type", response_model=VPNUpdateAssignmentTypeResponse)
async def update_vpn_assignment_type(
    vpn_id: int,
    data: VPNUpdateAssignmentTypeRequest,
    current_user: User = Depends(get_current_admin_user),
    service: VPNService = Depends(get_vpn_service)
):
    """
    Update VPN credential assignment type (admin only).

    Can only change assignment type if VPN is not currently assigned to a user or instance.

    Assignment types:
    - USER_REQUESTABLE: Available for participant self-service requests
    - INSTANCE_AUTO_ASSIGN: Automatically assigned to instances in events with vpn_available=true
    - RESERVED: Held in reserve, not available for auto-assignment
    """
    success, message = await service.update_assignment_type(vpn_id, data.assignment_type)

    if not success:
        if "not found" in message.lower():
            raise not_found("VPN credential", vpn_id)
        raise bad_request(message)

    return VPNUpdateAssignmentTypeResponse(
        success=True,
        message=message,
        vpn_id=vpn_id,
        new_assignment_type=data.assignment_type
    )


@router.post("/bulk-update-assignment-type", response_model=VPNBulkUpdateAssignmentTypeResponse)
async def bulk_update_vpn_assignment_type(
    data: VPNBulkUpdateAssignmentTypeRequest,
    current_user: User = Depends(get_current_admin_user),
    service: VPNService = Depends(get_vpn_service)
):
    """
    Bulk update VPN credential assignment types (admin only).

    Updates multiple VPN credentials to the same assignment type.
    Skips VPNs that are currently assigned to users or instances.
    """
    success_count, skipped_count, errors = await service.bulk_update_assignment_type(
        data.vpn_ids,
        data.assignment_type
    )

    return VPNBulkUpdateAssignmentTypeResponse(
        success=success_count > 0,
        message=f"Updated {success_count} VPN(s), skipped {skipped_count}",
        success_count=success_count,
        skipped_count=skipped_count,
        errors=errors[:10]  # Limit error messages
    )


@router.get("/stats/instance-pool", response_model=VPNInstancePoolStats)
async def get_instance_pool_stats(
    current_user: User = Depends(get_current_admin_user),
    service: VPNService = Depends(get_vpn_service)
):
    """
    Get statistics for INSTANCE_AUTO_ASSIGN VPN pool (admin only).

    Returns counts of total, available, and assigned INSTANCE_AUTO_ASSIGN VPNs.
    Useful for monitoring VPN pool capacity before creating events.
    """
    stats = await service.get_instance_pool_stats()

    return VPNInstancePoolStats(
        total=stats["total"],
        available=stats["available"],
        assigned=stats["assigned"]
    )
