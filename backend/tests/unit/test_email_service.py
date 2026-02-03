"""
Unit tests for EmailService.

Tests email template management and helper functions.
Note: SendGrid API integration methods are not tested (require external API).
"""

import pytest
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.email_service import EmailService, build_event_template_vars
from app.models.email_template import EmailTemplate
from app.models.event import Event


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailServiceTemplates:
    """Test email template management."""

    async def test_create_template(self, db_session: AsyncSession):
        """Test creating an email template."""
        service = EmailService(db_session)

        template = await service.create_template(
            name="test_template",
            display_name="Test Template",
            subject="Test Subject",
            html_content="<p>Test content with {{variable}}</p>",
            text_content="Test content with {{variable}}",
            description="A test template"
        )

        assert template.id is not None
        assert template.name == "test_template"
        assert template.display_name == "Test Template"
        assert template.subject == "Test Subject"
        assert template.is_system is False

    async def test_get_template_by_id(self, db_session: AsyncSession):
        """Test retrieving template by ID."""
        service = EmailService(db_session)

        # Create template
        created = await service.create_template(
            name="test",
            display_name="Test",
            subject="Subject",
            html_content="<p>Content</p>"
        )

        # Retrieve by ID
        retrieved = await service.get_template_by_id(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "test"

    async def test_get_nonexistent_template_by_id(self, db_session: AsyncSession):
        """Test retrieving non-existent template returns None."""
        service = EmailService(db_session)

        template = await service.get_template_by_id(99999)

        assert template is None

    async def test_get_template_by_name(self, db_session: AsyncSession):
        """Test retrieving template by name."""
        service = EmailService(db_session)

        # Create template
        await service.create_template(
            name="welcome_email",
            display_name="Welcome",
            subject="Welcome!",
            html_content="<p>Welcome!</p>"
        )

        # Retrieve by name
        retrieved = await service.get_template_by_name("welcome_email")

        assert retrieved is not None
        assert retrieved.name == "welcome_email"

    async def test_get_nonexistent_template_by_name(self, db_session: AsyncSession):
        """Test retrieving non-existent template by name returns None."""
        service = EmailService(db_session)

        template = await service.get_template_by_name("nonexistent")

        assert template is None

    async def test_get_templates_active_only(self, db_session: AsyncSession):
        """Test listing only active templates."""
        service = EmailService(db_session)

        # Create active template
        active = await service.create_template(
            name="active",
            display_name="Active",
            subject="Active",
            html_content="<p>Active</p>"
        )

        # Create inactive template
        inactive = EmailTemplate(
            name="inactive",
            display_name="Inactive",
            subject="Inactive",
            html_content="<p>Inactive</p>",
            is_active=False
        )
        db_session.add(inactive)
        await db_session.commit()

        # Get active only (default)
        templates = await service.get_templates(active_only=True)

        assert len(templates) == 1
        assert templates[0].name == "active"

    async def test_get_templates_all(self, db_session: AsyncSession):
        """Test listing all templates including inactive."""
        service = EmailService(db_session)

        # Create active template
        await service.create_template(
            name="active",
            display_name="Active",
            subject="Active",
            html_content="<p>Active</p>"
        )

        # Create inactive template
        inactive = EmailTemplate(
            name="inactive",
            display_name="Inactive",
            subject="Inactive",
            html_content="<p>Inactive</p>",
            is_active=False
        )
        db_session.add(inactive)
        await db_session.commit()

        # Get all templates
        templates = await service.get_templates(active_only=False)

        assert len(templates) == 2
        names = [t.name for t in templates]
        assert "active" in names
        assert "inactive" in names

    async def test_update_template(self, db_session: AsyncSession):
        """Test updating a template."""
        service = EmailService(db_session)

        # Create template
        template = await service.create_template(
            name="test",
            display_name="Original",
            subject="Original Subject",
            html_content="<p>Original</p>"
        )

        # Update template
        updated = await service.update_template(
            template.id,
            display_name="Updated",
            subject="Updated Subject",
            html_content="<p>Updated</p>"
        )

        assert updated is not None
        assert updated.display_name == "Updated"
        assert updated.subject == "Updated Subject"
        assert updated.html_content == "<p>Updated</p>"

    async def test_update_nonexistent_template(self, db_session: AsyncSession):
        """Test updating non-existent template returns None."""
        service = EmailService(db_session)

        result = await service.update_template(99999, subject="New")

        assert result is None

    async def test_delete_template(self, db_session: AsyncSession):
        """Test deleting a template."""
        service = EmailService(db_session)

        # Create template
        template = await service.create_template(
            name="to_delete",
            display_name="To Delete",
            subject="Delete Me",
            html_content="<p>Delete</p>"
        )

        # Delete it
        success, message = await service.delete_template(template.id)

        assert success is True
        assert "successfully" in message.lower()

        # Verify deleted
        deleted = await service.get_template_by_id(template.id)
        assert deleted is None

    async def test_delete_system_template_blocked(self, db_session: AsyncSession):
        """Test deleting system template is blocked."""
        service = EmailService(db_session)

        # Create system template
        template = EmailTemplate(
            name="system_template",
            display_name="System",
            subject="System",
            html_content="<p>System</p>",
            is_system=True
        )
        db_session.add(template)
        await db_session.commit()
        await db_session.refresh(template)

        # Attempt to delete
        success, message = await service.delete_template(template.id)

        assert success is False
        assert "system" in message.lower()

        # Verify still exists
        exists = await service.get_template_by_id(template.id)
        assert exists is not None


@pytest.mark.unit
class TestBuildEventTemplateVars:
    """Test event template variable building."""

    def test_build_event_vars_single_day(self):
        """Test building vars for single-day event."""
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 15),
            event_time="9:00 AM - 5:00 PM",
            event_location="Austin, TX"
        )

        vars = build_event_template_vars(event)

        assert vars["event_name"] == "CyberX 2026"
        assert vars["event_date_range"] == "Jun 15, 2026"
        assert vars["event_time"] == "9:00 AM - 5:00 PM"
        assert vars["event_location"] == "Austin, TX"

    def test_build_event_vars_multi_day_same_month(self):
        """Test building vars for multi-day event in same month."""
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7)
        )

        vars = build_event_template_vars(event)

        assert vars["event_date_range"] == "Jun 01 — 07, 2026"

    def test_build_event_vars_multi_day_different_months(self):
        """Test building vars for multi-day event across months."""
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 5, 30),
            end_date=date(2026, 6, 5)
        )

        vars = build_event_template_vars(event)

        assert vars["event_date_range"] == "May 30 — Jun 05, 2026"

    def test_build_event_vars_no_dates(self):
        """Test building vars when dates are not set."""
        event = Event(
            year=2026,
            name="CyberX 2026"
        )

        vars = build_event_template_vars(event)

        assert vars["event_date_range"] == "TBA"

    def test_build_event_vars_default_time_location(self):
        """Test default values for time and location."""
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7)
        )

        vars = build_event_template_vars(event)

        assert vars["event_time"] == "Doors open 18:00 UTC"
        assert vars["event_location"] == "Austin, TX"
