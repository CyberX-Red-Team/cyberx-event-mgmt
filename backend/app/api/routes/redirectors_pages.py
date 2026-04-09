"""HTML page routes for the Redirector Manager UI.

These routes serve Jinja2 templates. They are separate from the REST API
routes in redirectors.py and should be included alongside views.py in main.py.

Integration in main.py:
    from app.api.routes import redirectors as redirectors_api
    from app.api.routes import redirectors_pages
    app.include_router(redirectors_api.router)
    app.include_router(redirectors_pages.router)
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.dependencies import get_db, require_permission
from app.models.user import User
from app.services.redirector_service import RedirectorService
from app.api.routes.views import templates
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["Redirector Pages"])


@router.get("/admin/redirectors", response_class=HTMLResponse)
async def redirectors_list_page(
    request: Request,
    current_user: User = Depends(require_permission("redirectors.view")),
):
    """Render the redirectors list page."""
    return templates.TemplateResponse(
        "pages/redirectors/list.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "redirectors",
            "now": datetime.now(),
        },
    )


@router.get("/admin/redirectors/{redirector_id}", response_class=HTMLResponse)
async def redirector_detail_page(
    redirector_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.view")),
    db: AsyncSession = Depends(get_db),
):
    """Render the redirector detail page with stream configs."""
    svc = RedirectorService(db)
    redirector = await svc.get_redirector(redirector_id)
    if not redirector:
        raise HTTPException(status_code=404, detail="Redirector not found.")
    # Owner check: non-admins can only view their own redirectors
    if not current_user.has_permission("redirectors.view_all") and redirector.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this redirector.")

    return templates.TemplateResponse(
        "pages/redirectors/detail.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "redirectors",
            "redirector": redirector,
            "now": datetime.now(),
        },
    )


@router.get("/portal/redirectors/{redirector_id}", response_class=HTMLResponse)
async def participant_redirector_detail_page(
    redirector_id: str,
    request: Request,
    current_user: User = Depends(require_permission("redirectors.view")),
    db: AsyncSession = Depends(get_db),
):
    """Render the participant redirector detail page with stream configs."""
    svc = RedirectorService(db)
    redirector = await svc.get_redirector(redirector_id)
    if not redirector:
        raise HTTPException(status_code=404, detail="Redirector not found.")
    if not current_user.has_permission("redirectors.view_all") and redirector.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this redirector.")

    return templates.TemplateResponse(
        "pages/participant/redirector_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "redirector": redirector,
            "now": datetime.now(),
        },
    )
