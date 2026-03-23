"""REST API routes for Redirector and StreamConfig management.

All endpoints require admin authentication via get_current_admin_user.
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_admin_user, get_db
from app.models.user import User
from app.models.redirector import Redirector, StreamConfig
from app.schemas.redirector import (
    RedirectorCreate, RedirectorUpdate, RedirectorOut, RedirectorListOut,
    StreamConfigCreate, StreamConfigUpdate, StreamConfigOut,
    DeployResult, TestConnectionResult, ConfigPreview,
)
from app.services.redirector_service import RedirectorService
from app.services.ssh_service import (
    SSHService,
    SSHConnectionError, SSHAuthError, NginxReloadError, SSHCommandError,
    run_test_connection, run_deploy_single, run_remove_single, run_deploy_all,
    run_check_port, run_check_nginx_setup, run_fix_nginx_setup,
    run_check_prereqs, run_fix_prereqs,
)
from app.services.nginx_config_service import generate_stream_config_preview
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/redirectors", tags=["Redirectors"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_redirector_out(redirector: Redirector) -> RedirectorOut:
    """Build RedirectorOut from ORM object, always redacting key fields."""
    return RedirectorOut(
        id=redirector.id,
        name=redirector.name,
        current_ip=redirector.current_ip,
        ssh_port=redirector.ssh_port,
        ssh_username=redirector.ssh_username,
        ssh_private_key="**REDACTED**",
        ssh_key_passphrase="**REDACTED**" if redirector.ssh_key_passphrase else None,
        nginx_stream_dir=redirector.nginx_stream_dir,
        notes=redirector.notes,
        status=redirector.status,
        last_deployed_at=redirector.last_deployed_at,
        last_tested_at=redirector.last_tested_at,
        stream_count=redirector.stream_count,
        created_at=redirector.created_at,
        updated_at=redirector.updated_at,
    )


def _make_ssh_service(svc: RedirectorService, redirector: Redirector) -> SSHService:
    """Decrypt SSH credentials and return an SSHService instance."""
    return SSHService(
        hostname=redirector.current_ip,
        port=redirector.ssh_port,
        username=redirector.ssh_username,
        private_key_pem=svc.get_decrypted_key(redirector),
        passphrase=svc.get_decrypted_passphrase(redirector),
    )


def _ssh_connection_error(exc: SSHConnectionError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Could not connect to redirector: {exc}",
    )


def _ssh_auth_error(exc: SSHAuthError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"SSH authentication failed: {exc}",
    )


def _ssh_command_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"SSH command error: {exc}",
    )


async def _get_redirector_or_404(
    redirector_id: str, svc: RedirectorService
) -> Redirector:
    redir = await svc.get_redirector(redirector_id)
    if not redir:
        raise HTTPException(status_code=404, detail="Redirector not found.")
    return redir


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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all redirectors."""
    svc = RedirectorService(db)
    redirectors = await svc.list_redirectors()
    return RedirectorListOut(
        redirectors=[_build_redirector_out(r) for r in redirectors],
        total=len(redirectors),
    )


