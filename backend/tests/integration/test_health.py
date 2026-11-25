"""/health reports version and deployed commit for deploy verification."""
import pytest

from app.version import VERSION


pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_health_reports_version_and_short_commit(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": VERSION, "commit": "0123456"}


@pytest.mark.asyncio
async def test_health_without_render_commit(client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["commit"] == ""
    assert response.json()["status"] == "healthy"
