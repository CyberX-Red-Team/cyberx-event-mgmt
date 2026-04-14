"""REST API routes for Redirector and StreamConfig management.

Authentication uses the permission system:
  - redirectors.view      — list/read own redirectors (or all if view_all)
  - redirectors.manage    — create/edit/delete/deploy own redirectors
  - redirectors.view_all  — see ALL redirectors (admin)

Owner scoping: non-admin users only see redirectors where owner_id == user.id.
Admins (with redirectors.view_all) see all redirectors.

POST / PUT / DELETE operations require the X-CSRF-Token header (enforced
by the global CSRFMiddleware — no per-route action needed).

SSH private keys are NEVER returned in responses — always "**REDACTED**".
Decrypted keys exist only as local variables inside route handlers and are
passed directly to SSHService without logging or caching.

Error mapping from SSHService exceptions:
    SSHConnectionError  → 503 Service Unavailable
    SSHAuthError        → 422 Unprocessable Entity
    NginxTestError      → 200 OK with success=False (operator must see nginx output)
    NginxReloadError    → 500 Internal Server Error
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db, require_permission
from app.models.user import User
from app.models.redirector import Redirector, StreamConfig
from app.services.event_service import EventService
from app.schemas.redirector import (
    RedirectorCreate, RedirectorUpdate, RedirectorOut, RedirectorListOut,
    RedirectorFromInstance, ProvisionRedirectorRequest,
    AvailableInstanceOut, InstanceStatusOut, RedirectorTemplateOut,
    StreamConfigCreate, StreamConfigUpdate, StreamConfigOut,
    DeployResult, TestConnectionResult, ConfigPreview, CheckPortRequest,
)
from app.services.redirector_service import RedirectorService
from app.services.instance_service import InstanceService
from app.models.instance import Instance
from app.models.instance_template import InstanceTemplate
from app.models.cloud_init_template import CloudInitTemplate

# Cloud-init template name that identifies redirector templates by convention.
# Templates are considered redirector-eligible when is_redirector=True OR their
# linked cloud-init template name matches this constant.
REDIRECTOR_CLOUD_INIT_NAME = "Redirector Init"
from app.services.ssh_service import (
    SSHService,
    SSHConnectionError, SSHAuthError, NginxReloadError, SSHCommandError,
    run_test_connection, run_deploy_single, run_remove_single, run_deploy_all,
    run_check_port, run_check_nginx_setup, run_fix_nginx_setup,
    run_check_prereqs, run_fix_prereqs, run_deploy_infra_key,
)
from app.services.nginx_config_service import generate_stream_config_preview
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/redirectors", tags=["Redirectors"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_redirector_out(
    redirector: Redirector,
    stream_count: int | None = None,
    owner_username: str | None = None,
) -> RedirectorOut:
    """Build RedirectorOut from ORM object, always redacting key fields.

    stream_count and owner_username can be passed explicitly to avoid
    lazy-loading the corresponding relationships (which fails outside a
    greenlet context after session commits have expired the ORM object).
    """
    if stream_count is None:
        try:
            stream_count = redirector.stream_count
        except Exception:
            stream_count = 0
    if owner_username is None:
        try:
            owner = redirector.owner
            if owner is not None:
                owner_username = owner.pandas_username or owner.email
        except Exception:
            owner_username = None
    return RedirectorOut(
        id=redirector.id,
        name=redirector.name,
        current_ip=redirector.current_ip,
        ssh_port=redirector.ssh_port,
        ssh_username=redirector.ssh_username,
        use_infrastructure_key=redirector.use_infrastructure_key,
        ssh_private_key="**REDACTED**",
        ssh_key_passphrase="**REDACTED**" if redirector.ssh_key_passphrase else None,
        nginx_stream_dir=redirector.nginx_stream_dir,
        notes=redirector.notes,
        instance_id=redirector.instance_id,
        status=redirector.status,
        os_info=redirector.os_info,
        last_deployed_at=redirector.last_deployed_at,
        last_tested_at=redirector.last_tested_at,
        stream_count=stream_count,
        created_at=redirector.created_at,
        updated_at=redirector.updated_at,
        owner_id=redirector.owner_id,
        owner_username=owner_username,
        visibility=redirector.visibility or "private",
    )


async def _make_ssh_service(
    svc: RedirectorService,
    redirector: Redirector,
    db: AsyncSession,
) -> SSHService:
    """Decrypt SSH credentials and return an SSHService instance.

    Uses the active event's infrastructure key when use_infrastructure_key=True,
    otherwise decrypts the redirector's Fernet-encrypted BYOD key.
    """
    if redirector.use_infrastructure_key:
        event_svc = EventService(db)
        event = await event_svc.get_active_event()
        if not event or not event.ssh_private_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="This redirector uses the infrastructure key, but the active event "
                       "has no SSH key pair. Generate one in Event settings or switch "
                       "to a BYOD key.",
            )
        private_key_pem = event.ssh_private_key
        passphrase = None
    else:
        private_key_pem = svc.get_decrypted_key(redirector)
        passphrase = svc.get_decrypted_passphrase(redirector)

    return SSHService(
        hostname=redirector.current_ip,
        port=redirector.ssh_port,
        username=redirector.ssh_username,
        private_key_pem=private_key_pem,
        passphrase=passphrase,
    )


def _ssh_connection_error(exc: SSHConnectionError) -> HTTPException:
    logger.error("SSH connection error: %s", exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not connect to redirector. Check the IP, port, and that the host is reachable.",
    )


def _ssh_auth_error(exc: SSHAuthError) -> HTTPException:
    logger.error("SSH auth error: %s", exc)
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="SSH authentication failed. Check the private key and passphrase.",
    )


def _ssh_command_error(exc: Exception) -> HTTPException:
    logger.error("SSH command error: %s", exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An SSH command failed on the redirector. Check server logs for details.",
    )


async def _get_redirector_or_404(
    redirector_id: str, svc: RedirectorService
) -> Redirector:
    redir = await svc.get_redirector(redirector_id)
    if not redir:
        raise HTTPException(status_code=404, detail="Redirector not found.")
    return redir


async def _get_authorized_redirector(
    redirector_id: str,
    current_user: User,
    svc: RedirectorService,
    *,
    allow_public: bool = False,
) -> Redirector:
    """Fetch redirector and verify the user has access.

    Admins (redirectors.view_all) always pass. Owners always pass. When
    allow_public=True, any user who can view the list may read a public
    redirector (used by read-only routes like GET).
    """
    redir = await _get_redirector_or_404(redirector_id, svc)
    if current_user.has_permission("redirectors.view_all"):
        return redir
    if redir.owner_id == current_user.id:
        return redir
    if allow_public and redir.visibility == "public":
        return redir
    raise HTTPException(status_code=403, detail="Not authorized to access this redirector.")


async def _get_stream_or_404(
    stream_id: str, redirector_id: str, svc: RedirectorService
) -> StreamConfig:
    stream = await svc.get_stream(stream_id, redirector_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream config not found.")
    return stream


# ---------------------------------------------------------------------------
# Redirector CRUD
# ---------------------------------------------------------------------------

@router.get("/", response_model=RedirectorListOut)
async def list_redirectors(
    current_user: User = Depends(require_permission("redirectors.view")),
    db: AsyncSession = Depends(get_db),
):
    """List redirectors.

    Admins (redirectors.view_all) see all rows regardless of visibility.
    Other users see their own redirectors plus any redirector marked public.
    """
    svc = RedirectorService(db)
    if current_user.has_permission("redirectors.view_all"):
        redirectors = await svc.list_redirectors()
    else:
        redirectors = await svc.list_redirectors(
            owner_id=current_user.id, include_public=True
        )
    return RedirectorListOut(
        redirectors=[_build_redirector_out(r) for r in redirectors],
        total=len(redirectors),
    )


@router.post("/", response_model=RedirectorOut, status_code=status.HTTP_201_CREATED)
async def create_redirector(
    payload: RedirectorCreate,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Create a BYOD redirector.

    The provided SSH key is used once to bootstrap the event's infrastructure
    key onto the redirector. After a successful bootstrap the BYOD key is
    deleted and the redirector switches to infrastructure-key mode.
    """
    svc = RedirectorService(db)

    # Uniqueness check
    existing = await svc.get_redirector_by_name(payload.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A redirector named '{payload.name}' already exists.",
        )

    owner_id = current_user.id if current_user.id else None
    redirector = await svc.create_redirector({**payload.model_dump(), "owner_id": owner_id})

    # Auto-test connection to set initial status (online/offline).
    # Best-effort: redirector is already saved, so any failure here just
    # sets status to offline rather than crashing the create request.
    bootstrap_ok = False
    try:
        ssh = await _make_ssh_service(svc, redirector, db)
        result = await run_test_connection(ssh)
        new_status = "online" if result["success"] else "offline"
        await svc.update_status(redirector, new_status, os_info=result.get("os_info"))

        # Deploy infrastructure key using the one-time BYOD credentials
        if result["success"]:
            try:
                event_svc = EventService(db)
                event = await event_svc.get_active_event()
                if event and event.ssh_public_key:
                    deploy_result = await run_deploy_infra_key(ssh, event.ssh_public_key)
                    if deploy_result.get("deployed") or deploy_result.get("already_present"):
                        bootstrap_ok = True
                        await svc.clear_byod_key(redirector)
                        infra_audit = AuditService(db)
                        await infra_audit.log(
                            action="INFRA_KEY_DEPLOYED",
                            user_id=current_user.id,
                            resource_type="REDIRECTOR",
                            details={
                                "redirector_id": redirector.id,
                                "event_name": event.name,
                                "byod_key_cleared": True,
                            },
                            ip_address=request.client.host if request.client else None,
                        )
            except Exception as infra_err:
                logger.warning("Failed to deploy infrastructure key: %s", infra_err)
    except Exception as test_err:
        logger.warning("Auto-test connection failed for new redirector %s: %s", redirector.id, test_err)
        try:
            await svc.update_status(redirector, "offline")
        except Exception as inner:
            logger.warning("Failed to set offline status after test error: %s", inner)

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_CREATE",
        user_id=current_user.id,
        resource_type="REDIRECTOR",
        details={
            "redirector_id": redirector.id,
            "name": redirector.name,
            "type": "byod",
            "infra_key_bootstrapped": bootstrap_ok,
        },
        ip_address=request.client.host if request.client else None,
    )

    # Refresh scalar attributes expired by prior commits (update_status, audit).
    # Pass stream_count=0 to avoid lazy-loading the relationship.
    await db.refresh(redirector)
    return _build_redirector_out(redirector, stream_count=0)


