"""The license install queue requires a real license token for the product.

Mirrors cloud-init-utils/hexio_setup.py: fetch the blob (consumes the token),
acquire a slot with the same token, install, release.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.license import LicenseSlot, LicenseToken
from app.services.license_service import LicenseService


pytestmark = [pytest.mark.integration]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def products(db_session):
    service = LicenseService(db_session)
    a = await service.create_product(name="Hexio A", license_blob="BLOB-A", max_concurrent=2)
    b = await service.create_product(name="Hexio B", license_blob="BLOB-B", max_concurrent=2)
    return a, b


async def _token(db_session, product):
    return await LicenseService(db_session).generate_token(product.id)


async def _slot_count(db_session):
    db_session.expire_all()
    return (await db_session.execute(
        select(func.count(LicenseSlot.id)).where(LicenseSlot.is_active == True)  # noqa: E712
    )).scalar()


async def _acquire(client, token, product_id, hostname="vm-1"):
    return await client.post(
        "/api/license/queue/acquire", headers=_bearer(token),
        json={"product_id": product_id, "hostname": hostname},
    )


async def _release(client, token, slot_id):
    return await client.post(
        "/api/license/queue/release", headers=_bearer(token),
        json={"slot_id": slot_id, "result": "success", "elapsed_seconds": 42},
    )


@pytest.mark.asyncio
class TestLicenseQueueAuthorization:

    async def test_full_vm_flow_blob_then_acquire_then_release(self, client, db_session, products):
        product, _ = products
        token = await _token(db_session, product)

        blob = await client.get("/api/license/blob", headers=_bearer(token))
        assert blob.status_code == 200, blob.text            # token now consumed
        acquired = await _acquire(client, token, product.id)
        assert acquired.status_code == 200, acquired.text   # used token still OK for the queue
        assert acquired.json()["status"] == "granted"
        slot_id = acquired.json()["slot_id"]

        released = await _release(client, token, slot_id)
        assert released.status_code == 200, released.text
        assert await _slot_count(db_session) == 0

    @pytest.mark.parametrize("header", [
        "Bearer not-a-real-token", "Bearer x", "Basic abc", "Bearer ",
    ])
    async def test_unknown_or_malformed_token_cannot_acquire(
        self, client, db_session, products, header,
    ):
        product, _ = products
        response = await client.post(
            "/api/license/queue/acquire", headers={"Authorization": header},
            json={"product_id": product.id},
        )
        assert response.status_code == 401
        assert await _slot_count(db_session) == 0

    async def test_token_for_another_product_cannot_acquire(self, client, db_session, products):
        a, b = products
        token_for_a = await _token(db_session, a)
        response = await _acquire(client, token_for_a, b.id)
        assert response.status_code == 401
        assert await _slot_count(db_session) == 0

    async def test_token_past_its_queue_window_cannot_acquire(
        self, client, db_session, products,
    ):
        product, _ = products   # slot_ttl defaults to 7200
        token = await _token(db_session, product)
        row = (await db_session.execute(select(LicenseToken))).scalars().one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=product.slot_ttl + 1)
        await db_session.commit()

        response = await _acquire(client, token, product.id)
        assert response.status_code == 401
        assert await _slot_count(db_session) == 0

    async def test_vm_waiting_past_token_expiry_still_gets_a_slot(
        self, client, db_session, products,
    ):
        # Fill the queue, then a third VM polls after its blob token expired.
        product, _ = products   # max_concurrent=2
        holders = [await _token(db_session, product) for _ in range(2)]
        slots = [(await _acquire(client, t, product.id, f"vm-{i}")).json()["slot_id"]
                 for i, t in enumerate(holders)]
        waiter = await _token(db_session, product)
        assert (await _acquire(client, waiter, product.id, "vm-wait")).json()["status"] == "wait"

        db_session.expire_all()
        row = (await db_session.execute(
            select(LicenseToken).order_by(LicenseToken.id.desc())
        )).scalars().first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=30)  # past token_ttl
        await db_session.commit()

        assert (await _release(client, holders[0], slots[0])).status_code == 200
        granted = await _acquire(client, waiter, product.id, "vm-wait")
        assert granted.status_code == 200, granted.text
        assert granted.json()["status"] == "granted"

    async def test_one_token_cannot_fill_the_queue(self, client, db_session, products):
        product, _ = products
        token = await _token(db_session, product)
        first = await _acquire(client, token, product.id)
        again = await _acquire(client, token, product.id, hostname="vm-1-retry")
        assert first.json()["status"] == again.json()["status"] == "granted"
        assert first.json()["slot_id"] == again.json()["slot_id"]   # idempotent retry
        assert await _slot_count(db_session) == 1

    async def test_distinct_tokens_share_the_concurrency_limit(self, client, db_session, products):
        product, _ = products   # max_concurrent=2
        statuses = []
        for i in range(3):
            token = await _token(db_session, product)
            statuses.append((await _acquire(client, token, product.id, f"vm-{i}")).json()["status"])
        assert statuses == ["granted", "granted", "wait"]
        assert await _slot_count(db_session) == 2

    async def test_release_requires_the_acquiring_token(self, client, db_session, products):
        product, _ = products
        owner = await _token(db_session, product)
        other = await _token(db_session, product)
        slot_id = (await _acquire(client, owner, product.id)).json()["slot_id"]

        assert (await _release(client, other, slot_id)).status_code == 403
        assert (await _release(client, "Bearer-garbage", slot_id)).status_code == 401
        assert await _slot_count(db_session) == 1
        assert (await _release(client, owner, slot_id)).status_code == 200
        assert await _slot_count(db_session) == 0

    async def test_release_works_after_the_token_expires(self, client, db_session, products):
        product, _ = products
        token = await _token(db_session, product)
        slot_id = (await _acquire(client, token, product.id)).json()["slot_id"]
        db_session.expire_all()
        row = (await db_session.execute(select(LicenseToken))).scalars().one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db_session.commit()

        assert (await _release(client, token, slot_id)).status_code == 200

    async def test_release_unknown_slot_is_404(self, client, db_session, products):
        product, _ = products
        token = await _token(db_session, product)
        assert (await _release(client, token, "no-such-slot")).status_code == 404

    async def test_legacy_unbound_slot_releases_with_a_same_product_token(
        self, client, db_session, products,
    ):
        a, b = products
        db_session.add(LicenseSlot(slot_id="legacy-slot", product_id=a.id, token_id=None))
        await db_session.commit()
        token_b = await _token(db_session, b)
        token_a = await _token(db_session, a)

        assert (await _release(client, token_b, "legacy-slot")).status_code == 403
        assert (await _release(client, token_a, "legacy-slot")).status_code == 200

    async def test_blob_endpoint_still_single_use(self, client, db_session, products):
        product, _ = products
        token = await _token(db_session, product)
        assert (await client.get("/api/license/blob", headers=_bearer(token))).status_code == 200
        assert (await client.get("/api/license/blob", headers=_bearer(token))).status_code == 401


@pytest.mark.asyncio
class TestHexioSetupWireFormat:
    """Replays hexio_setup.py's requests and checks the fields it reads."""

    async def test_script_acquire_and_release_round_trip(self, client, db_session, products):
        product, _ = products
        token = await _token(db_session, product)
        headers = {**_bearer(token), "Content-Type": "application/json",
                   "User-Agent": "hexio-setup/1.0"}

        # acquire_queue_slot(): payload is {"hostname": hostname} -- no product_id
        acquired = await client.post(
            "/api/license/queue/acquire", headers=headers, json={"hostname": "ts-01"},
        )
        assert acquired.status_code == 200, acquired.text
        body = acquired.json()
        assert body["status"] == "granted"
        slot_id = body["slot_id"]
        # The script logs body["slot_id"][:8], body["active"], body["max"]
        assert isinstance(slot_id, str) and len(slot_id) >= 8
        assert body["active"] == 1 and body["max"] == product.max_concurrent

        # release_queue_slot(): payload uses "elapsed", reads body["active"/"max"]
        released = await client.post(
            "/api/license/queue/release", headers=headers,
            json={"slot_id": slot_id, "result": "success", "elapsed": 321},
        )
        assert released.status_code == 200, released.text
        assert released.json()["active"] == 0
        assert released.json()["max"] == product.max_concurrent

        db_session.expire_all()
        slot = (await db_session.execute(select(LicenseSlot))).scalars().one()
        assert slot.elapsed_seconds == 321      # "elapsed" accepted
        assert slot.result == "success"

    async def test_script_wait_response_has_the_fields_it_reads(
        self, client, db_session, products,
    ):
        product, _ = products   # max_concurrent=2
        for i in range(2):
            await client.post(
                "/api/license/queue/acquire",
                headers=_bearer(await _token(db_session, product)),
                json={"hostname": f"ts-{i}"},
            )
        waiting = await client.post(
            "/api/license/queue/acquire",
            headers=_bearer(await _token(db_session, product)),
            json={"hostname": "ts-wait"},
        )
        body = waiting.json()
        # The script reads body["retry_after"], body["active"], body["max"]
        assert body["status"] == "wait"
        assert body["active"] == 2 and body["max"] == 2
        assert body["retry_after"] > 0
