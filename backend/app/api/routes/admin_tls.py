"""Admin routes for TLS certificate management (CA chains and step-ca sidecars)."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.user import User
from app.models.tls_certificate import CAChain, CAChainStatus, TLSCertificate, TLSCertificateStatus
from app.dependencies import get_current_admin_user
from app.services.stepca_service import StepCAService
from app.services.audit_service import AuditService
from app.utils.encryption import encrypt_field, decrypt_field
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/tls", tags=["admin-tls"])


# -------------------------------------------------------------------------
# Schemas
# -------------------------------------------------------------------------

class CAChainResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    event_id: int
    step_ca_status: str
    step_ca_url: Optional[str]
    render_service_id: Optional[str]
    default_duration: str
    allow_wildcard: bool
    created_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    certificate_count: int = 0

    model_config = {"from_attributes": True}


class TLSCertificateResponse(BaseModel):
    id: int
    user_id: int
    user_email: str
    user_name: str
    event_id: int
    ca_chain_id: int
    ca_chain_name: str
    common_name: str
    sans: Optional[list[str]]
    is_wildcard: bool
    serial_number: Optional[str]
    status: str
    issued_at: Optional[datetime]
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    revocation_reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# -------------------------------------------------------------------------
# CA Chain endpoints
# -------------------------------------------------------------------------

@router.post("/ca-chains")
async def create_ca_chain(
    name: str = Form(...),
    description: str = Form(None),
    event_id: int = Form(...),
    default_duration: str = Form("2160h"),
    allow_wildcard: bool = Form(True),
    root_cert: UploadFile = File(...),
    root_key: UploadFile = File(...),
    intermediate_cert: UploadFile = File(...),
    intermediate_key: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Create a new CA chain with uploaded PEM files.

    Validates PEM format, chain integrity, encrypts private keys,
    and stores all files in R2.
    """
    stepca_service = StepCAService()

    # Read uploaded files
    root_cert_bytes = await root_cert.read()
    root_key_bytes = await root_key.read()
    intermediate_cert_bytes = await intermediate_cert.read()
    intermediate_key_bytes = await intermediate_key.read()

    # Validate PEM format
    try:
        stepca_service.validate_pem_certificate(root_cert_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid root certificate: {e}")

    try:
        stepca_service.validate_pem_private_key(root_key_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid root private key: {e}")

    try:
        stepca_service.validate_pem_certificate(intermediate_cert_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid intermediate certificate: {e}")

    try:
        stepca_service.validate_pem_private_key(intermediate_key_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid intermediate private key: {e}")

    # Validate chain (intermediate signed by root)
    try:
        stepca_service.validate_chain(root_cert_bytes, intermediate_cert_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Chain validation failed: {e}")

    # Create DB record first to get the ID
    ca_chain = CAChain(
        name=name,
        description=description,
        event_id=event_id,
        default_duration=default_duration,
        allow_wildcard=allow_wildcard,
        step_ca_status=CAChainStatus.STOPPED.value,
        created_by_user_id=current_user.id,
    )
    db.add(ca_chain)
    await db.flush()  # Get the ID

    # Upload files to R2
    prefix = stepca_service.get_ca_files_r2_prefix(ca_chain.id)

    r2_keys = {
        "root_cert": f"{prefix}/root_ca.crt",
        "root_key": f"{prefix}/root_ca.key",
        "intermediate_cert": f"{prefix}/intermediate_ca.crt",
        "intermediate_key": f"{prefix}/intermediate_ca.key",
    }

    # Upload all files (encrypt private keys before upload)
    encrypted_root_key = encrypt_field(root_key_bytes.decode("utf-8"))
    encrypted_intermediate_key = encrypt_field(intermediate_key_bytes.decode("utf-8"))

    stepca_service.upload_to_r2(r2_keys["root_cert"], root_cert_bytes)
    stepca_service.upload_to_r2(r2_keys["root_key"], encrypted_root_key.encode("utf-8"))
    stepca_service.upload_to_r2(r2_keys["intermediate_cert"], intermediate_cert_bytes)
    stepca_service.upload_to_r2(r2_keys["intermediate_key"], encrypted_intermediate_key.encode("utf-8"))

    # Store R2 keys in DB
    ca_chain.root_cert_r2_key = r2_keys["root_cert"]
    ca_chain.root_key_r2_key = r2_keys["root_key"]
    ca_chain.intermediate_cert_r2_key = r2_keys["intermediate_cert"]
    ca_chain.intermediate_key_r2_key = r2_keys["intermediate_key"]

    await db.commit()
    await db.refresh(ca_chain)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="ca_chain_create",
        resource_type="ca_chain",
        details={"message": f"Created CA chain '{name}'", "ca_chain_id": ca_chain.id}
    )

    return {
        "success": True,
        "ca_chain_id": ca_chain.id,
        "message": f"CA chain '{name}' created. Use the Initialize endpoint to deploy the step-ca service.",
    }


@router.get("/ca-chains")
async def list_ca_chains(
    event_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """List all CA chains with certificate counts."""
    query = select(CAChain)
    if event_id:
        query = query.where(CAChain.event_id == event_id)
    query = query.order_by(CAChain.created_at.desc())

    result = await db.execute(query)
    chains = result.scalars().all()

    # Get certificate counts
    count_query = select(
        TLSCertificate.ca_chain_id,
        func.count(TLSCertificate.id).label("count"),
    ).group_by(TLSCertificate.ca_chain_id)
    count_result = await db.execute(count_query)
    cert_counts = {row[0]: row[1] for row in count_result.all()}

    response = []
    for chain in chains:
        response.append({
            "id": chain.id,
            "name": chain.name,
            "description": chain.description,
            "event_id": chain.event_id,
            "step_ca_status": chain.step_ca_status,
            "step_ca_url": chain.step_ca_url,
            "render_service_id": chain.render_service_id,
            "default_duration": chain.default_duration,
            "allow_wildcard": chain.allow_wildcard,
            "created_by_user_id": chain.created_by_user_id,
            "created_at": chain.created_at,
            "updated_at": chain.updated_at,
            "certificate_count": cert_counts.get(chain.id, 0),
        })

    return response


@router.get("/ca-chains/{chain_id}")
async def get_ca_chain(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Get CA chain details."""
    result = await db.execute(
        select(CAChain).where(CAChain.id == chain_id)
    )
    chain = result.scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="CA chain not found")

    # Get cert count
    count_result = await db.execute(
        select(func.count(TLSCertificate.id)).where(
            TLSCertificate.ca_chain_id == chain_id
        )
    )
    cert_count = count_result.scalar() or 0

    return {
        "id": chain.id,
        "name": chain.name,
        "description": chain.description,
        "event_id": chain.event_id,
        "step_ca_status": chain.step_ca_status,
        "step_ca_url": chain.step_ca_url,
        "render_service_id": chain.render_service_id,
        "default_duration": chain.default_duration,
        "allow_wildcard": chain.allow_wildcard,
        "created_by_user_id": chain.created_by_user_id,
        "created_at": chain.created_at,
        "updated_at": chain.updated_at,
        "certificate_count": cert_count,
    }


@router.delete("/ca-chains/{chain_id}")
async def delete_ca_chain(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Delete a CA chain. Must have no issued certificates."""
    result = await db.execute(
        select(CAChain).where(CAChain.id == chain_id)
    )
    chain = result.scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="CA chain not found")

    # Check for issued certs
    cert_count_result = await db.execute(
        select(func.count(TLSCertificate.id)).where(
            TLSCertificate.ca_chain_id == chain_id,
            TLSCertificate.status == TLSCertificateStatus.ISSUED.value,
        )
    )
    cert_count = cert_count_result.scalar() or 0
    if cert_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete CA chain with {cert_count} active certificate(s). Revoke them first.",
        )

    # Delete Render service if exists
    stepca_service = StepCAService()
    await stepca_service.delete_instance(chain, db)

    # Delete R2 files
    for key in [chain.root_cert_r2_key, chain.root_key_r2_key,
                chain.intermediate_cert_r2_key, chain.intermediate_key_r2_key]:
        if key:
            stepca_service.delete_from_r2(key)

    await db.delete(chain)
    await db.commit()

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="ca_chain_delete",
        resource_type="ca_chain",
        details={"message": f"Deleted CA chain '{chain.name}'", "ca_chain_id": chain_id}
    )

    return {"success": True, "message": f"CA chain '{chain.name}' deleted"}


# -------------------------------------------------------------------------
# step-ca Sidecar Lifecycle
# -------------------------------------------------------------------------

@router.post("/ca-chains/{chain_id}/initialize")
async def initialize_ca_chain(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Initialize the step-ca Render service for this CA chain.

    Downloads CA files from R2, creates a new Render private service
    with the CA files as base64 env vars, and waits for it to deploy.
    """
    result = await db.execute(
        select(CAChain).where(CAChain.id == chain_id)
    )
    chain = result.scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="CA chain not found")

    if chain.render_service_id:
        raise HTTPException(status_code=400, detail="CA chain already has a Render service. Stop and delete it first.")

    stepca_service = StepCAService()

    # Download CA files from R2
    root_cert_bytes = stepca_service.download_from_r2(chain.root_cert_r2_key)
    root_key_encrypted = stepca_service.download_from_r2(chain.root_key_r2_key)
    intermediate_cert_bytes = stepca_service.download_from_r2(chain.intermediate_cert_r2_key)
    intermediate_key_encrypted = stepca_service.download_from_r2(chain.intermediate_key_r2_key)

    if not all([root_cert_bytes, root_key_encrypted, intermediate_cert_bytes, intermediate_key_encrypted]):
        raise HTTPException(status_code=500, detail="Failed to download CA files from R2")

    # Decrypt private keys
    root_key_bytes = decrypt_field(root_key_encrypted.decode("utf-8")).encode("utf-8")
    intermediate_key_bytes = decrypt_field(intermediate_key_encrypted.decode("utf-8")).encode("utf-8")

    success = await stepca_service.initialize_ca_chain(
        ca_chain=chain,
        root_cert_bytes=root_cert_bytes,
        root_key_bytes=root_key_bytes,
        intermediate_cert_bytes=intermediate_cert_bytes,
        intermediate_key_bytes=intermediate_key_bytes,
        db=db,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to initialize step-ca service")

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="ca_chain_initialize",
        resource_type="ca_chain",
        details={"message": f"Initialized step-ca for '{chain.name}'", "ca_chain_id": chain_id}
    )

    return {
        "success": True,
        "message": f"step-ca service initialized for '{chain.name}'",
        "render_service_id": chain.render_service_id,
    }


@router.post("/ca-chains/{chain_id}/start")
async def start_ca_chain(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Resume the step-ca Render service for this CA chain."""
    result = await db.execute(
        select(CAChain).where(CAChain.id == chain_id)
    )
    chain = result.scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="CA chain not found")

    if not chain.render_service_id:
        raise HTTPException(status_code=400, detail="CA chain has no Render service. Initialize it first.")

    stepca_service = StepCAService()
    success = await stepca_service.start_instance(chain, db)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to start step-ca service")

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="ca_chain_start",
        resource_type="ca_chain",
        details={"message": f"Started step-ca for '{chain.name}'"}
    )

    return {"success": True, "message": f"step-ca for '{chain.name}' is now running"}


@router.post("/ca-chains/{chain_id}/stop")
async def stop_ca_chain(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Suspend the step-ca Render service for this CA chain."""
    result = await db.execute(
        select(CAChain).where(CAChain.id == chain_id)
    )
    chain = result.scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="CA chain not found")

    if not chain.render_service_id:
        raise HTTPException(status_code=400, detail="CA chain has no Render service")

    stepca_service = StepCAService()
    success = await stepca_service.stop_instance(chain, db)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop step-ca service")

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="ca_chain_stop",
        resource_type="ca_chain",
        details={"message": f"Stopped step-ca for '{chain.name}'"}
    )

    return {"success": True, "message": f"step-ca for '{chain.name}' suspended"}


@router.get("/ca-chains/{chain_id}/status")
async def get_ca_chain_status(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Get the current status of the step-ca service for this CA chain."""
    result = await db.execute(
        select(CAChain).where(CAChain.id == chain_id)
    )
    chain = result.scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="CA chain not found")

    stepca_service = StepCAService()
    actual_status = await stepca_service.get_instance_status(chain)

    # Update DB if status changed
    if actual_status != chain.step_ca_status:
        chain.step_ca_status = actual_status
        await db.commit()

    return {
        "ca_chain_id": chain_id,
        "status": actual_status,
        "render_service_id": chain.render_service_id,
    }


# -------------------------------------------------------------------------
# Certificate Management
# -------------------------------------------------------------------------

@router.get("/certificates")
async def list_certificates(
    event_id: Optional[int] = None,
    ca_chain_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """List all issued TLS certificates with filters."""
    from sqlalchemy.orm import selectinload

    query = select(TLSCertificate).options(
        selectinload(TLSCertificate.user),
        selectinload(TLSCertificate.ca_chain),
    )

    if event_id:
        query = query.where(TLSCertificate.event_id == event_id)
    if ca_chain_id:
        query = query.where(TLSCertificate.ca_chain_id == ca_chain_id)
    if status:
        query = query.where(TLSCertificate.status == status)

    query = query.order_by(TLSCertificate.created_at.desc())

    result = await db.execute(query)
    certs = result.scalars().all()

    response = []
    for cert in certs:
        user = cert.user
        response.append({
            "id": cert.id,
            "user_id": cert.user_id,
            "user_email": user.email if user else "",
            "user_name": f"{user.first_name or ''} {user.last_name or ''}".strip() if user else "",
            "event_id": cert.event_id,
            "ca_chain_id": cert.ca_chain_id,
            "ca_chain_name": cert.ca_chain.name if cert.ca_chain else "",
            "common_name": cert.common_name,
            "sans": json.loads(cert.sans) if cert.sans else [],
            "is_wildcard": cert.is_wildcard,
            "serial_number": cert.serial_number,
            "status": cert.status,
            "issued_at": cert.issued_at,
            "expires_at": cert.expires_at,
            "revoked_at": cert.revoked_at,
            "revocation_reason": cert.revocation_reason,
            "created_at": cert.created_at,
        })

    return response


class RevokeCertRequest(BaseModel):
    reason: str = ""


@router.post("/certificates/{cert_id}/revoke")
async def revoke_certificate(
    cert_id: int,
    data: RevokeCertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Revoke a TLS certificate."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(TLSCertificate).options(
            selectinload(TLSCertificate.ca_chain)
        ).where(TLSCertificate.id == cert_id)
    )
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if cert.status != TLSCertificateStatus.ISSUED.value:
        raise HTTPException(status_code=400, detail=f"Certificate is already {cert.status}")

    # Try to revoke via step-ca if the service is running
    if cert.serial_number and cert.ca_chain and cert.ca_chain.step_ca_status == "running":
        stepca_service = StepCAService()
        await stepca_service.revoke_certificate(
            cert.ca_chain, cert.serial_number, data.reason
        )

    cert.status = TLSCertificateStatus.REVOKED.value
    cert.revoked_at = datetime.now(timezone.utc)
    cert.revocation_reason = data.reason
    await db.commit()

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="tls_cert_revoke",
        resource_type="tls_certificate",
        details={
            "message": f"Revoked TLS cert for '{cert.common_name}'",
            "cert_id": cert_id,
            "reason": data.reason,
        }
    )

    return {"success": True, "message": f"Certificate for '{cert.common_name}' revoked"}