def _is_redirector_template_filter():
    """SQLAlchemy filter: template is a redirector template.

    Matches when EITHER is_redirector=True OR the linked cloud-init template
    is named 'Redirector Init'.
    """
    return or_(
        InstanceTemplate.is_redirector.is_(True),
        InstanceTemplate.cloud_init_template.has(
            CloudInitTemplate.name == REDIRECTOR_CLOUD_INIT_NAME
        ),
    )


def _is_redirector_template(template: InstanceTemplate) -> bool:
    """Python-side check: is this template a redirector template?"""
    if template.is_redirector:
        return True
    if (
        template.cloud_init_template
        and template.cloud_init_template.name == REDIRECTOR_CLOUD_INIT_NAME
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# CyberX Redirector endpoints (static paths — must precede /{redirector_id})
# ---------------------------------------------------------------------------

@router.get("/available-instances", response_model=List[AvailableInstanceOut])
async def list_available_instances(
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """List ACTIVE cloud instances eligible to become CyberX redirectors.

    Returns instances from redirector templates that are not already linked
    to a managed redirector.
    """
    event_svc = EventService(db)
    event = await event_svc.get_active_event()
    if not event:
        return []

    # Subquery: instance IDs already linked to a redirector
    linked_ids = (
        select(Redirector.instance_id)
        .where(Redirector.instance_id.isnot(None))
        .scalar_subquery()
    )

    query = (
        select(Instance)
        .join(InstanceTemplate, Instance.instance_template_id == InstanceTemplate.id)
        .outerjoin(CloudInitTemplate, InstanceTemplate.cloud_init_template_id == CloudInitTemplate.id)
        .where(
            Instance.status == "ACTIVE",
            Instance.deleted_at.is_(None),
            Instance.event_id == event.id,
            _is_redirector_template_filter(),
            Instance.id.notin_(linked_ids),
        )
        .order_by(Instance.name)
    )

    # Owner scoping: non-admins see only their own instances
    if not current_user.has_permission("redirectors.view_all"):
        query = query.where(Instance.created_by_user_id == current_user.id)

    result = await db.execute(query)
    return [AvailableInstanceOut.model_validate(i) for i in result.scalars().all()]


@router.get("/redirector-templates", response_model=List[RedirectorTemplateOut])
async def list_redirector_templates(
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """List active instance templates marked as redirector templates."""
    event_svc = EventService(db)
    event = await event_svc.get_active_event()
    if not event:
        return []

    result = await db.execute(
        select(InstanceTemplate)
        .outerjoin(CloudInitTemplate, InstanceTemplate.cloud_init_template_id == CloudInitTemplate.id)
        .where(
            InstanceTemplate.event_id == event.id,
            _is_redirector_template_filter(),
            InstanceTemplate.is_active.is_(True),
        )
        .order_by(InstanceTemplate.name)
    )
    return [RedirectorTemplateOut.model_validate(t) for t in result.scalars().all()]


@router.post("/from-instance", response_model=RedirectorOut, status_code=status.HTTP_201_CREATED)
async def create_from_instance(
    payload: RedirectorFromInstance,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Auto-create a redirector from an existing CyberX cloud instance."""
    svc = RedirectorService(db)

    # Validate instance exists and is ACTIVE
    instance = await db.get(Instance, payload.instance_id)
    if not instance or instance.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if instance.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Instance is not active (status: {instance.status}).",
        )

    # Owner check
    if not current_user.has_permission("redirectors.view_all") and instance.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to use this instance.")

    # Validate template is a redirector template
    template = None
    if instance.instance_template_id:
        result = await db.execute(
            select(InstanceTemplate)
            .options(selectinload(InstanceTemplate.cloud_init_template))
            .where(InstanceTemplate.id == instance.instance_template_id)
        )
        template = result.scalar_one_or_none()
    if not template or not _is_redirector_template(template):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This instance was not created from a redirector template.",
        )

    # Uniqueness: no redirector already linked to this instance
    existing = await svc.get_redirector_by_instance_id(payload.instance_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A redirector is already linked to this instance ('{existing.name}').",
        )

    # Validate infra key exists
    event_svc = EventService(db)
    event = await event_svc.get_active_event()
    if not event or not event.ssh_private_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Active event has no SSH key pair. Generate one in Event settings.",
        )

    # Name uniqueness
    name = payload.name or instance.name
    existing_name = await svc.get_redirector_by_name(name)
    if existing_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A redirector named '{name}' already exists.",
        )

    # Auto-populate from instance + template
    redirector = await svc.create_redirector({
        "name": name,
        "current_ip": instance.ip_address,
        "ssh_port": 22,
        "ssh_username": template.ssh_username,
        "nginx_stream_dir": payload.nginx_stream_dir,
        "notes": payload.notes,
        "owner_id": current_user.id,
        "instance_id": instance.id,
        "visibility": payload.visibility,
    })

    # Best-effort connection test
    try:
        ssh = await _make_ssh_service(svc, redirector, db)
        result = await run_test_connection(ssh)
        new_status = "online" if result["success"] else "offline"
        await svc.update_status(redirector, new_status, os_info=result.get("os_info"))
    except Exception as test_err:
        logger.warning("Auto-test failed for CyberX redirector %s: %s", redirector.id, test_err)
        try:
            await svc.update_status(redirector, "offline")
        except Exception:
            pass

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_CREATE_FROM_INSTANCE",
        user_id=current_user.id,
        resource_type="REDIRECTOR",
        details={
            "redirector_id": redirector.id,
            "name": redirector.name,
            "instance_id": instance.id,
            "instance_name": instance.name,
        },
        ip_address=request.client.host if request.client else None,
    )

    await db.refresh(redirector)
    return _build_redirector_out(redirector, stream_count=0)


@router.post("/provision-and-register", status_code=status.HTTP_201_CREATED)
async def provision_redirector_instance(
    payload: ProvisionRedirectorRequest,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Provision a new cloud instance from a redirector template.

    Returns the instance ID and status. The frontend polls /instance-status/{id}
    until ACTIVE, then calls /from-instance to complete registration.
    """
    # Validate template
    result = await db.execute(
        select(InstanceTemplate)
        .options(selectinload(InstanceTemplate.cloud_init_template))
        .where(InstanceTemplate.id == payload.template_id)
    )
    template = result.scalar_one_or_none()
    if not template or not _is_redirector_template(template) or not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid or inactive redirector template.",
        )

    event_svc = EventService(db)
    event = await event_svc.get_active_event()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No active event.",
        )
    if not event.ssh_private_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Active event has no SSH key pair.",
        )

    # Provision via existing InstanceService
    instance_svc = InstanceService(db)
    instance = await instance_svc.create_from_template(
        template_id=payload.template_id,
        name=payload.name,
        assigned_to_user_id=current_user.id,
        created_by_user_id=current_user.id,
    )

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_INSTANCE_PROVISIONED",
        user_id=current_user.id,
        resource_type="INSTANCE",
        details={
            "instance_id": instance.id,
            "template_id": template.id,
            "template_name": template.name,
            "name": payload.name,
        },
        ip_address=request.client.host if request.client else None,
    )

    return InstanceStatusOut(
        id=instance.id,
        name=instance.name,
        ip_address=instance.ip_address,
        status=instance.status,
    )


