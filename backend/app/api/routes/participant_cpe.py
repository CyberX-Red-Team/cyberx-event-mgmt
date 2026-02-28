"""Participant API routes for CPE certificate viewing and download."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_active_user
from app.models.user import User
from app.models.cpe_certificate import CertificateStatus
from app.services.cpe_certificate_service import CPECertificateService
from app.services.download_service import DownloadService
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cpe", tags=["CPE Certificates"])


@router.get("/my-certificates")
async def get_my_certificates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List current user's CPE certificates."""
    service = CPECertificateService(db)
    certificates = await service.get_user_certificates(current_user.id)

    return {
        "certificates": [
            {
                "id": cert.id,
                "certificate_number": cert.certificate_number,
                "cpe_hours": cert.cpe_hours,
                "status": cert.status,
                "pdf_available": cert.pdf_storage_key is not None,
                "created_at": cert.created_at.isoformat() if cert.created_at else None,
            }
            for cert in certificates
        ]
    }


@router.get("/my-certificates/{certificate_id}/download")
async def download_certificate(
    certificate_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Download a certificate PDF. Redirects to a signed R2 URL."""
    service = CPECertificateService(db)
    cert = await service.get_certificate_by_id(certificate_id)

    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if cert.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")

    if cert.status == CertificateStatus.REVOKED.value:
        raise HTTPException(status_code=410, detail="Certificate has been revoked")

    if not cert.pdf_storage_key:
        raise HTTPException(status_code=404, detail="Certificate PDF has not been generated yet")

    # Generate signed download URL
    download_service = DownloadService()
    try:
        signed_url = download_service.generate_link(cert.pdf_storage_key, expires_in=300)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Download service error: {e}")

    # Audit log
    audit = AuditService(db)
    await audit.log_certificate_download(
        user_id=current_user.id,
        certificate_id=cert.id,
        certificate_number=cert.certificate_number,
        ip_address=request.client.host if request.client else None,
    )

    return RedirectResponse(url=signed_url, status_code=302)
