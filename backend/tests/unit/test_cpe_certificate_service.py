"""
Unit tests for CPECertificateService eligibility logic.

Covers the audit-log-based VPN check (added so eligibility survives a VPN
being unassigned after it was issued) and the 7-day soft-start window that
precedes event.start_date.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.event import Event, generate_slug
from app.models.user import User, UserRole
from app.models.vpn import VPNCredential
from app.services.cpe_certificate_service import CPECertificateService


# Event spans 2026-04-15 to 2026-04-17.
# Eligibility window: 2026-04-08 00:00 UTC (soft start) to 2026-04-18 00:00 UTC.
EVENT_START = date(2026, 4, 15)
EVENT_END = date(2026, 4, 17)

MID_EVENT = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
SOFT_START = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)  # 5 days before start
BEFORE_WINDOW = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)  # 8 days before start
AFTER_WINDOW = datetime(2026, 4, 19, 0, 0, tzinfo=timezone.utc)


async def _make_event(db_session: AsyncSession) -> Event:
    event = Event(
        year=2026,
        name="CyberX 2026",
        slug=generate_slug("CyberX 2026"),
        start_date=EVENT_START,
        end_date=EVENT_END,
        is_active=True,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event


async def _make_user(db_session: AsyncSession, email: str = "user@test.com") -> User:
    user = User(
        email=email,
        email_normalized=email.lower(),
        first_name="Test",
        last_name="User",
        country="USA",
        role=UserRole.INVITEE.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _log_vpn_assign(
    db_session: AsyncSession, target_user_id: int, at: datetime
) -> None:
    log = AuditLog(
        user_id=None,  # admin actor — irrelevant to the check
        action="VPN_ASSIGN",
        resource_type="VPN",
        resource_id=1,
        details={"assigned_to_user_id": target_user_id},
        created_at=at,
    )
    db_session.add(log)
    await db_session.commit()


async def _log_keycloak_login(
    db_session: AsyncSession, user_id: int, client_id: str, at: datetime
) -> None:
    log = AuditLog(
        user_id=user_id,
        action="KEYCLOAK_LOGIN",
        details={"client_id": client_id},
        created_at=at,
    )
    db_session.add(log)
    await db_session.commit()


@pytest.mark.unit
@pytest.mark.asyncio
class TestVpnAssignedCheck:
    """The VPN criterion queries AuditLog for VPN_ASSIGN within the window."""

    async def test_vpn_assigned_during_event_counts(self, db_session: AsyncSession):
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        await _log_vpn_assign(db_session, user.id, MID_EVENT)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["criteria"]["has_vpn_assigned"] is True

    async def test_vpn_assigned_during_soft_start_counts(self, db_session: AsyncSession):
        """VPN issued during the 7-day soft start should count."""
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        await _log_vpn_assign(db_session, user.id, SOFT_START)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["criteria"]["has_vpn_assigned"] is True

    async def test_vpn_assigned_before_soft_start_does_not_count(self, db_session: AsyncSession):
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        await _log_vpn_assign(db_session, user.id, BEFORE_WINDOW)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["criteria"]["has_vpn_assigned"] is False

    async def test_vpn_assigned_after_event_does_not_count(self, db_session: AsyncSession):
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        await _log_vpn_assign(db_session, user.id, AFTER_WINDOW)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["criteria"]["has_vpn_assigned"] is False

    async def test_vpn_unassigned_after_event_still_counts(self, db_session: AsyncSession):
        """Regression: audit log persists even when VPNCredential is unassigned.

        No live VPNCredential row exists for this user — only the VPN_ASSIGN
        audit log. Under the old state-based check this would return False.
        """
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        await _log_vpn_assign(db_session, user.id, MID_EVENT)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["criteria"]["has_vpn_assigned"] is True

    async def test_live_vpn_record_without_audit_log_does_not_count(self, db_session: AsyncSession):
        """Regression: a direct VPNCredential row without a VPN_ASSIGN log is ignored.

        Guards against reintroducing the old state-based check, which would
        credit a user purely because VPNCredential.assigned_to_user_id was set.
        """
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        vpn = VPNCredential(
            interface_ip="10.20.200.149",
            private_key="fake-private-key",
            endpoint="vpn.test:51820",
            key_type="cyber",
            assigned_to_user_id=user.id,
            is_available=False,
        )
        db_session.add(vpn)
        await db_session.commit()

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["criteria"]["has_vpn_assigned"] is False

    async def test_other_users_vpn_assignment_is_not_credited(self, db_session: AsyncSession):
        user = await _make_user(db_session, email="user@test.com")
        other = await _make_user(db_session, email="other@test.com")
        event = await _make_event(db_session)
        await _log_vpn_assign(db_session, other.id, MID_EVENT)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["criteria"]["has_vpn_assigned"] is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestEligibilityFullCriteria:
    """End-to-end eligibility checks covering the three-criterion AND."""

    async def test_all_three_criteria_met_is_eligible(self, db_session: AsyncSession):
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        await _log_keycloak_login(db_session, user.id, "nextcloud", MID_EVENT)
        await _log_keycloak_login(db_session, user.id, "powerdns-admin", MID_EVENT)
        await _log_vpn_assign(db_session, user.id, MID_EVENT)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["eligible"] is True
        assert result["cpe_hours"] > 0
        assert result["criteria"] == {
            "has_nextcloud_login": True,
            "has_powerdns_login": True,
            "has_vpn_assigned": True,
        }

    async def test_bug_scenario_vpn_missing_is_ineligible(self, db_session: AsyncSession):
        """The reported bug: Nextcloud+PowerDNS logged but VPN not credited."""
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        await _log_keycloak_login(db_session, user.id, "nextcloud", MID_EVENT)
        await _log_keycloak_login(db_session, user.id, "powerdns-admin", MID_EVENT)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["eligible"] is False
        assert result["cpe_hours"] == 0
        assert result["criteria"] == {
            "has_nextcloud_login": True,
            "has_powerdns_login": True,
            "has_vpn_assigned": False,
        }

    async def test_soft_start_activity_makes_user_eligible(self, db_session: AsyncSession):
        """All three criteria satisfied during the 7-day soft start should qualify."""
        user = await _make_user(db_session)
        event = await _make_event(db_session)
        await _log_keycloak_login(db_session, user.id, "nextcloud", SOFT_START)
        await _log_keycloak_login(db_session, user.id, "powerdns-admin", SOFT_START)
        await _log_vpn_assign(db_session, user.id, SOFT_START)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["eligible"] is True

    async def test_no_activity_is_ineligible(self, db_session: AsyncSession):
        user = await _make_user(db_session)
        event = await _make_event(db_session)

        result = await CPECertificateService(db_session).check_eligibility(user.id, event)
        assert result["eligible"] is False
        assert result["criteria"] == {
            "has_nextcloud_login": False,
            "has_powerdns_login": False,
            "has_vpn_assigned": False,
        }
