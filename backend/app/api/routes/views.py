"""Frontend view routes for serving HTML templates."""
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.exceptions import not_found, forbidden, bad_request, conflict, unauthorized, server_error
from app.dependencies import get_optional_user, get_current_active_user, get_current_admin_user, get_current_sponsor_user
from app.models.user import User
from app.config import get_version


router = APIRouter(tags=["Views"])

# Configure Jinja2 templates - path is relative to backend directory
templates_path = Path(__file__).parent.parent.parent.parent.parent / "frontend" / "templates"
templates = Jinja2Templates(directory=str(templates_path))

# Add global context processor for version
templates.env.globals["app_version"] = get_version()


# Authentication pages
@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    current_user: User = Depends(get_optional_user)
):
    """Render login page."""
    # Redirect if already logged in
    if current_user:
        if current_user.is_admin or current_user.role == 'admin':
            return RedirectResponse(url="/admin/dashboard", status_code=302)
        return RedirectResponse(url="/portal", status_code=302)

    return templates.TemplateResponse(
        "pages/auth/login.html",
        {"request": request, "now": datetime.now()}
    )


@router.get("/confirm", response_class=HTMLResponse)
async def confirmation_page(
    request: Request
):
    """Render public confirmation page (no authentication required)."""
    return templates.TemplateResponse(
        "pages/public/confirm.html",
        {"request": request, "now": datetime.now()}
    )


@router.get("/", response_class=HTMLResponse)
async def home_page(
    request: Request,
    current_user: User = Depends(get_optional_user)
):
    """Home page - redirect to appropriate dashboard."""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    if current_user.is_admin or current_user.role == 'admin':
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    return RedirectResponse(url="/portal", status_code=302)


# Admin pages
@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render admin dashboard."""
    return templates.TemplateResponse(
        "pages/admin/dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "dashboard",
            "now": datetime.now()
        }
    )


@router.get("/admin/participants")
async def admin_participants_page(
    current_user: User = Depends(get_current_admin_user)
):
    """Redirect to unified invitees page."""
    return RedirectResponse(url="/admin/users", status_code=301)


@router.get("/admin/participants/add")
async def admin_add_participant_page(
    current_user: User = Depends(get_current_admin_user)
):
    """Redirect to unified invitees page."""
    return RedirectResponse(url="/admin/users", status_code=301)


@router.get("/admin/participants/{participant_id}")
async def admin_edit_participant_page(
    participant_id: int,
    current_user: User = Depends(get_current_admin_user)
):
    """Redirect to unified invitees page."""
    return RedirectResponse(url="/admin/users", status_code=301)


@router.get("/admin/vpn", response_class=HTMLResponse)
async def admin_vpn_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render VPN management page."""
    return templates.TemplateResponse(
        "pages/admin/vpn.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "vpn",
            "now": datetime.now()
        }
    )


@router.get("/admin/email", response_class=HTMLResponse)
async def admin_email_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render email management page."""
    return templates.TemplateResponse(
        "pages/admin/email.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "email",
            "now": datetime.now()
        }
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render user management page (admin only)."""
    # Double-check user is an admin
    if current_user.role != "admin":
        raise forbidden("Admin access required")

    return templates.TemplateResponse(
        "pages/admin/users.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "participants",
            "now": datetime.now()
        }
    )


@router.get("/admin/audit", response_class=HTMLResponse)
async def admin_audit_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render audit log page (admin only)."""
    return templates.TemplateResponse(
        "pages/admin/audit.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "audit",
            "now": datetime.now()
        }
    )


@router.get("/admin/workflows", response_class=HTMLResponse)
async def admin_workflows_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render email workflows management page (admin only)."""
    return templates.TemplateResponse(
        "pages/admin/workflows.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "workflows",
            "now": datetime.now()
        }
    )


@router.get("/admin/events", response_class=HTMLResponse)
async def admin_events_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render events management page (admin only)."""
    return templates.TemplateResponse(
        "pages/admin/events.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "events",
            "now": datetime.now()
        }
    )


@router.get("/admin/instances", response_class=HTMLResponse)
async def admin_instances_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render instance management page (admin only)."""
    return templates.TemplateResponse(
        "pages/admin/instances.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "instances",
            "now": datetime.now()
        }
    )


@router.get("/admin/instance-templates", response_class=HTMLResponse)
async def admin_instance_templates_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render instance templates management page (admin only)."""
    return templates.TemplateResponse(
        "pages/admin/instance_templates.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "instance-templates",
            "now": datetime.now()
        }
    )


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render system settings page (admin only)."""
    return templates.TemplateResponse(
        "pages/admin/settings.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "settings",
            "now": datetime.now()
        }
    )


@router.get("/admin/cloud-init", response_class=HTMLResponse)
async def admin_cloud_init_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render cloud-init template management page (admin only)."""
    return templates.TemplateResponse(
        "pages/admin/cloud_init.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "cloud_init",
            "now": datetime.now()
        }
    )


@router.get("/admin/licenses", response_class=HTMLResponse)
async def admin_licenses_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user)
):
    """Render license products management page (admin only)."""
    return templates.TemplateResponse(
        "pages/admin/license_products.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "licenses",
            "now": datetime.now()
        }
    )


# Sponsor pages
@router.get("/sponsor/invitees", response_class=HTMLResponse)
async def sponsor_invitees_page(
    request: Request,
    current_user: User = Depends(get_current_sponsor_user)
):
    """Render sponsor invitees management page."""
    return templates.TemplateResponse(
        "pages/sponsor/invitees.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "invitees",
            "now": datetime.now()
        }
    )


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: User = Depends(get_current_active_user)
):
    """Render user profile/settings page."""
    return templates.TemplateResponse(
        "pages/profile.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "profile",
            "now": datetime.now()
        }
    )


# Participant portal pages
@router.get("/portal", response_class=HTMLResponse)
async def participant_portal_page(
    request: Request,
    current_user: User = Depends(get_current_active_user)
):
    """Render participant portal dashboard."""
    return templates.TemplateResponse(
        "pages/participant/portal.html",
        {
            "request": request,
            "current_user": current_user,
            "now": datetime.now()
        }
    )


@router.get("/portal/vpn", response_class=HTMLResponse)
async def participant_vpn_page(
    request: Request,
    current_user: User = Depends(get_current_active_user)
):
    """Render participant VPN page."""
    return templates.TemplateResponse(
        "pages/participant/vpn.html",
        {
            "request": request,
            "current_user": current_user,
            "now": datetime.now()
        }
    )


@router.get("/portal/ssh-key", response_class=HTMLResponse)
async def participant_ssh_key_page(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    event_service: EventService = Depends(get_event_service)
):
    """Render participant SSH key page."""

    # Get the active event
    active_event = await event_service.get_active_event()
    if not active_event:
        raise HTTPException(status_code=404, detail="No active event found")

    # Check if user is a confirmed participant
    participation = await event_service.get_participation_by_user_and_event(
        current_user.id, active_event.id
    )
    if not participation or participation.status != "confirmed":
        raise forbidden("You must be a confirmed participant to access the SSH key")

    return templates.TemplateResponse(
        "pages/participant/ssh_key.html",
        {
            "request": request,
            "current_user": current_user,
            "event_id": active_event.id,
            "event_name": active_event.name,
            "event_slug": active_event.slug,
            "now": datetime.now()
        }
    )
