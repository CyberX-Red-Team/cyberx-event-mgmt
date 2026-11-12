"""Server-rendered pages must render.

No other test renders a Jinja template, so a framework change that breaks
TemplateResponse passes the rest of the suite while every page returns 500.
Starlette 1.x does exactly that to the name-first call style this app uses.

Page routes are discovered from the page routers rather than listed by hand,
so a new page is covered automatically. Discovery reads each router's own
`.routes` instead of `app.routes`: from FastAPI ~0.13x, included routers are no
longer flattened onto the app, so walking `app.routes` finds nothing.
"""
import re

import pytest

from app.api.routes import admin_pages, redirectors_pages, views


pytestmark = [pytest.mark.integration]

# main.py includes these without an extra prefix, so route paths are final.
PAGE_ROUTERS = (views.router, redirectors_pages.router, admin_pages.router)


def _page_routes() -> list[str]:
    """Parameterless GET routes that serve HTML pages."""
    paths = []
    for router in PAGE_ROUTERS:
        for route in router.routes:
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", "")
            if "GET" in methods and "{" not in path and not path.startswith("/api/"):
                paths.append(path)
    return sorted(set(paths))


def _title(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    return match.group(1).strip() if match else ""


def test_page_routes_were_discovered():
    """Guard against the discovery silently finding nothing."""
    assert len(_page_routes()) >= 20


class TestEveryPageRenders:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", _page_routes())
    async def test_page_does_not_error(self, path, authenticated_admin_client):
        """As an admin, no page may fail to render.

        Redirects are allowed: some pages send admins elsewhere before any
        template runs. A template failure surfaces as a 5xx.
        """
        response = await authenticated_admin_client.get(path)

        assert response.status_code < 500, (
            f"{path} returned {response.status_code}"
        )
        if response.status_code == 200:
            assert "<html" in response.text.lower()


class TestKeyPagesRenderTheirContent:
    """Each role's main page renders the expected template, not an error page."""

    @pytest.mark.asyncio
    async def test_login_page_for_anonymous_visitor(self, client):
        response = await client.get("/login")

        assert response.status_code == 200
        assert "Login" in _title(response.text)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path,title",
        [
            ("/admin/users", "User Management"),
            ("/admin/instances", "Instance Management"),
            ("/admin/redirectors", "Redirectors"),
        ],
    )
    async def test_admin_pages(self, path, title, authenticated_admin_client):
        response = await authenticated_admin_client.get(path)

        assert response.status_code == 200
        assert title in _title(response.text)

    @pytest.mark.asyncio
    async def test_sponsor_invitees_page(self, authenticated_sponsor_client):
        response = await authenticated_sponsor_client.get("/sponsor/invitees")

        assert response.status_code == 200
        assert "My Invitees" in _title(response.text)

    @pytest.mark.asyncio
    async def test_participant_portal(self, authenticated_invitee_client):
        response = await authenticated_invitee_client.get("/portal")

        assert response.status_code == 200
        assert "Participant Portal" in _title(response.text)
