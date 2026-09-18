"""Authorization tests for the admin participant endpoints.

These cover a privilege escalation reachable by the default Sponsor role:
several /api/admin/participants routes are guarded only by `participants.edit`,
which Sponsor holds, and the update route accepts fields that change
authentication and role state.

Two conventions matter here:

1. **Assert database state, not just the status code.** These endpoints commit
   before building their response, so "not 200" does not mean "nothing
   happened".
2. **Don't mock the service or the permission dependency.** The bug lives in the
   wiring between the route guard and the service, which is exactly what a mock
   would hide.
"""
import pytest
from sqlalchemy import select

from app.models.role import Role
from app.models.user import User, UserRole
from app.utils.security import verify_password


pytestmark = [
    pytest.mark.integration,
    pytest.mark.security,
    pytest.mark.auth,
]


async def _reload(db_session, user_id: int) -> User:
    """Re-read a user from the database, bypassing the identity map."""
    db_session.expire_all()
    result = await db_session.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


@pytest.fixture
def as_actor(client, sponsor_session_token, invitee_session_token):
    """Authenticate the shared client as a named non-admin actor.

    Deliberately NOT a dict of pre-authenticated clients: the authenticated_*
    fixtures all set a cookie on the same underlying client, so building two of
    them makes the second silently win and the test runs as the wrong user.
    """
    tokens = {"sponsor": sponsor_session_token, "invitee": invitee_session_token}

    def _login_as(actor: str):
        client.cookies.set("session_token", tokens[actor])
        return client

    return _login_as


# ============================================================================
# Layer 1 - endpoint authorization
# ============================================================================

class TestAdminParticipantRoutesRejectNonAdmins:
    """Escalation routes must require an admin-level permission."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("actor", ["sponsor", "invitee"])
    async def test_cannot_reassign_sponsor(
        self, actor, as_actor, db_session, admin_user, sponsor_user
    ):
        """Nobody but an admin may change who sponsors a user.

        This is step 1 of the takeover chain: claiming a victim as your own
        invitee is what makes the later edit pass its ownership check.
        """
        client = as_actor(actor)
        victim_id = admin_user.id
        original_sponsor_id = admin_user.sponsor_id

        response = await client.put(
            f"/api/admin/participants/{victim_id}/sponsor",
            json={"participant_id": victim_id, "sponsor_id": sponsor_user.id},
        )

        assert response.status_code == 403
        victim = await _reload(db_session, victim_id)
        assert victim.sponsor_id == original_sponsor_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("actor", ["sponsor", "invitee"])
    async def test_cannot_change_role(
        self, actor, as_actor, db_session, invitee_user
    ):
        """Nobody but an admin may change a user's role."""
        client = as_actor(actor)
        target_id = invitee_user.id

        response = await client.put(
            f"/api/admin/participants/{target_id}/role",
            json={"participant_id": target_id, "role": UserRole.ADMIN.value},
        )

        assert response.status_code == 403
        target = await _reload(db_session, target_id)
        assert target.role == UserRole.INVITEE.value
        assert target.is_admin is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("actor", ["sponsor", "invitee"])
    async def test_cannot_bulk_deactivate(
        self, actor, as_actor, db_session, admin_user
    ):
        """Bulk actions are unscoped, so they must be admin-only.

        Deactivating a user kills their sessions on the next request.
        """
        client = as_actor(actor)
        victim_id = admin_user.id

        response = await client.post(
            "/api/admin/participants/bulk",
            json={"participant_ids": [victim_id], "action": "deactivate"},
        )

        assert response.status_code == 403
        victim = await _reload(db_session, victim_id)
        assert victim.is_active is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("actor", ["sponsor", "invitee"])
    async def test_cannot_assign_role_id(
        self, actor, as_actor, db_session, invitee_user, admin_role
    ):
        """Regression guard: assign-role already requires admin.manage_roles."""
        client = as_actor(actor)
        target_id = invitee_user.id
        original_role_id = invitee_user.role_id

        response = await client.put(
            f"/api/admin/participants/{target_id}/assign-role",
            json={"role_id": admin_role.id},
        )

        assert response.status_code == 403
        target = await _reload(db_session, target_id)
        assert target.role_id == original_role_id
        assert target.is_admin is False


# ============================================================================
# Layer 2 - field-level restrictions on the update route
# ============================================================================

