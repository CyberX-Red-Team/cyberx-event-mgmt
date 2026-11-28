"""Routes must persist changes even though app.database.get_db and
app.dependencies.get_db hand out different sessions in production.

The shared `client` fixture overrides both with one session, which hid two
bugs: confirming in-person attendance never saved confirmed_in_person, and the
referrer "I'm their parent or guardian" link was never saved. This client gives
each its own session, like production.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_db as database_get_db
from app.dependencies import get_db as dependencies_get_db
from app.main import app
from app.models.participant_action import ParticipantAction
from app.models.user import User
from app.utils.encryption import init_encryptor
from tests.personal_data_seed import make_event

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def split_client(async_engine, db_session, test_settings):
    init_encryptor(test_settings.ENCRYPTION_KEY)
    from app.api.routes import auth
    auth._rate_limit_cache.clear()
    # Same settings as production's AsyncSessionLocal (app/database.py)
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False,
                                 autocommit=False, autoflush=False)

    def per_request():
        async def _get():
            async with factory() as s:
                yield s
        return _get

    app.dependency_overrides[database_get_db] = per_request()
    app.dependency_overrides[dependencies_get_db] = per_request()
    from app.middleware.csrf import CSRFMiddleware
    original = CSRFMiddleware._is_exempt
    CSRFMiddleware._is_exempt = lambda self, path: True
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as c:
        yield c
    CSRFMiddleware._is_exempt = original
    app.dependency_overrides.clear()


async def _login(client, email, password):
    r = await client.post("/api/auth/login", json={"username": email, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.set("session_token", r.cookies.get("session_token"))


async def _fresh(async_engine, model, pk):
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        return await s.get(model, pk)


async def test_in_person_confirmation_is_saved(split_client, async_engine, db_session, invitee_user):
    event = await make_event(db_session, "Live", is_active=True)
    action = ParticipantAction(user_id=invitee_user.id, event_id=event.id,
                               action_type="in_person_attendance", title="In person")
    db_session.add(action)
    await db_session.commit()

    await _login(split_client, invitee_user.email, "invitee123")
    r = await split_client.post(f"/api/participants/actions/{action.id}/respond", json={"status": "confirmed"})
    assert r.status_code == 200, r.text
    assert (await _fresh(async_engine, User, invitee_user.id)).confirmed_in_person is True


async def test_in_person_decline_is_saved(split_client, async_engine, db_session, invitee_user):
    event = await make_event(db_session, "Live", is_active=True)
    u = await db_session.get(User, invitee_user.id)
    u.confirmed_in_person = True
    action = ParticipantAction(user_id=invitee_user.id, event_id=event.id,
                               action_type="in_person_attendance", title="In person")
    db_session.add(action)
    await db_session.commit()

    await _login(split_client, invitee_user.email, "invitee123")
    r = await split_client.post(f"/api/participants/actions/{action.id}/respond", json={"status": "declined"})
    assert r.status_code == 200, r.text
    assert (await _fresh(async_engine, User, invitee_user.id)).confirmed_in_person is False


async def test_referrer_guardian_shortcut_is_saved(split_client, async_engine, sponsor_user, invitee_role):
    await _login(split_client, sponsor_user.email, "sponsor123")
    r = await split_client.post("/api/sponsors/my-invitees", json={
        "email": "kid@example.org", "first_name": "Kim", "last_name": "Kid", "country": "USA",
        "referrer_is_guardian": True,
    })
    assert r.status_code == 200, r.text
    kid = await _fresh(async_engine, User, r.json()["id"])
    assert kid.guardian_user_id == sponsor_user.id
    assert kid.guardian_link_status == "pending"


async def test_admin_minor_alerts_are_not_merged(db_session, admin_user):
    """Two alerts while the first is still pending must both be queued."""
    from app.models.email_queue import EmailQueue
    from app.services.minor_service import notify_admins
    from tests.personal_data_seed import make_user
    a = await make_user(db_session, "kid1@example.org")
    b = await make_user(db_session, "kid2@example.org")
    await notify_admins(db_session, "guardian_not_registered", a)
    await notify_admins(db_session, "guardian_link_rejected", b)
    rows = (await db_session.execute(
        select(EmailQueue).where(EmailQueue.template_name == "admin_minor_alert")
    )).scalars().all()
    assert sorted((r.custom_vars["minor_user_id"], r.custom_vars["reason"]) for r in rows) == [
        (str(a.id), "guardian not registered"), (str(b.id), "guardian link rejected"),
    ]


async def test_duplicate_check_tolerates_several_pending_rows(db_session, admin_user):
    from app.models.email_queue import EmailQueue
    from app.services.email_queue_service import EmailQueueService
    for _ in range(2):
        db_session.add(EmailQueue(user_id=admin_user.id, template_name="t", recipient_email=admin_user.email,
                                  status="pending"))
    await db_session.commit()
    entry = await EmailQueueService(db_session).enqueue_email(user_id=admin_user.id, template_name="t")
    assert entry.status == "pending"  # returned an existing row instead of raising
