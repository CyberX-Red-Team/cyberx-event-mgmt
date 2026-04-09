"""HTML page routes for general admin UI features (logs, etc.).

These routes serve Jinja2 templates and internal JSON APIs for admin tools
that are not specific to any single feature module.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.dependencies import require_permission
from app.models.user import User
from app.services.log_buffer import get_recent_logs
from app.api.routes.views import templates

router = APIRouter(tags=["Admin Pages"])


# ---------------------------------------------------------------------------
# Error Log Viewer
# ---------------------------------------------------------------------------

@router.get("/admin/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    current_user: User = Depends(require_permission("admin.view_audit_log")),
):
    """Render the application error log viewer page."""
    return templates.TemplateResponse(
        "pages/admin/logs.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "logs",
            "now": datetime.now(),
        },
    )


@router.get("/api/internal/logs")
async def internal_logs(
    current_user: User = Depends(require_permission("admin.view_audit_log")),
    n: int = Query(default=200, ge=1, le=500),
):
    """Return recent application log entries as JSON."""
    return JSONResponse(content={"logs": get_recent_logs(n)})
