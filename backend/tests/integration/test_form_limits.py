"""Starlette's form-parsing limits (max_fields / max_part_size) apply to
application/x-www-form-urlencoded bodies as well as multipart."""
import pytest


pytestmark = [pytest.mark.integration]

# A real route taking plain form fields (see test_form_parsing.py).
FORM_ROUTE = "/api/participants/instances/1"
URLENCODED = {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.mark.asyncio
class TestUrlencodedFormLimits:

    async def test_too_many_fields_is_rejected(self, client):
        body = "&".join(f"f{i}=v" for i in range(5000)).encode()   # default max_fields is 1000
        response = await client.patch(FORM_ROUTE, content=body, headers=URLENCODED)
        assert response.status_code == 400, response.text

    async def test_oversized_field_is_rejected(self, client):
        body = b"notes=" + b"a" * (2 * 1024 * 1024)                 # default max_part_size is 1 MiB
        response = await client.patch(FORM_ROUTE, content=body, headers=URLENCODED)
        assert response.status_code == 400, response.text

    async def test_normal_form_is_parsed(self, client):
        response = await client.patch(
            FORM_ROUTE, content=b"visibility=public&notes=hi", headers=URLENCODED,
        )
        assert response.status_code == 401
