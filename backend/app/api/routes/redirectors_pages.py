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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_current_admin_user
from app.models.user import User
from app.services.redirector_service import RedirectorService
from app.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["Redirector Pages"])

# Template path matches the main app's views.py template resolution
_templates_path = Path(__file__).parent.parent.parent.parent.parent.parent / "frontend" / "templates"
templates = Jinja2Templates(directory=str(_templates_path))


@router.get("/admin/redirectors", response_class=HTMLResponse)
async def redirectors_list_page(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
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
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Render the redirector detail page with stream configs."""
    svc = RedirectorService(db)
    redirector = await svc.get_redirector(redirector_id)
    if not redirector:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Redirector not found.")

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