@router.post("/", response_model=RedirectorOut, status_code=status.HTTP_201_CREATED)
async def create_redirector(
    payload: RedirectorCreate,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new redirector. SSH private key is encrypted before storage."""
    svc = RedirectorService(db)

    # Uniqueness check
    existing = await svc.get_redirector_by_name(payload.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A redirector named '{payload.name}' already exists.",
        )

    redirector = await svc.create_redirector(payload.model_dump())

    audit = AuditService(db)
    await audit.log(
        action="REDIRECTOR_CREATE",
        user_id=current_user.id,
        resource_type="REDIRECTOR",
        details={"redirector_id": redirector.id, "name": redirector.name},
        ip_address=request.client.host if request.client else None,
    )

    return _build_redirector_out(redirector)


@router.get("/{redirector_id}", response_model=RedirectorOut)
async def get_redirector(
    redirector_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single redirector with its stream count."""
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    return _build_redirector_out(redirector)


@router.put("/{redirector_id}", response_model=RedirectorOut)
async def update_redirector(
    redirector_id: str,
    payload: RedirectorUpdate,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a redirector. Omit ssh_private_key to keep the existing key.
    Send an empty string for ssh_key_passphrase to clear it.
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a redirector and all its stream configs (cascade). Does not remove remote files."""
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    SSH connect to the redirector and verify nginx stream module presence.
    Updates the redirector status (online/offline) and last_tested_at.
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    ssh = _make_ssh_service(svc, redirector)

    try:
        result = await run_test_connection(ssh)
    except SSHConnectionError as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError, Exception) as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_command_error(e)

    new_status = "online" if result["success"] else "offline"
    await svc.update_status(redirector, new_status)

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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    SSH into the redirector and check for common nginx config issues:
    default site active (port 80) and stream block presence.
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    ssh = _make_ssh_service(svc, redirector)
    try:
        return await run_check_nginx_setup(ssh)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except Exception as e:
        raise _ssh_command_error(e)


@router.post("/{redirector_id}/fix-nginx-setup")
async def fix_nginx_setup(
    redirector_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    SSH into the redirector and fix common nginx config issues:
    remove sites-enabled/default, add stream block to nginx.conf, reload nginx.

    Requires additional sudoers entry on the redirector:
        <user> ALL=(ALL) NOPASSWD: /bin/bash /tmp/.cyberx_nginx_fix.sh
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    ssh = _make_ssh_service(svc, redirector)
    try:
        return await run_fix_nginx_setup(ssh, redirector.nginx_stream_dir)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except Exception as e:
        raise _ssh_command_error(e)


@router.post("/{redirector_id}/check-prereqs")
async def check_prereqs(
    redirector_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Check that all CyberX prerequisites are met on the redirector."""
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    ssh = _make_ssh_service(svc, redirector)
    try:
        return await run_check_prereqs(ssh, redirector.nginx_stream_dir)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except Exception as e:
        raise _ssh_command_error(e)


@router.post("/{redirector_id}/fix-prereqs")
async def fix_prereqs(
    redirector_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Attempt to automatically satisfy CyberX prerequisites on the redirector.
    Requires the SSH user to have sudo access (NOPASSWD preferred).
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    ssh = _make_ssh_service(svc, redirector)
    try:
        return await run_fix_prereqs(ssh, redirector.nginx_stream_dir)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except Exception as e:
        raise _ssh_command_error(e)


@router.post("/{redirector_id}/check-port")
async def check_port(
    redirector_id: str,
    body: dict,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    SSH into the redirector and check whether a port is already in use.
    Body: {"port": int, "protocol": "tcp"|"udp"|"dns"}
    Returns: {"in_use": bool, "listeners": [...], "message": str}
    """
    port = body.get("port")
    protocol = body.get("protocol", "tcp")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise HTTPException(status_code=422, detail="port must be an integer between 1 and 65535.")

    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    ssh = _make_ssh_service(svc, redirector)

    try:
        result = await run_check_port(ssh, port, protocol)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except Exception as e:
        raise _ssh_command_error(e)

    return result


@router.post("/{redirector_id}/deploy-all", response_model=DeployResult)
async def deploy_all(
    redirector_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync all stream configs for this redirector:
    write enabled, delete disabled, remove orphans, reload nginx.
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    streams = await svc.list_streams(redirector_id)
    ssh = _make_ssh_service(svc, redirector)

    try:
        result = await run_deploy_all(ssh, redirector.nginx_stream_dir, streams)
    except SSHConnectionError as e:
        await svc.update_status(redirector, "offline")
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError, Exception) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        await svc.update_status(redirector, "online")
        await svc.update_deployed_at(redirector)

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


# ---------------------------------------------------------------------------
# StreamConfig CRUD
# ---------------------------------------------------------------------------

@router.get("/{redirector_id}/streams", response_model=List[StreamConfigOut])
async def list_streams(
    redirector_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all stream configs for a redirector."""
    svc = RedirectorService(db)
    await _get_redirector_or_404(redirector_id, svc)
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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a stream config for a redirector (does not deploy immediately)."""
    svc = RedirectorService(db)
    await _get_redirector_or_404(redirector_id, svc)
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
    current_user: User = Depends(get_current_admin_user),
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
    current_user: User = Depends(get_current_admin_user),
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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a stream config from the database (does not remove remote file)."""
    svc = RedirectorService(db)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)
    name = stream.name
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
    current_user: User = Depends(get_current_admin_user),
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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a stream as enabled, write its config file to the redirector, and reload nginx.
    Rolls back (deletes the file) if nginx -t fails — stream stays enabled in DB on rollback
    so the operator can fix the config and retry.
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)

    stream = await svc.update_stream(stream, {"enabled": True})
    ssh = _make_ssh_service(svc, redirector)

    try:
        result = await run_deploy_single(ssh, redirector.nginx_stream_dir, stream)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError, Exception) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        await svc.update_deployed_at(redirector)

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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Write a single stream config file to the redirector and reload nginx.
    Rolls back (deletes the file) if nginx -t fails.
    Returns HTTP 200 with success=False if nginx test fails (operator sees output).
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)

    if not stream.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stream is disabled. Enable it before deploying.",
        )

    ssh = _make_ssh_service(svc, redirector)

    try:
        result = await run_deploy_single(ssh, redirector.nginx_stream_dir, stream)
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError, Exception) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        await svc.update_deployed_at(redirector)

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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a stream config file from the redirector and reload nginx.
    Does not delete the StreamConfig from the database — use DELETE for that.
    """
    svc = RedirectorService(db)
    redirector = await _get_redirector_or_404(redirector_id, svc)
    stream = await _get_stream_or_404(stream_id, redirector_id, svc)
    ssh = _make_ssh_service(svc, redirector)

    try:
        result = await run_remove_single(
            ssh, redirector.nginx_stream_dir, stream_id, stream.name
        )
    except SSHConnectionError as e:
        raise _ssh_connection_error(e)
    except SSHAuthError as e:
        raise _ssh_auth_error(e)
    except (NginxReloadError, SSHCommandError, Exception) as e:
        raise _ssh_command_error(e)

    if result["success"]:
        await svc.update_stream(stream, {"enabled": False})

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