class TestAdminUpdateRouteRejectsSponsors:
    """The admin update route accepts auth- and role-changing fields, so it is
    admin-only. A sponsor must not reach it even for an invitee they sponsor.

    Sponsors edit invitees through /api/sponsors/my-invitees/{id} instead; that
    route's restrictions are covered in TestSponsorRouteRestrictions below.
    """

    @pytest.mark.asyncio
    async def test_cannot_set_password(
        self, authenticated_sponsor_client, db_session, invitee_user
    ):
        """Setting pandas_password rewrites password_hash - account takeover."""
        target_id = invitee_user.id
        original_hash = invitee_user.password_hash

        response = await authenticated_sponsor_client.put(
            f"/api/admin/participants/{target_id}",
            json={"pandas_password": "sponsor-chosen-password-123"},
        )

        assert response.status_code == 403
        target = await _reload(db_session, target_id)
        assert target.password_hash == original_hash
        assert not verify_password("sponsor-chosen-password-123", target.password_hash)

    @pytest.mark.asyncio
    async def test_cannot_set_role_id(
        self, authenticated_sponsor_client, db_session, invitee_user, admin_role
    ):
        """role_id syncs role and is_admin from the target role."""
        target_id = invitee_user.id
        original_role_id = invitee_user.role_id

        response = await authenticated_sponsor_client.put(
            f"/api/admin/participants/{target_id}",
            json={"role_id": admin_role.id},
        )

        assert response.status_code == 403
        target = await _reload(db_session, target_id)
        assert target.role_id == original_role_id
        assert target.role == UserRole.INVITEE.value
        assert target.is_admin is False

    @pytest.mark.asyncio
    async def test_cannot_set_is_admin(
        self, authenticated_sponsor_client, db_session, invitee_user
    ):
        target_id = invitee_user.id

        response = await authenticated_sponsor_client.put(
            f"/api/admin/participants/{target_id}",
            json={"is_admin": True},
        )

        assert response.status_code == 403
        target = await _reload(db_session, target_id)
        assert target.is_admin is False

    @pytest.mark.asyncio
    async def test_cannot_set_is_active(
        self, authenticated_sponsor_client, db_session, invitee_user
    ):
        target_id = invitee_user.id

        response = await authenticated_sponsor_client.put(
            f"/api/admin/participants/{target_id}",
            json={"is_active": False},
        )

        assert response.status_code == 403
        target = await _reload(db_session, target_id)
        assert target.is_active is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({"role": UserRole.ADMIN.value}, id="role"),
            pytest.param({"sponsor_id": 1}, id="sponsor_id"),
        ],
    )
    async def test_already_blocked_fields_stay_blocked(
        self, payload, authenticated_sponsor_client, db_session, invitee_user
    ):
        """Controls: these two are already rejected today. Keep it that way."""
        target_id = invitee_user.id
        original_role = invitee_user.role
        original_sponsor_id = invitee_user.sponsor_id

        response = await authenticated_sponsor_client.put(
            f"/api/admin/participants/{target_id}", json=payload
        )

        assert response.status_code == 403
        target = await _reload(db_session, target_id)
        assert target.role == original_role
        assert target.sponsor_id == original_sponsor_id


class TestSponsorRouteRestrictions:
    """The sponsor path must stay usable, and stay limited.

    Its schema is an allowlist, so fields outside it are dropped rather than
    rejected - these tests assert the stored value, not the status code.
    """

    @pytest.mark.asyncio
    async def test_sponsor_can_edit_own_invitee(
        self, authenticated_sponsor_client, db_session, invitee_user
    ):
        """Control: a sponsor must still be able to correct their invitee."""
        target_id = invitee_user.id

        response = await authenticated_sponsor_client.put(
            f"/api/sponsors/my-invitees/{target_id}",
            json={"first_name": "Corrected"},
        )

        assert response.status_code == 200
        target = await _reload(db_session, target_id)
        assert target.first_name == "Corrected"

    @pytest.mark.asyncio
    async def test_sponsor_cannot_reach_someone_elses_invitee(
        self, authenticated_sponsor_client, db_session, admin_user
    ):
        """Ownership check on the sponsor route."""
        victim_id = admin_user.id
        original_first_name = admin_user.first_name

        response = await authenticated_sponsor_client.put(
            f"/api/sponsors/my-invitees/{victim_id}",
            json={"first_name": "Hijacked"},
        )

        assert response.status_code in (403, 404)
        victim = await _reload(db_session, victim_id)
        assert victim.first_name == original_first_name

    @pytest.mark.asyncio
    async def test_sponsor_cannot_set_password_via_sponsor_route(
        self, authenticated_sponsor_client, db_session, invitee_user
    ):
        """pandas_password is not in the schema, so it must be dropped."""
        target_id = invitee_user.id
        original_hash = invitee_user.password_hash

        await authenticated_sponsor_client.put(
            f"/api/sponsors/my-invitees/{target_id}",
            json={"first_name": "Corrected", "pandas_password": "sponsor-chosen-123"},
        )

        target = await _reload(db_session, target_id)
        assert target.password_hash == original_hash
        assert not verify_password("sponsor-chosen-123", target.password_hash)

    @pytest.mark.asyncio
    async def test_sponsor_cannot_set_confirmed_via_sponsor_route(
        self, authenticated_sponsor_client, db_session, invitee_user
    ):
        """Confirmation status belongs to /confirm/accept and /confirm/decline."""
        target_id = invitee_user.id
        original_confirmed = invitee_user.confirmed

        await authenticated_sponsor_client.put(
            f"/api/sponsors/my-invitees/{target_id}",
            json={"first_name": "Corrected", "confirmed": "YES"},
        )

        target = await _reload(db_session, target_id)
        assert target.confirmed == original_confirmed

    @pytest.mark.asyncio
    async def test_sponsor_cannot_assign_non_invitee_role(
        self, authenticated_sponsor_client, db_session, invitee_user, admin_role
    ):
        """role_id is restricted to invitee-type roles."""
        target_id = invitee_user.id
        original_role_id = invitee_user.role_id

        response = await authenticated_sponsor_client.put(
            f"/api/sponsors/my-invitees/{target_id}",
            json={"role_id": admin_role.id},
        )

        assert response.status_code == 403
        target = await _reload(db_session, target_id)
        assert target.role_id == original_role_id
        assert target.is_admin is False


