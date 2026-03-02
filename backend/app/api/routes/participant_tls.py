"""Participant routes for self-service TLS certificate issuance."""
import io
import json
import logging
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

from app.database import get_db
from app.models.user import User
from app.models.event import Event
from app.models.tls_certificate import CAChain, CAChainStatus, TLSCertificate, TLSCertificateStatus
from app.dependencies import get_current_active_user
from app.services.stepca_service import StepCAService
from app.services.powerdns_service import PowerDNSService
from app.utils.encryption import encrypt_field, decrypt_field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tls", tags=["participant-tls"])


# -------------------------------------------------------------------------
# Schemas
# -------------------------------------------------------------------------

class CertificateRequest(BaseModel):
    ca_chain_id: int
    common_name: str = Field(..., min_length=1, max_length=255)
    sans: list[str] = Field(default_factory=list)
    is_wildcard: bool = False


class CertificateResponse(BaseModel):
    id: int
    ca_chain_id: int
    ca_chain_name: str
    common_name: str
    sans: list[str]
    is_wildcard: bool
    status: str
    issued_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# -------------------------------------------------------------------------
# CA Chain listing
# -------------------------------------------------------------------------

@router.get("/ca-chains")
async def list_available_ca_chains(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List available CA chains for the active event (only running ones)."""
    # Get active event
    event_result = await db.execute(
        select(Event).where(Event.is_active == True)
    )
    event = event_result.scalar_one_or_none()
    if not event:
        return []

    result = await db.execute(
        select(CAChain).where(
            CAChain.event_id == event.id,
            CAChain.step_ca_status == CAChainStatus.RUNNING.value,
        ).order_by(CAChain.name)
    )
    chains = result.scalars().all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "allow_wildcard": c.allow_wildcard,
            "default_duration": c.default_duration,
        }
        for c in chains
    ]


# -------------------------------------------------------------------------
# Certificate request
# -------------------------------------------------------------------------

@router.post("/certificates")
async def request_certificate(
    data: CertificateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Request a TLS certificate for a domain.

    Validates:
    1. CA chain exists and is running
    2. All domains (CN + SANs) have matching zones in PowerDNS
    3. Wildcard allowed by CA chain config

    Then generates CSR, signs via step-ca, and stores cert + key in R2.
    """
    # Get active event
    event_result = await db.execute(
        select(Event).where(Event.is_active == True)
    )
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=400, detail="No active event")

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

    # Validate all domains against PowerDNS
    pdns = PowerDNSService()
    for domain in all_domains:
        is_valid, error_msg = await pdns.validate_domain_for_cert(domain)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Domain validation failed for '{domain}': {error_msg}")

    # Generate CSR and private key
    stepca_service = StepCAService()
    csr_pem, key_pem = stepca_service.generate_csr(common_name, data.sans)

    # Sign via step-ca
    duration = ca_chain.default_duration or "2160h"
    sign_result = await stepca_service.sign_certificate(ca_chain, csr_pem, duration)

    if not sign_result:
        raise HTTPException(status_code=500, detail="Failed to sign certificate via step-ca")

    cert_pem = sign_result.get("crt", "")
    ca_pem = sign_result.get("ca", "")
    serial_number = sign_result.get("serial_number", "")

    if not cert_pem:
        raise HTTPException(status_code=500, detail="step-ca returned empty certificate")

    # Build cert bundle (leaf + intermediate)
    cert_bundle = cert_pem
    if ca_pem:
        cert_bundle = cert_pem + "\n" + ca_pem

    # Calculate expiry from duration
    hours = int(duration.replace("h", ""))
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=hours)

    # Get fingerprint from cert
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

    # Encrypt private key before storing
    encrypted_key = encrypt_field(key_pem)

    stepca_service.upload_to_r2(cert_bundle_key, cert_bundle.encode())
    stepca_service.upload_to_r2(private_key_key, encrypted_key.encode())

    # Build and upload the full CA chain for the download bundle:
    # signing cert + chain above it (intermediates + root)
    if ca_chain.ca_chain_r2_key:
        chain_pem_bytes = stepca_service.download_from_r2(ca_chain.ca_chain_r2_key)
        if chain_pem_bytes:
            # Full chain: signing cert (returned by step-ca as ca_pem) + uploaded chain
            if ca_pem:
                full_chain = ca_pem + "\n" + chain_pem_bytes.decode()
            else:
                # If step-ca didn't return ca, use signing cert from R2
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

    return {
        "success": True,
        "certificate_id": tls_cert.id,
        "common_name": common_name,
        "expires_at": expires_at.isoformat(),
        "message": f"Certificate issued for '{common_name}'",
    }


