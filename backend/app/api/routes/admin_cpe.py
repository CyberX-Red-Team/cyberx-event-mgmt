"""Admin API routes for CPE certificate management."""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, get_current_admin_user
from app.models.user import User
from app.models.event import Event
from app.models.cpe_certificate import CPECertificate
from app.services.cpe_certificate_service import CPECertificateService
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/cpe", tags=["Admin - CPE Certificates"])


# --- Request/Response Models ---

class IssueCertificateRequest(BaseModel):
    user_id: int
    event_id: int
    skip_eligibility: bool = False


class BulkIssueRequest(BaseModel):
    event_id: int
    user_ids: List[int]
    skip_eligibility: bool = False


class BulkRegenerateRequest(BaseModel):
    event_id: int
    certificate_ids: Optional[List[int]] = None


class RevokeCertificateRequest(BaseModel):
    reason: str


# --- Endpoints ---

@router.get("/eligibility/{event_id}")
async def check_bulk_eligibility(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Check CPE eligibility for all confirmed participants of an event."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if not event.start_date or not event.end_date:
        raise HTTPException(
            status_code=400,
            detail="Event must have start_date and end_date set for eligibility checking"
        )

    service = CPECertificateService(db)
    results = await service.bulk_check_eligibility(event)

    eligible_count = sum(1 for r in results if r["eligible"])

    return {
        "event_id": event_id,
        "event_name": event.name,
        "total_participants": len(results),
        "eligible_count": eligible_count,
        "ineligible_count": len(results) - eligible_count,
        "participants": results,
    }


@router.get("/eligibility/{event_id}/{user_id}")
async def check_user_eligibility(
    event_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Check CPE eligibility for a single participant."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if not event.start_date or not event.end_date:
        raise HTTPException(
            status_code=400,
            detail="Event must have start_date and end_date set"
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    service = CPECertificateService(db)
    result = await service.check_eligibility(user_id, event)
    result["email"] = user.email
    result["first_name"] = user.first_name
    result["last_name"] = user.last_name

    return result


@router.post("/issue")
async def issue_certificate(
    request_body: IssueCertificateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Issue a CPE certificate to a single user.

    Automatically manages the Gotenberg service on Render for PDF generation.
    """
    from app.services.render_service import RenderServiceManager

    render = RenderServiceManager()
    service = CPECertificateService(db)
    audit = AuditService(db)

    try:
        if render.enabled:
            ready = await render.start_gotenberg()
            if not ready:
                logger.warning("Gotenberg not ready - certificate will be created without PDF")

        cert = await service.issue_certificate(
            user_id=request_body.user_id,
            event_id=request_body.event_id,
            issued_by_user_id=current_user.id,
            skip_eligibility=request_body.skip_eligibility,
        )
        await db.commit()

        await audit.log_certificate_issue(
            user_id=current_user.id,
            target_user_id=request_body.user_id,
            certificate_id=cert.id,
            event_id=request_body.event_id,
            certificate_number=cert.certificate_number,
            ip_address=request.client.host if request.client else None,
        )

        return {
            "status": "ok",
            "certificate_id": cert.id,
            "certificate_number": cert.certificate_number,
            "pdf_generated": cert.pdf_storage_key is not None,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    finally:
        if render.enabled:
            await render.stop_gotenberg()


@router.post("/issue/bulk")
async def bulk_issue_certificates(
    request_body: BulkIssueRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Issue CPE certificates in bulk for multiple users.

    Automatically manages the Gotenberg service on Render for PDF generation.
    """
    from app.services.render_service import RenderServiceManager

    render = RenderServiceManager()
    service = CPECertificateService(db)
    audit = AuditService(db)

    try:
        if render.enabled:
            ready = await render.start_gotenberg()
            if not ready:
                logger.warning("Gotenberg not ready - certificates will be created without PDFs")

        result = await service.bulk_issue(
            event_id=request_body.event_id,
            user_ids=request_body.user_ids,
            issued_by_user_id=current_user.id,
            skip_eligibility=request_body.skip_eligibility,
        )

        if result["issued"]:
            await audit.log_bulk_certificate_issue(
                user_id=current_user.id,
                event_id=request_body.event_id,
                count=len(result["issued"]),
                ip_address=request.client.host if request.client else None,
            )

        return {
            "status": "ok",
            "issued_count": len(result["issued"]),
            "skipped_ineligible_count": len(result["skipped_ineligible"]),
            "skipped_existing_count": len(result["skipped_existing"]),
            "failed_count": len(result["failed"]),
            **result,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    finally:
        if render.enabled:
            await render.stop_gotenberg()


@router.get("/certificates/{event_id}")
async def list_certificates(
    event_id: int,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """List all certificates for an event."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    service = CPECertificateService(db)
    certificates = await service.get_certificates_for_event(event_id, status=status_filter)

    # Enrich with user info
    items = []
    for cert in certificates:
        user = await db.get(User, cert.user_id)
        items.append({
            "id": cert.id,
            "certificate_number": cert.certificate_number,
            "user_id": cert.user_id,
            "email": user.email if user else None,
            "first_name": user.first_name if user else None,
            "last_name": user.last_name if user else None,
            "cpe_hours": cert.cpe_hours,
            "status": cert.status,
            "has_nextcloud_login": cert.has_nextcloud_login,
            "has_powerdns_login": cert.has_powerdns_login,
            "has_vpn_assigned": cert.has_vpn_assigned,
            "pdf_generated": cert.pdf_storage_key is not None,
            "created_at": cert.created_at.isoformat() if cert.created_at else None,
            "revoked_at": cert.revoked_at.isoformat() if cert.revoked_at else None,
            "revocation_reason": cert.revocation_reason,
        })

    return {
        "event_id": event_id,
        "event_name": event.name,
        "total": len(items),
        "certificates": items,
    }


@router.post("/certificates/{certificate_id}/revoke")
async def revoke_certificate(
    certificate_id: int,
    request_body: RevokeCertificateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Revoke an issued certificate."""
    service = CPECertificateService(db)
    audit = AuditService(db)

    try:
        cert = await service.revoke_certificate(
            certificate_id=certificate_id,
            revoked_by_user_id=current_user.id,
            reason=request_body.reason,
        )
        await db.commit()

        await audit.log_certificate_revoke(
            user_id=current_user.id,
            certificate_id=cert.id,
            certificate_number=cert.certificate_number,
            reason=request_body.reason,
            ip_address=request.client.host if request.client else None,
        )

        return {
            "status": "ok",
            "certificate_number": cert.certificate_number,
            "revoked_at": cert.revoked_at.isoformat() if cert.revoked_at else None,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/certificates/{certificate_id}/reinstate")
async def reinstate_certificate(
    certificate_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Reinstate a revoked certificate (undo revocation)."""
    service = CPECertificateService(db)
    audit = AuditService(db)

    cert = await service.get_certificate_by_id(certificate_id)
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if cert.status != "revoked":
        raise HTTPException(status_code=400, detail="Certificate is not revoked")

    cert.status = "issued"
    cert.revoked_at = None
    cert.revoked_by_user_id = None
    cert.revocation_reason = None
    await db.commit()

    await audit.log(
        action="CERTIFICATE_REINSTATE",
        user_id=current_user.id,
        resource_type="CERTIFICATE",
        resource_id=cert.id,
        details={
            "certificate_number": cert.certificate_number,
        },
        ip_address=request.client.host if request.client else None,
    )

    return {
        "status": "ok",
        "certificate_number": cert.certificate_number,
    }


@router.post("/certificates/{certificate_id}/regenerate")
async def regenerate_certificate_pdf(
    certificate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Regenerate the PDF for an existing certificate.

    Automatically manages the Gotenberg service on Render:
    starts before conversion, suspends after.
    """
    from app.services.render_service import RenderServiceManager

    render = RenderServiceManager()
    service = CPECertificateService(db)

    try:
        if render.enabled:
            ready = await render.start_gotenberg()
            if not ready:
                raise HTTPException(
                    status_code=503,
                    detail="Gotenberg service did not become ready in time"
                )

        cert = await service.regenerate_pdf(certificate_id)
        await db.commit()

        return {
            "status": "ok",
            "certificate_number": cert.certificate_number,
            "pdf_generated_at": cert.pdf_generated_at.isoformat() if cert.pdf_generated_at else None,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    finally:
        if render.enabled:
            await render.stop_gotenberg()


@router.post("/certificates/regenerate/bulk")
async def bulk_regenerate_pdfs(
    request_body: BulkRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Bulk regenerate PDFs for certificates.

    Automatically manages the Gotenberg service on Render:
    scales to Standard, resumes, waits for ready, then suspends after.

    If certificate_ids is omitted, regenerates all ISSUED certs missing PDFs for the event.
    """
    from app.services.render_service import RenderServiceManager

    render = RenderServiceManager()
    service = CPECertificateService(db)

    try:
        # Start Gotenberg (scale + resume + wait)
        if render.enabled:
            ready = await render.start_gotenberg()
            if not ready:
                raise HTTPException(
                    status_code=503,
                    detail="Gotenberg service did not become ready in time"
                )

        result = await service.bulk_regenerate_pdfs(
            event_id=request_body.event_id,
            certificate_ids=request_body.certificate_ids,
        )
        await db.commit()

        return {
            "status": "ok",
            "regenerated_count": len(result["regenerated"]),
            "failed_count": len(result["failed"]),
            "skipped_revoked_count": len(result["skipped_revoked"]),
            **result,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    finally:
        # Always suspend Gotenberg after bulk operation
        if render.enabled:
            await render.stop_gotenberg()
