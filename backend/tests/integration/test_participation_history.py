"""GET /api/events/my/history: the participant portal's "Past Events" source.

The route used to read participation totals from the session-loaded user,
whose event_participations relationship is not eager-loaded, so every call
500'd with MissingGreenlet in production.
"""
from datetime import datetime, timezone

import pytest

from app.models.event import Event, EventParticipation, ParticipationStatus, generate_slug


pytestmark = [pytest.mark.integration]


async def _event(db_session, year: int, *, archived: bool) -> Event:
    event = Event(
        name=f"CyberX {year}",
        slug=generate_slug(f"CyberX {year}"),
        year=year,
        is_active=not archived,
        is_archived=archived,
        archived_at=datetime.now(timezone.utc) if archived else None,
    )
    db_session.add(event)
    await db_session.commit()
    return event


async def _participation(db_session, user, event, status: ParticipationStatus):
    db_session.add(EventParticipation(user_id=user.id, event_id=event.id, status=status.value))
    await db_session.commit()


async def test_history_with_archived_events(db_session, authenticated_invitee_client, invitee_user):
    older = await _event(db_session, 2024, archived=True)
    newer = await _event(db_session, 2025, archived=True)
    await _participation(db_session, invitee_user, older, ParticipationStatus.DECLINED)
    await _participation(db_session, invitee_user, newer, ParticipationStatus.CONFIRMED)

    resp = await authenticated_invitee_client.get("/api/events/my/history")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == invitee_user.id
    assert body["total_years_invited"] == 2
    assert body["total_years_participated"] == 1
    assert body["participation_rate"] == 50.0
    assert body["is_chronic_non_participant"] is False
    assert body["should_recommend_removal"] is False
    assert [(h["event_year"], h["status"]) for h in body["history"]] == [
        (2025, "confirmed"),
        (2024, "declined"),
    ]


async def test_history_flags_chronic_non_participant(db_session, authenticated_invitee_client, invitee_user):
    for year in (2022, 2023, 2024):
        event = await _event(db_session, year, archived=True)
        await _participation(db_session, invitee_user, event, ParticipationStatus.NO_RESPONSE)

    resp = await authenticated_invitee_client.get("/api/events/my/history")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_years_invited"] == 3
    assert body["total_years_participated"] == 0
    assert body["participation_rate"] == 0.0
    assert body["is_chronic_non_participant"] is True
    assert body["should_recommend_removal"] is True


async def test_history_empty(authenticated_invitee_client, invitee_user):
    resp = await authenticated_invitee_client.get("/api/events/my/history")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["history"] == []
    assert body["total_years_invited"] == 0
    assert body["participation_rate"] == 0.0


async def test_history_only_returns_own_rows(
    db_session, authenticated_invitee_client, invitee_user, sponsor_user
):
    event = await _event(db_session, 2025, archived=True)
    await _participation(db_session, sponsor_user, event, ParticipationStatus.CONFIRMED)

    resp = await authenticated_invitee_client.get("/api/events/my/history")

    assert resp.status_code == 200, resp.text
    assert resp.json()["history"] == []


async def test_history_requires_login(client):
    resp = await client.get("/api/events/my/history")
    assert resp.status_code == 401
