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
    signing_cert: UploadFile = File(...),
    signing_key: UploadFile = File(...),
    ca_chain_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Create a new CA chain with uploaded PEM files.

    Accepts 3 files:
    - signing_cert: The CA certificate that will sign end-entity certs
    - signing_key: Its private key
    - ca_chain_file: PEM chain of all certs above the signing cert up to root

    Validates PEM format, chain integrity, encrypts private key,
    and stores all files in R2.
    """
    stepca_service = StepCAService()

    # Read uploaded files
    signing_cert_bytes = await signing_cert.read()
    signing_key_bytes = await signing_key.read()
    ca_chain_bytes = await ca_chain_file.read()

    # Validate PEM format
    try:
        stepca_service.validate_pem_certificate(signing_cert_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid signing certificate: {e}")

    try:
        stepca_service.validate_pem_private_key(signing_key_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid signing private key: {e}")

    # Validate chain file contains at least one cert
    try:
        chain_certs = stepca_service.parse_pem_chain(ca_chain_bytes)
        if not chain_certs:
            raise ValueError("CA chain file must contain at least one certificate")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid CA chain file: {e}")

    # Validate that signing cert is signed by the first cert in the chain
    try:
        stepca_service.validate_signing_chain(signing_cert_bytes, ca_chain_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Chain validation failed: {e}")

    # Normalize chain: strip signing cert if it was included in the chain file
    ca_chain_bytes = stepca_service.strip_signing_cert_from_chain(
        signing_cert_bytes, ca_chain_bytes
    )

    # Create DB record first to get the ID
    ca_chain_record = CAChain(
        name=name,
        description=description,
        event_id=event_id,
        default_duration=default_duration,
        allow_wildcard=allow_wildcard,
        step_ca_status=CAChainStatus.STOPPED.value,
        created_by_user_id=current_user.id,
    )
    db.add(ca_chain_record)
    await db.flush()  # Get the ID

    # Upload files to R2
    prefix = stepca_service.get_ca_files_r2_prefix(ca_chain_record.id)

    r2_keys = {
        "signing_cert": f"{prefix}/signing_ca.crt",
        "signing_key": f"{prefix}/signing_ca.key",
        "ca_chain": f"{prefix}/ca-chain.pem",
    }

    # Encrypt private key before upload
    encrypted_signing_key = encrypt_field(signing_key_bytes.decode("utf-8"))

    stepca_service.upload_to_r2(r2_keys["signing_cert"], signing_cert_bytes)
    stepca_service.upload_to_r2(r2_keys["signing_key"], encrypted_signing_key.encode("utf-8"))
    stepca_service.upload_to_r2(r2_keys["ca_chain"], ca_chain_bytes)

    # Store R2 keys in DB
    ca_chain_record.signing_cert_r2_key = r2_keys["signing_cert"]
    ca_chain_record.signing_key_r2_key = r2_keys["signing_key"]
    ca_chain_record.ca_chain_r2_key = r2_keys["ca_chain"]

    await db.commit()
    await db.refresh(ca_chain_record)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="ca_chain_create",
        resource_type="ca_chain",
        details={"message": f"Created CA chain '{name}'", "ca_chain_id": ca_chain_record.id}
    )

    return {
        "success": True,
        "ca_chain_id": ca_chain_record.id,
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
    for key in [chain.signing_cert_r2_key, chain.signing_key_r2_key,
                chain.ca_chain_r2_key]:
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
    signing_cert_bytes = stepca_service.download_from_r2(chain.signing_cert_r2_key)
    signing_key_encrypted = stepca_service.download_from_r2(chain.signing_key_r2_key)
    ca_chain_bytes = stepca_service.download_from_r2(chain.ca_chain_r2_key)

    if not all([signing_cert_bytes, signing_key_encrypted, ca_chain_bytes]):
        raise HTTPException(status_code=500, detail="Failed to download CA files from R2")

    # Decrypt private key
    signing_key_bytes = decrypt_field(signing_key_encrypted.decode("utf-8")).encode("utf-8")

    success = await stepca_service.initialize_ca_chain(
        ca_chain=chain,
        signing_cert_bytes=signing_cert_bytes,
        signing_key_bytes=signing_key_bytes,
        ca_chain_bytes=ca_chain_bytes,
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


class AdminCertificateRequest(BaseModel):
    ca_chain_id: int
    common_name: str
    sans: list[str] = []
    is_wildcard: bool = False
    event_id: Optional[int] = None  # defaults to active event


@router.post("/certificates")
async def admin_request_certificate(
    data: AdminCertificateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Admin-only certificate request. Bypasses PowerDNS validation with a warning.

    Unlike the participant endpoint, this does not require the domain to have
    a matching zone in PowerDNS. It still attempts validation and includes
    a warning in the response if validation fails.
    """
    from app.models.event import Event
    from app.services.powerdns_service import PowerDNSService
    from datetime import timedelta

    # Resolve event
    if data.event_id:
        event_result = await db.execute(
            select(Event).where(Event.id == data.event_id)
        )
        event = event_result.scalar_one_or_none()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
    else:
        event_result = await db.execute(
            select(Event).where(Event.is_active == True)
        )
        event = event_result.scalar_one_or_none()
        if not event:
            raise HTTPException(status_code=400, detail="No active event and no event_id specified")

    # Validate CA chain
    chain_result = await db.execute(
        select(CAChain).where(CAChain.id == data.ca_chain_id)
    )
    ca_chain = chain_result.scalar_one_or_none()
    if not ca_chain:
        raise HTTPException(status_code=404, detail="CA chain not found")
    if ca_chain.step_ca_status != CAChainStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="CA chain is not running")
    if data.is_wildcard and not ca_chain.allow_wildcard:
        raise HTTPException(status_code=400, detail="This CA chain does not allow wildcard certificates")

    # Prepare domain list
    common_name = data.common_name.strip().lower()
    if data.is_wildcard and not common_name.startswith("*."):
        common_name = f"*.{common_name}"

    all_domains = [common_name] + [s.strip().lower() for s in data.sans if s.strip()]

    # Attempt PowerDNS validation but don't block on failure
    dns_warnings = []
    try:
        pdns = PowerDNSService()
        for domain in all_domains:
            is_valid, error_msg = await pdns.validate_domain_for_cert(domain)
            if not is_valid:
                dns_warnings.append(f"{domain}: {error_msg}")
    except Exception as e:
        dns_warnings.append(f"PowerDNS unavailable: {e}")

    # Generate CSR and sign via step-ca
    stepca_service = StepCAService()
    csr_pem, key_pem = stepca_service.generate_csr(common_name, data.sans)

    duration = ca_chain.default_duration or "2160h"
    sign_result = await stepca_service.sign_certificate(ca_chain, csr_pem, duration)

    if not sign_result:
        raise HTTPException(status_code=500, detail="Failed to sign certificate via step-ca")

    cert_pem = sign_result.get("crt", "")
    ca_pem = sign_result.get("ca", "")
    serial_number = sign_result.get("serial_number", "")

    if not cert_pem:
        raise HTTPException(status_code=500, detail="step-ca returned empty certificate")

    # Build cert bundle
    cert_bundle = cert_pem
    if ca_pem:
        cert_bundle = cert_pem + "\n" + ca_pem

    # Calculate expiry
    hours = int(duration.replace("h", ""))
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=hours)

    # Get fingerprint
    from cryptography import x509 as cx509
    try:
        parsed_cert = cx509.load_pem_x509_certificate(cert_pem.encode())
        fingerprint = parsed_cert.fingerprint(parsed_cert.signature_hash_algorithm).hex()
        serial_number = serial_number or format(parsed_cert.serial_number, 'x')
    except Exception:
        fingerprint = ""

    # Upload to R2
    cn_safe = common_name.replace("*.", "wildcard.").replace("/", "_")
    r2_prefix = f"tls/certificates/{event.id}/{current_user.id}"
    cert_bundle_key = f"{r2_prefix}/{cn_safe}.crt"
    private_key_key = f"{r2_prefix}/{cn_safe}.key"

    encrypted_key = encrypt_field(key_pem)
    stepca_service.upload_to_r2(cert_bundle_key, cert_bundle.encode())
    stepca_service.upload_to_r2(private_key_key, encrypted_key.encode())

    # Build CA chain file
    if ca_chain.ca_chain_r2_key:
        chain_pem_bytes = stepca_service.download_from_r2(ca_chain.ca_chain_r2_key)
        if chain_pem_bytes:
            if ca_pem:
                full_chain = ca_pem + "\n" + chain_pem_bytes.decode()
            else:
                signing_cert_bytes = stepca_service.download_from_r2(ca_chain.signing_cert_r2_key)
                full_chain = (signing_cert_bytes.decode() if signing_cert_bytes else "") + "\n" + chain_pem_bytes.decode()
            ca_chain_key = f"{r2_prefix}/{cn_safe}.ca-chain.crt"
            stepca_service.upload_to_r2(ca_chain_key, full_chain.encode())

    # Create DB record
    tls_cert = TLSCertificate(
        user_id=current_user.id,
        event_id=event.id,
        ca_chain_id=ca_chain.id,
        common_name=common_name,
        sans=json.dumps(data.sans) if data.sans else None,
        is_wildcard=data.is_wildcard,
        serial_number=serial_number,
        fingerprint=fingerprint,
        cert_bundle_r2_key=cert_bundle_key,
        private_key_r2_key=private_key_key,
        status=TLSCertificateStatus.ISSUED.value,
        issued_at=now,
        expires_at=expires_at,
    )
    db.add(tls_cert)
    await db.commit()
    await db.refresh(tls_cert)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="admin_tls_cert_request",
        resource_type="tls_certificate",
        details={
            "message": f"Admin issued TLS cert for '{common_name}'",
            "cert_id": tls_cert.id,
            "dns_validated": len(dns_warnings) == 0,
            "dns_warnings": dns_warnings,
        }
    )

    response = {
        "success": True,
        "certificate_id": tls_cert.id,
        "common_name": common_name,
        "expires_at": expires_at.isoformat(),
        "message": f"Certificate issued for '{common_name}'",
    }
    if dns_warnings:
        response["dns_warnings"] = dns_warnings
        response["message"] += f" (WARNING: {len(dns_warnings)} domain(s) not validated in PowerDNS)"

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