# -------------------------------------------------------------------------
# Certificate listing
# -------------------------------------------------------------------------

@router.get("/certificates")
async def list_my_certificates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List certificates issued to the current user."""
    result = await db.execute(
        select(TLSCertificate).options(
            selectinload(TLSCertificate.ca_chain)
        ).where(
            TLSCertificate.user_id == current_user.id
        ).order_by(TLSCertificate.created_at.desc())
    )
    certs = result.scalars().all()

    return [
        {
            "id": c.id,
            "ca_chain_id": c.ca_chain_id,
            "ca_chain_name": c.ca_chain.name if c.ca_chain else "",
            "common_name": c.common_name,
            "sans": json.loads(c.sans) if c.sans else [],
            "is_wildcard": c.is_wildcard,
            "status": c.status,
            "issued_at": c.issued_at,
            "expires_at": c.expires_at,
            "created_at": c.created_at,
        }
        for c in certs
    ]


# -------------------------------------------------------------------------
# Certificate download
# -------------------------------------------------------------------------

@router.get("/certificates/{cert_id}/download")
async def download_certificate(
    cert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Download certificate bundle as a zip file.

    Contains:
    - {cn}.crt: PEM leaf cert + intermediate CA (for ssl_certificate)
    - {cn}.key: PEM private key (for ssl_certificate_key)
    - ca-chain.crt: PEM intermediate + root CA (for trust store)
    """
    result = await db.execute(
        select(TLSCertificate).options(
            selectinload(TLSCertificate.ca_chain)
        ).where(
            TLSCertificate.id == cert_id,
            TLSCertificate.user_id == current_user.id,
        )
    )
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if cert.status != TLSCertificateStatus.ISSUED.value:
        raise HTTPException(status_code=400, detail=f"Certificate is {cert.status} and cannot be downloaded")

    stepca_service = StepCAService()

    # Download cert bundle from R2
    cert_bundle_bytes = stepca_service.download_from_r2(cert.cert_bundle_r2_key)
    if not cert_bundle_bytes:
        raise HTTPException(status_code=500, detail="Failed to download certificate from storage")

    # Download and decrypt private key
    encrypted_key_bytes = stepca_service.download_from_r2(cert.private_key_r2_key)
    if not encrypted_key_bytes:
        raise HTTPException(status_code=500, detail="Failed to download private key from storage")

    key_pem = decrypt_field(encrypted_key_bytes.decode()).encode()

    # Build CA chain file (intermediate + root)
    ca_chain_bytes = None
    cn_safe = cert.common_name.replace("*.", "wildcard.").replace("/", "_")
    ca_chain_key = cert.cert_bundle_r2_key.replace(f"{cn_safe}.crt", f"{cn_safe}.ca-chain.crt")
    ca_chain_bytes = stepca_service.download_from_r2(ca_chain_key)

    # Create zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{cn_safe}.crt", cert_bundle_bytes)
        zf.writestr(f"{cn_safe}.key", key_pem)
        if ca_chain_bytes:
            zf.writestr("ca-chain.crt", ca_chain_bytes)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{cn_safe}-tls-bundle.zip"'
        },
    )