@router.get("/instance-status/{instance_id}", response_model=InstanceStatusOut)
async def get_instance_status(
    instance_id: int,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Poll instance provisioning status. Used by frontend during CyberX flow."""
    instance = await db.get(Instance, instance_id)
    if not instance or instance.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if not current_user.has_permission("redirectors.view_all") and instance.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized.")

    # Trigger a status sync from the cloud provider
    try:
        instance_svc = InstanceService(db)
        await instance_svc.sync_instance_status(instance)
        await db.refresh(instance)
    except Exception as e:
        logger.warning("Failed to sync instance %s status: %s", instance_id, e)

    return InstanceStatusOut(
        id=instance.id,
        name=instance.name,
        ip_address=instance.ip_address,
        status=instance.status,
    )


@router.get("/{redirector_id}", response_model=RedirectorOut)
async def get_redirector(
    redirector_id: str,
    current_user: User = Depends(require_permission("redirectors.view")),
    db: AsyncSession = Depends(get_db),
):
    """Get a single redirector with its stream count.

    Non-owners may fetch a redirector when its visibility is 'public';
    mutating routes below still require owner or admin permissions.
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(
        redirector_id, current_user, svc, allow_public=True
    )
    return _build_redirector_out(redirector)


@router.put("/{redirector_id}", response_model=RedirectorOut)
async def update_redirector(
    redirector_id: str,
    payload: RedirectorUpdate,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a redirector. Omit ssh_private_key to keep the existing key.
    Send an empty string for ssh_key_passphrase to clear it.
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    redirector = await svc.update_redirector(
        redirector, payload.model_dump(exclude_unset=True)
    )

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_UPDATE",
        user_id=current_user.id,
        resource_type="REDIRECTOR",
        details={"redirector_id": redirector_id},
        ip_address=request.client.host if request.client else None,
    )

    return _build_redirector_out(redirector)


@router.delete("/{redirector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_redirector(
    redirector_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a redirector and all its stream configs (cascade). Does not remove remote files."""
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    name = redirector.name
    await svc.delete_redirector(redirector)

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_DELETE",
        user_id=current_user.id,
        resource_type="REDIRECTOR",
        details={"redirector_id": redirector_id, "name": name},
        ip_address=request.client.host if request.client else None,
    )


# ---------------------------------------------------------------------------
# SSH operations on redirectors
# ---------------------------------------------------------------------------

@router.post("/{redirector_id}/test-connection", response_model=TestConnectionResult)
async def test_connection(
    redirector_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    SSH connect to the redirector and verify nginx stream module presence.
    Updates the redirector status (online/offline) and last_tested_at.
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    ssh = await _make_ssh_service(svc, redirector, db)

    try:
        result = await run_test_connection(ssh)
    except SSHConnectionError as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError) as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_command_error(e)

    new_status = "online" if result["success"] else "offline"
    await svc.update_status(redirector, new_status, os_info=result.get("os_info"))

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_TEST",
        user_id=current_user.id,
        resource_type="REDIRECTOR",
        details={
            "redirector_id": redirector_id,
            "success": result["success"],
            "stream_module_present": result.get("stream_module_present"),
        },
        ip_address=request.client.host if request.client else None,
    )

    return TestConnectionResult(**result)


@router.post("/{redirector_id}/check-nginx-setup")
async def check_nginx_setup(
    redirector_id: str,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    SSH into the redirector and check for common nginx config issues:
    default site active (port 80) and stream block presence.
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    ssh = await _make_ssh_service(svc, redirector, db)
    try:
        return await run_check_nginx_setup(ssh)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (SSHCommandError, NginxReloadError) as e:
        raise _ssh_command_error(e)


@router.post("/{redirector_id}/fix-nginx-setup")
async def fix_nginx_setup(
    redirector_id: str,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    SSH into the redirector and fix common nginx config issues:
    remove sites-enabled/default, add stream block to nginx.conf, reload nginx.

    Requires additional sudoers entry on the redirector:
        <user> ALL=(ALL) NOPASSWD: /bin/bash /tmp/.cyberx_nginx_fix.sh
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    ssh = await _make_ssh_service(svc, redirector, db)
    try:
        return await run_fix_nginx_setup(ssh, redirector.nginx_stream_dir)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (SSHCommandError, NginxReloadError) as e:
        raise _ssh_command_error(e)
    except (FileNotFoundError, OSError) as e:
        return {
            "success": False,
            "message": f"Fix script failed: {e}. Ensure the SSH user has sudo permissions.",
        }


@router.post("/{redirector_id}/check-prereqs")
async def check_prereqs(
    redirector_id: str,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Check that all CyberX prerequisites are met on the redirector."""
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    ssh = await _make_ssh_service(svc, redirector, db)
    try:
        return await run_check_prereqs(ssh, redirector.nginx_stream_dir)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (SSHCommandError, NginxReloadError) as e:
        raise _ssh_command_error(e)


@router.post("/{redirector_id}/fix-prereqs")
async def fix_prereqs(
    redirector_id: str,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Attempt to automatically satisfy CyberX prerequisites on the redirector.
    Requires the SSH user to have sudo access (NOPASSWD preferred).
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    ssh = await _make_ssh_service(svc, redirector, db)
    try:
        return await run_fix_prereqs(ssh, redirector.nginx_stream_dir)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (SSHCommandError, NginxReloadError) as e:
        raise _ssh_command_error(e)


@router.post("/{redirector_id}/check-port")
async def check_port(
    redirector_id: str,
    body: CheckPortRequest,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    SSH into the redirector and check whether a port is already in use.
    Returns: {"in_use": bool, "listeners": [...], "message": str}
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    ssh = await _make_ssh_service(svc, redirector, db)

    try:
        result = await run_check_port(ssh, body.port, body.protocol)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (SSHCommandError, NginxReloadError) as e:
        raise _ssh_command_error(e)

    return result


@router.post("/{redirector_id}/deploy-all", response_model=DeployResult)
async def deploy_all(
    redirector_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Enable and deploy all stream configs for this redirector:
    mark all as enabled, write configs, remove orphans, reload nginx.
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    streams = await svc.list_streams(redirector_id)

    # Mark all streams as enabled before deploying
    for s in streams:
        await svc.update_stream(s, {"enabled": True})

    ssh = await _make_ssh_service(svc, redirector, db)

    try:
        result = await run_deploy_all(ssh, redirector.nginx_stream_dir, streams)
    except SSHConnectionError as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        await svc.update_status(redirector, "online")
        await svc.update_deployed_at(redirector)
        # Mark enabled streams as deployed, disabled as not deployed
        for s in streams:
            await svc.update_stream(s, {"deployed": s.enabled})

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_DEPLOY_ALL",
        user_id=current_user.id,
        resource_type="REDIRECTOR",
        details={
            "redirector_id": redirector_id,
            "success": result["success"],
            "files_written": result["files_written"],
            "files_deleted": result["files_deleted"],
        },
        ip_address=request.client.host if request.client else None,
    )

    return DeployResult(**result)


@router.post("/{redirector_id}/disable-all", response_model=DeployResult)
async def disable_all(
    redirector_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Disable all streams for this redirector:
    mark all as disabled, remove all config files, reload nginx.
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    streams = await svc.list_streams(redirector_id)

    # Mark all streams as disabled before deploying
    for s in streams:
        await svc.update_stream(s, {"enabled": False})

    ssh = await _make_ssh_service(svc, redirector, db)

    try:
        result = await run_deploy_all(ssh, redirector.nginx_stream_dir, streams)
    except SSHConnectionError as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        for s in streams:
            await svc.update_stream(s, {"deployed": False})

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_DISABLE_ALL",
        user_id=current_user.id,
        resource_type="REDIRECTOR",
        details={
            "redirector_id": redirector_id,
            "success": result["success"],
            "files_deleted": result["files_deleted"],
        },
        ip_address=request.client.host if request.client else None,
    )

    return DeployResult(**result)


# ---------------------------------------------------------------------------
# StreamConfig CRUD
# ---------------------------------------------------------------------------

@router.get("/{redirector_id}/streams", response_model=List[StreamConfigOut])
async def list_streams(
    redirector_id: str,
    current_user: User = Depends(require_permission("redirectors.view")),
    db: AsyncSession = Depends(get_db),
):
    """List all stream configs for a redirector."""
    svc = RedirectorService(db)
    await _get_authorized_redirector(redirector_id, current_user, svc)
    streams = await svc.list_streams(redirector_id)
    return [StreamConfigOut.model_validate(s) for s in streams]


@router.post(
    "/{redirector_id}/streams",
    response_model=StreamConfigOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_stream(
    redirector_id: str,
    payload: StreamConfigCreate,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Create a stream config for a redirector (does not deploy immediately)."""
    svc = RedirectorService(db)
    await _get_authorized_redirector(redirector_id, current_user, svc)
    stream = await svc.create_stream(redirector_id, payload.model_dump())

    audit = AuditService(db)
    await audit.log(
        action="STREAM_CREATE",
        user_id=current_user.id,
        resource_type="STREAM_CONFIG",
        details={
            "stream_id": stream.id,
            "redirector_id": redirector_id,
            "name": stream.name,
            "protocol": stream.protocol,
        },
        ip_address=request.client.host if request.client else None,
    )

    return StreamConfigOut.model_validate(stream)


@router.get("/{redirector_id}/streams/{stream_id}", response_model=StreamConfigOut)
async def get_stream(
    redirector_id: str,
    stream_id: str,
    current_user: User = Depends(require_permission("redirectors.view")),
    db: AsyncSession = Depends(get_db),
):
    """Get a single stream config."""
    svc = RedirectorService(db)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)
    return StreamConfigOut.model_validate(stream)


@router.put("/{redirector_id}/streams/{stream_id}", response_model=StreamConfigOut)
async def update_stream(
    redirector_id: str,
    stream_id: str,
    payload: StreamConfigUpdate,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Update a stream config (does not redeploy automatically)."""
    svc = RedirectorService(db)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)
    stream = await svc.update_stream(stream, payload.model_dump(exclude_unset=True))

    audit = AuditService(db)
    await audit.log(
        action="STREAM_UPDATE",
        user_id=current_user.id,
        resource_type="STREAM_CONFIG",
        details={"stream_id": stream_id, "redirector_id": redirector_id},
        ip_address=request.client.host if request.client else None,
    )

    return StreamConfigOut.model_validate(stream)


@router.delete(
    "/{redirector_id}/streams/{stream_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_stream(
    redirector_id: str,
    stream_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a stream config from the database and remove the config file from the redirector."""
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)
    name = stream.name

    # Remove the config file from the redirector (best-effort — delete from DB even if SSH fails)
    try:
        ssh = await _make_ssh_service(svc, redirector, db)
        await run_remove_single(ssh, redirector.nginx_stream_dir, stream_id, name)
    except Exception as e:
        logger.warning("Failed to remove stream file from redirector during delete: %s", e)

    await svc.delete_stream(stream)

    audit = AuditService(db)
    await audit.log(
        action="STREAM_DELETE",
        user_id=current_user.id,
        resource_type="STREAM_CONFIG",
        details={"stream_id": stream_id, "redirector_id": redirector_id, "name": name},
        ip_address=request.client.host if request.client else None,
    )


# ---------------------------------------------------------------------------
# SSH operations on individual streams
# ---------------------------------------------------------------------------

@router.get(
    "/{redirector_id}/streams/{stream_id}/preview",
    response_model=ConfigPreview,
)
async def preview_stream(
    redirector_id: str,
    stream_id: str,
    current_user: User = Depends(require_permission("redirectors.view")),
    db: AsyncSession = Depends(get_db),
):
    """Return the generated nginx config text without performing any SSH operation."""
    svc = RedirectorService(db)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)
    content = generate_stream_config_preview(stream)
    return ConfigPreview(filename=stream.filename, content=content)


@router.post("/{redirector_id}/streams/{stream_id}/enable", response_model=DeployResult)
async def enable_stream(
    redirector_id: str,
    stream_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a stream as enabled, write its config file to the redirector, and reload nginx.
    Rolls back (deletes the file) if nginx -t fails — stream stays enabled in DB on rollback
    so the operator can fix the config and retry.
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)

    stream = await svc.update_stream(stream, {"enabled": True})
    ssh = await _make_ssh_service(svc, redirector, db)

    try:
        result = await run_deploy_single(ssh, redirector.nginx_stream_dir, stream)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        await svc.update_deployed_at(redirector)
        await svc.update_stream(stream, {"deployed": True})

    audit = AuditService(db)
    await audit.log(
        action="STREAM_ENABLE",
        user_id=current_user.id,
        resource_type="STREAM_CONFIG",
        details={
            "stream_id": stream_id,
            "redirector_id": redirector_id,
            "success": result["success"],
        },
        ip_address=request.client.host if request.client else None,
    )

    return DeployResult(**result)


@router.post("/{redirector_id}/streams/{stream_id}/deploy", response_model=DeployResult)
async def deploy_stream(
    redirector_id: str,
    stream_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Write a single stream config file to the redirector and reload nginx.
    Rolls back (deletes the file) if nginx -t fails.
    Returns HTTP 200 with success=False if nginx test fails (operator sees output).
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)

    if not stream.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stream is disabled. Enable it before deploying.",
        )

    ssh = await _make_ssh_service(svc, redirector, db)

    try:
        result = await run_deploy_single(ssh, redirector.nginx_stream_dir, stream)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        await svc.update_deployed_at(redirector)
        await svc.update_stream(stream, {"deployed": True})

    audit = AuditService(db)
    await audit.log(
        action="STREAM_DEPLOY",
        user_id=current_user.id,
        resource_type="STREAM_CONFIG",
        details={
            "stream_id": stream_id,
            "redirector_id": redirector_id,
            "success": result["success"],
        },
        ip_address=request.client.host if request.client else None,
    )

    return DeployResult(**result)


@router.post("/{redirector_id}/streams/{stream_id}/remove", response_model=DeployResult)
async def remove_stream_file(
    redirector_id: str,
    stream_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.manage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a stream config file from the redirector and reload nginx.
    Does not delete the StreamConfig from the database — use DELETE for that.
    """
    svc = RedirectorService(db)
    redirector = await _get_authorized_redirector(redirector_id, current_user, svc)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)
    ssh = await _make_ssh_service(svc, redirector, db)

    try:
        result = await run_remove_single(
            ssh, redirector.nginx_stream_dir, stream_id, stream.name
        )
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        await svc.update_stream(stream, {"enabled": False, "deployed": False})

    audit = AuditService(db)
    await audit.log(
        action="STREAM_DISABLE",
        user_id=current_user.id,
        resource_type="STREAM_CONFIG",
        details={
            "stream_id": stream_id,
            "redirector_id": redirector_id,
            "success": result["success"],
        },
        ip_address=request.client.host if request.client else None,
    )

    return DeployResult(**result)