# ============================================================================
# Layer 3 - the attack chains, end to end
# ============================================================================

class TestEscalationChains:
    """Whole attacks, not individual endpoints."""

    @pytest.mark.asyncio
    async def test_sponsor_cannot_take_over_admin_account(
        self, authenticated_sponsor_client, client, db_session, sponsor_user, admin_user
    ):
        """Claim an admin, set their password, log in as them."""
        victim_id = admin_user.id
        victim_email = admin_user.email
        attacker_password = "pwned-by-sponsor-123"

        claim = await authenticated_sponsor_client.put(
            f"/api/admin/participants/{victim_id}/sponsor",
            json={"participant_id": victim_id, "sponsor_id": sponsor_user.id},
        )
        takeover = await authenticated_sponsor_client.put(
            f"/api/admin/participants/{victim_id}",
            json={"pandas_password": attacker_password},
        )

        assert claim.status_code == 403
        assert takeover.status_code == 403

        victim = await _reload(db_session, victim_id)
        assert victim.sponsor_id != sponsor_user.id
        assert not verify_password(attacker_password, victim.password_hash)

        # The proof that matters: the attacker cannot authenticate as the victim.
        client.cookies.clear()
        login = await client.post(
            "/api/auth/login",
            json={"username": victim_email, "password": attacker_password},
        )
        assert login.status_code == 401

    @pytest.mark.asyncio
    async def test_sponsor_cannot_create_an_admin(
        self, authenticated_sponsor_client, db_session, admin_role
    ):
        """Create an invitee, then try to promote it to the Admin role.

        A fresh user has no EventParticipation rows, so the
        "no participation history" guard does not apply to it.
        """
        created = await authenticated_sponsor_client.post(
            "/api/admin/participants",
            json={
                "email": "escalation-target@test.com",
                "first_name": "Escalation",
                "last_name": "Target",
                "country": "USA",
                "role": UserRole.INVITEE.value,
            },
        )
        assert created.status_code in (200, 201)
        new_user_id = created.json()["id"]

        promote = await authenticated_sponsor_client.put(
            f"/api/admin/participants/{new_user_id}",
            json={"role_id": admin_role.id},
        )

        assert promote.status_code == 403
        promoted = await _reload(db_session, new_user_id)
        assert promoted.role != UserRole.ADMIN.value
        assert promoted.is_admin is False
        assert promoted.role_id != admin_role.id

        role = None
        if promoted.role_id:
            role = (
                await db_session.execute(select(Role).where(Role.id == promoted.role_id))
            ).scalar_one_or_none()
        granted = set(role.permissions or []) if role else set()
        assert "admin.manage_users" not in granted

    @pytest.mark.asyncio
    async def test_sponsor_cannot_enumerate_all_participants(
        self, authenticated_sponsor_client, admin_user, invitee_user
    ):
        """Reconnaissance step: finding the admin's id to target.

        docs/ROLES_AND_PERMISSIONS.md says `participants.view` sees only
        sponsored participants. The list endpoint returns everyone.
        """
        response = await authenticated_sponsor_client.get("/api/admin/participants")

        if response.status_code == 403:
            return

        assert response.status_code == 200
        returned_ids = {item["id"] for item in response.json()["items"]}
        assert admin_user.id not in returned_ids, (
            "sponsor can see participants they do not sponsor"
        )
