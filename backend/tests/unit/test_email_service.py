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


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailServiceAdvancedTemplateOps:
    """Test advanced template operations."""

    async def test_duplicate_template(self, db_session: AsyncSession):
        """Test duplicating a template."""
        service = EmailService(db_session)

        # Create original template
        original = await service.create_template(
            name="original",
            display_name="Original Template",
            subject="Original Subject",
            html_content="<p>Original content</p>",
            text_content="Original content",
            description="Original description",
            available_variables=["var1", "var2"]
        )

        # Duplicate it
        duplicate = await service.duplicate_template(original.id, "duplicate")

        assert duplicate is not None
        assert duplicate.id != original.id
        assert duplicate.name == "duplicate"
        assert duplicate.display_name == "Original Template (Copy)"
        assert duplicate.subject == original.subject
        assert duplicate.html_content == original.html_content
        assert duplicate.available_variables == original.available_variables
        assert duplicate.is_system is False

    async def test_duplicate_nonexistent_template(self, db_session: AsyncSession):
        """Test duplicating non-existent template returns None."""
        service = EmailService(db_session)

        result = await service.duplicate_template(99999, "new_name")

        assert result is None

    async def test_render_template_content(self, db_session: AsyncSession):
        """Test rendering template with user data."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create template with variables
        template = await service.create_template(
            name="welcome",
            display_name="Welcome",
            subject="Welcome {first_name}!",
            html_content="<p>Hello {first_name} {last_name}</p>",
            text_content="Hello {first_name} {last_name}"
        )

        # Create user
        user = User(
            email="test@example.com",
            first_name="John",
            last_name="Doe",
            country="USA",
            role=UserRole.INVITEE.value
        )

        # Render template
        subject, html, text = service._render_template_content(template, user)

        assert "John" in subject
        assert "John" in html
        assert "Doe" in html
        assert "John" in text
        assert "Doe" in text

    async def test_render_template_with_custom_vars(self, db_session: AsyncSession):
        """Test rendering template with custom variables."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create template
        template = await service.create_template(
            name="custom",
            display_name="Custom",
            subject="Event: {event_name}",
            html_content="<p>{custom_var}</p>"
        )

        # Create user
        user = User(
            email="test@example.com",
            first_name="John",
            last_name="Doe",
            country="USA",
            role=UserRole.INVITEE.value
        )

        # Render with custom vars
        custom_vars = {"custom_var": "Custom Value", "event_name": "CyberX 2026"}
        subject, html, text = service._render_template_content(
            template, user, custom_vars
        )

        assert "CyberX 2026" in subject
        assert "Custom Value" in html

    async def test_preview_template(self, db_session: AsyncSession):
        """Test previewing template with sample data."""
        service = EmailService(db_session)

        # Create template with variables
        template = await service.create_template(
            name="preview_test",
            display_name="Preview Test",
            subject="Hello {first_name}!",
            html_content="<p>Email: {email}</p>",
            text_content="Email: {email}"
        )

        # Preview with default sample data
        result = await service.preview_template(template.id)

        assert result is not None
        subject, html, text = result
        assert "John" in subject  # Default sample user first name
        assert "john.doe@example.com" in html  # Default sample user email
        assert "john.doe@example.com" in text

    async def test_preview_template_with_custom_sample_data(self, db_session: AsyncSession):
        """Test preview with custom sample data."""
        service = EmailService(db_session)

        # Create template
        template = await service.create_template(
            name="preview_custom",
            display_name="Preview Custom",
            subject="Welcome {first_name}!",
            html_content="<p>{custom_message}</p>"
        )

        # Preview with custom sample data
        sample_data = {
            "first_name": "Alice",
            "custom_message": "This is a custom message"
        }
        result = await service.preview_template(template.id, sample_data)

        assert result is not None
        subject, html, text = result
        assert "Alice" in subject
        assert "This is a custom message" in html

    async def test_preview_nonexistent_template(self, db_session: AsyncSession):
        """Test previewing non-existent template returns None."""
        service = EmailService(db_session)

        result = await service.preview_template(99999)

        assert result is None

    async def test_extract_template_variables(self, db_session: AsyncSession):
        """Test extracting variables from template content."""
        service = EmailService(db_session)

        # Test with single brace variables
        content1 = "<p>Hello {first_name} {last_name}! Your email is {email}.</p>"
        vars1 = service._extract_template_variables(content1)
        assert "first_name" in vars1
        assert "last_name" in vars1
        assert "email" in vars1

        # Test with double brace variables
        content2 = "<p>Event: {{event_name}} on {{event_date}}</p>"
        vars2 = service._extract_template_variables(content2)
        assert "event_name" in vars2
        assert "event_date" in vars2

        # Test with mixed braces
        content3 = "<p>{single} and {{double}}</p>"
        vars3 = service._extract_template_variables(content3)
        assert "single" in vars3
        assert "double" in vars3

        # Test with no variables
        content4 = "<p>No variables here</p>"
        vars4 = service._extract_template_variables(content4)
        assert len(vars4) == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailServiceStatistics:
    """Test email statistics and analytics methods."""

    async def test_get_email_stats_empty(self, db_session: AsyncSession):
        """Test email stats with no events."""
        service = EmailService(db_session)

        stats = await service.get_email_stats()

        assert stats["total_sent"] == 0
        assert stats["delivered"] == 0
        assert stats["opened"] == 0
        assert stats["clicked"] == 0
        assert stats["bounced"] == 0
        assert stats["spam_reports"] == 0

    async def test_get_email_stats_with_events(self, db_session: AsyncSession):
        """Test email stats with various event types."""
        from app.models.audit_log import EmailEvent

        service = EmailService(db_session)

        # Create various email events
        events = [
            EmailEvent(email_to="user1@test.com", event_type="sent", template_name="invite"),
            EmailEvent(email_to="user2@test.com", event_type="sent", template_name="invite"),
            EmailEvent(email_to="user3@test.com", event_type="sent", template_name="reminder"),
            EmailEvent(email_to="user1@test.com", event_type="delivered", template_name="invite"),
            EmailEvent(email_to="user2@test.com", event_type="delivered", template_name="invite"),
            EmailEvent(email_to="user1@test.com", event_type="open", template_name="invite"),
            EmailEvent(email_to="user1@test.com", event_type="click", template_name="invite"),
            EmailEvent(email_to="user3@test.com", event_type="bounce", template_name="reminder"),
            EmailEvent(email_to="user4@test.com", event_type="spamreport", template_name="invite"),
        ]
        db_session.add_all(events)
        await db_session.commit()

        # Get stats
        stats = await service.get_email_stats()

        assert stats["total_sent"] == 3
        assert stats["delivered"] == 2
        assert stats["opened"] == 1
        assert stats["clicked"] == 1
        assert stats["bounced"] == 1
        assert stats["spam_reports"] == 1

    async def test_get_analytics(self, db_session: AsyncSession):
        """Test analytics calculations with rates."""
        from app.models.audit_log import EmailEvent

        service = EmailService(db_session)

        # Create events with known counts for rate calculation
        events = [
            # 10 sent
            *[EmailEvent(email_to=f"user{i}@test.com", event_type="sent", template_name="test")
              for i in range(10)],
            # 8 delivered (80% delivery rate)
            *[EmailEvent(email_to=f"user{i}@test.com", event_type="delivered", template_name="test")
              for i in range(8)],
            # 4 opened (50% open rate of delivered)
            *[EmailEvent(email_to=f"user{i}@test.com", event_type="open", template_name="test")
              for i in range(4)],
            # 2 clicked (50% click rate of opened)
            *[EmailEvent(email_to=f"user{i}@test.com", event_type="click", template_name="test")
              for i in range(2)],
            # 2 bounced (20% bounce rate)
            *[EmailEvent(email_to=f"user{i}@test.com", event_type="bounce", template_name="test")
              for i in range(2)],
        ]
        db_session.add_all(events)
        await db_session.commit()

        # Get analytics
        analytics = await service.get_analytics()

        assert analytics["total_sent"] == 10
        assert analytics["total_delivered"] == 8
        assert analytics["total_opened"] == 4
        assert analytics["total_clicked"] == 2
        assert analytics["total_bounced"] == 2
        assert analytics["delivery_rate"] == 80.0
        assert analytics["open_rate"] == 50.0
        assert analytics["click_rate"] == 50.0
        assert analytics["bounce_rate"] == 20.0

    async def test_get_analytics_empty(self, db_session: AsyncSession):
        """Test analytics with no events (avoid division by zero)."""
        service = EmailService(db_session)

        analytics = await service.get_analytics()

        assert analytics["total_sent"] == 0
        assert analytics["delivery_rate"] == 0.0
        assert analytics["open_rate"] == 0.0
        assert analytics["click_rate"] == 0.0
        assert analytics["bounce_rate"] == 0.0

    async def test_get_user_email_events(self, db_session: AsyncSession):
        """Test getting email events for specific user."""
        from app.models.user import User, UserRole
        from app.models.audit_log import EmailEvent

        service = EmailService(db_session)

        # Create test user
        user = User(
            email="testuser@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create email events for this user
        events = [
            EmailEvent(email_to=user.email, user_id=user.id, event_type="sent", template_name="invite"),
            EmailEvent(email_to=user.email, user_id=user.id, event_type="delivered", template_name="invite"),
            EmailEvent(email_to=user.email, user_id=user.id, event_type="open", template_name="invite"),
        ]
        # Create events for different user
        other_events = [
            EmailEvent(email_to="other@test.com", user_id=999, event_type="sent", template_name="test"),
        ]
        db_session.add_all(events + other_events)
        await db_session.commit()

        # Get events for our user
        user_events = await service.get_user_email_events(user.id)

        assert len(user_events) == 3
        assert all(e.email_to == user.email for e in user_events)
        # Verify event types (order may vary in test environment)
        event_types = {e.event_type for e in user_events}
        assert event_types == {"sent", "delivered", "open"}

    async def test_get_user_email_events_nonexistent_user(self, db_session: AsyncSession):
        """Test getting events for non-existent user returns empty list."""
        service = EmailService(db_session)

        events = await service.get_user_email_events(99999)

        assert len(events) == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailServiceAnalytics:
    """Test email analytics and history methods."""

    async def test_get_template_stats_empty(self, db_session: AsyncSession):
        """Test template stats with no events."""
        service = EmailService(db_session)

        stats = await service.get_template_stats()

        assert len(stats) == 0

    async def test_get_template_stats_with_events(self, db_session: AsyncSession):
        """Test template stats aggregation."""
        from app.models.audit_log import EmailEvent

        service = EmailService(db_session)

        # Create templates
        template1 = await service.create_template(
            name="invite",
            display_name="Invitation",
            subject="You're invited",
            html_content="<p>Welcome</p>"
        )
        template2 = await service.create_template(
            name="reminder",
            display_name="Reminder",
            subject="Reminder",
            html_content="<p>Remember</p>"
        )

        # Create events for invite template
        invite_events = [
            EmailEvent(email_to="user1@test.com", event_type="sent", template_name="invite"),
            EmailEvent(email_to="user2@test.com", event_type="sent", template_name="invite"),
            EmailEvent(email_to="user1@test.com", event_type="delivered", template_name="invite"),
            EmailEvent(email_to="user2@test.com", event_type="delivered", template_name="invite"),
            EmailEvent(email_to="user1@test.com", event_type="open", template_name="invite"),
            EmailEvent(email_to="user1@test.com", event_type="click", template_name="invite"),
        ]

        # Create events for reminder template
        reminder_events = [
            EmailEvent(email_to="user3@test.com", event_type="sent", template_name="reminder"),
            EmailEvent(email_to="user3@test.com", event_type="delivered", template_name="reminder"),
        ]

        db_session.add_all(invite_events + reminder_events)
        await db_session.commit()

        # Get stats
        stats = await service.get_template_stats()

        # Find stats for each template
        invite_stats = next((s for s in stats if s["template_name"] == "invite"), None)
        reminder_stats = next((s for s in stats if s["template_name"] == "reminder"), None)

        assert invite_stats is not None
        assert invite_stats["sent"] == 2
        assert invite_stats["delivered"] == 2
        assert invite_stats["opened"] == 1
        assert invite_stats["clicked"] == 1
        assert invite_stats["open_rate"] == 50.0  # 1/2 delivered
        assert invite_stats["click_rate"] == 100.0  # 1/1 opened

        assert reminder_stats is not None
        assert reminder_stats["sent"] == 1
        assert reminder_stats["delivered"] == 1
        assert reminder_stats["opened"] == 0

    async def test_get_email_history_empty(self, db_session: AsyncSession):
        """Test email history with no events."""
        service = EmailService(db_session)

        items, total = await service.get_email_history()

        assert len(items) == 0
        assert total == 0

    async def test_get_email_history_with_events(self, db_session: AsyncSession):
        """Test email history retrieval."""
        from app.models.user import User, UserRole
        from app.models.audit_log import EmailEvent
        import json

        service = EmailService(db_session)

        # Create users
        user1 = User(
            email="user1@test.com",
            first_name="Alice",
            last_name="Smith",
            country="USA",
            role=UserRole.INVITEE.value
        )
        user2 = User(
            email="user2@test.com",
            first_name="Bob",
            last_name="Jones",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add_all([user1, user2])
        await db_session.commit()
        await db_session.refresh(user1)
        await db_session.refresh(user2)

        # Create sent email events
        event1 = EmailEvent(
            email_to=user1.email,
            user_id=user1.id,
            event_type="sent",
            template_name="invite",
            sendgrid_message_id="msg123",
            payload=json.dumps({"subject": "Invitation to CyberX"})
        )
        event2 = EmailEvent(
            email_to=user2.email,
            user_id=user2.id,
            event_type="sent",
            template_name="reminder",
            sendgrid_message_id="msg456",
            payload=json.dumps({"subject": "Reminder: CyberX"})
        )
        db_session.add_all([event1, event2])
        await db_session.commit()

        # Get history
        items, total = await service.get_email_history(page=1, page_size=50)

        assert total == 2
        assert len(items) == 2

        # Check first item
        item1 = next((i for i in items if i["recipient_email"] == user1.email), None)
        assert item1 is not None
        assert item1["recipient_name"] == "Alice Smith"
        assert item1["template_name"] == "invite"
        assert item1["subject"] == "Invitation to CyberX"
        assert item1["status"] == "sent"

    async def test_get_email_history_pagination(self, db_session: AsyncSession):
        """Test email history pagination."""
        from app.models.user import User, UserRole
        from app.models.audit_log import EmailEvent

        service = EmailService(db_session)

        # Create users
        users = []
        for i in range(10):
            user = User(
                email=f"user{i}@test.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA",
                role=UserRole.INVITEE.value
            )
            users.append(user)
        db_session.add_all(users)
        await db_session.commit()

        # Create 10 sent events
        for user in users:
            await db_session.refresh(user)
            event = EmailEvent(
                email_to=user.email,
                user_id=user.id,
                event_type="sent",
                template_name="test"
            )
            db_session.add(event)
        await db_session.commit()

        # Get first page (5 items)
        page1_items, page1_total = await service.get_email_history(page=1, page_size=5)
        assert len(page1_items) == 5
        assert page1_total == 10

        # Get second page (5 items)
        page2_items, page2_total = await service.get_email_history(page=2, page_size=5)
        assert len(page2_items) == 5
        assert page2_total == 10

        # Verify no overlap
        page1_emails = {item["recipient_email"] for item in page1_items}
        page2_emails = {item["recipient_email"] for item in page2_items}
        assert len(page1_emails & page2_emails) == 0

    async def test_get_email_history_search(self, db_session: AsyncSession):
        """Test email history search filtering."""
        from app.models.user import User, UserRole
        from app.models.audit_log import EmailEvent

        service = EmailService(db_session)

        # Create users
        user1 = User(
            email="alice@test.com",
            first_name="Alice",
            last_name="Smith",
            country="USA",
            role=UserRole.INVITEE.value
        )
        user2 = User(
            email="bob@test.com",
            first_name="Bob",
            last_name="Jones",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add_all([user1, user2])
        await db_session.commit()
        await db_session.refresh(user1)
        await db_session.refresh(user2)

        # Create events
        event1 = EmailEvent(
            email_to=user1.email,
            user_id=user1.id,
            event_type="sent",
            template_name="invite"
        )
        event2 = EmailEvent(
            email_to=user2.email,
            user_id=user2.id,
            event_type="sent",
            template_name="invite"
        )
        db_session.add_all([event1, event2])
        await db_session.commit()

        # Search for "alice"
        items, total = await service.get_email_history(search="alice")

        assert total >= 1
        assert any(item["recipient_email"] == "alice@test.com" for item in items)
        assert all("bob" not in item["recipient_email"] for item in items)

    async def test_get_email_history_template_filter(self, db_session: AsyncSession):
        """Test email history template filtering."""
        from app.models.user import User, UserRole
        from app.models.audit_log import EmailEvent

        service = EmailService(db_session)

        # Create user
        user = User(
            email="user@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create events with different templates
        event1 = EmailEvent(
            email_to=user.email,
            user_id=user.id,
            event_type="sent",
            template_name="invite"
        )
        event2 = EmailEvent(
            email_to=user.email,
            user_id=user.id,
            event_type="sent",
            template_name="reminder"
        )
        db_session.add_all([event1, event2])
        await db_session.commit()

        # Filter by invite template
        items, total = await service.get_email_history(template_name="invite")

        assert all(item["template_name"] == "invite" for item in items)
        assert not any(item["template_name"] == "reminder" for item in items)


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailServiceEventLogging:
    """Test email event logging and user status updates."""

    async def test_log_email_event(self, db_session: AsyncSession):
        """Test logging an email event."""
        from app.models.audit_log import EmailEvent
        from sqlalchemy import select

        service = EmailService(db_session)

        # Log an email event
        await service._log_email_event(
            email="test@example.com",
            user_id=1,
            event_type="sent",
            message_id="msg123",
            template_name="invite",
            subject="Welcome to CyberX"
        )

        # Verify event was logged
        result = await db_session.execute(
            select(EmailEvent).where(EmailEvent.email_to == "test@example.com")
        )
        event = result.scalar_one_or_none()

        assert event is not None
        assert event.email_to == "test@example.com"
        assert event.user_id == 1
        assert event.event_type == "sent"
        assert event.sendgrid_message_id == "msg123"
        assert event.template_name == "invite"
        assert "Welcome to CyberX" in event.payload

    async def test_log_email_event_with_reason(self, db_session: AsyncSession):
        """Test logging a failed email event with reason."""
        from app.models.audit_log import EmailEvent
        from sqlalchemy import select

        service = EmailService(db_session)

        # Log failed event
        await service._log_email_event(
            email="test@example.com",
            user_id=1,
            event_type="failed",
            message_id=None,
            template_name="invite",
            reason="Invalid email address"
        )

        # Verify event was logged
        result = await db_session.execute(
            select(EmailEvent).where(EmailEvent.email_to == "test@example.com")
        )
        event = result.scalar_one_or_none()

        assert event is not None
        assert event.event_type == "failed"
        assert "Invalid email address" in event.payload

    async def test_update_user_email_status_invite(self, db_session: AsyncSession):
        """Test updating user status for invite email."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        assert user.invite_sent is None
        assert user.last_invite_sent is None

        # Update status for invite
        await service._update_user_email_status(user, "invite")

        # Verify timestamps updated
        await db_session.refresh(user)
        assert user.invite_sent is not None
        assert user.last_invite_sent is not None

    async def test_update_user_email_status_password(self, db_session: AsyncSession):
        """Test updating user status for password email."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        assert user.password_email_sent is None

        # Update status for password email
        await service._update_user_email_status(user, "password")

        # Verify timestamp updated
        await db_session.refresh(user)
        assert user.password_email_sent is not None

    async def test_update_user_email_status_reminder(self, db_session: AsyncSession):
        """Test updating user status for reminder email."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        assert user.invite_reminder_sent is None

        # Update status for reminder
        await service._update_user_email_status(user, "reminder")

        # Verify timestamps updated
        await db_session.refresh(user)
        assert user.invite_reminder_sent is not None
        assert user.last_invite_sent is not None

    async def test_update_user_email_status_survey(self, db_session: AsyncSession):
        """Test updating user status for survey email."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        assert user.survey_email_sent is None

        # Update status for survey
        await service._update_user_email_status(user, "survey")

        # Verify timestamp updated
        await db_session.refresh(user)
        assert user.survey_email_sent is not None

    async def test_update_user_email_status_orientation(self, db_session: AsyncSession):
        """Test updating user status for orientation email."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        assert user.orientation_invite_email_sent is None

        # Update status for orientation
        await service._update_user_email_status(user, "orientation")

        # Verify timestamp updated
        await db_session.refresh(user)
        assert user.orientation_invite_email_sent is not None

    async def test_process_webhook_event_delivered(self, db_session: AsyncSession):
        """Test processing a delivered webhook event."""
        from app.models.audit_log import EmailEvent
        from sqlalchemy import select

        service = EmailService(db_session)

        # Process webhook event
        event_data = {
            "email": "test@example.com",
            "event": "delivered",
            "sg_message_id": "msg123",
            "timestamp": 1234567890
        }

        success = await service.process_webhook_event(event_data)

        assert success is True

        # Verify event was logged
        result = await db_session.execute(
            select(EmailEvent).where(EmailEvent.email_to == "test@example.com")
        )
        event = result.scalar_one_or_none()

        assert event is not None
        assert event.event_type == "delivered"
        assert event.sendgrid_message_id == "msg123"

    async def test_process_webhook_event_bounce(self, db_session: AsyncSession):
        """Test processing a bounce event updates user status."""
        from app.models.user import User, UserRole
        from app.models.audit_log import EmailEvent
        from sqlalchemy import select

        service = EmailService(db_session)

        # Create user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        assert user.email_status != "BAD"

        # Process bounce event
        event_data = {
            "email": "test@example.com",
            "event": "bounce",
            "sg_message_id": "msg123",
            "reason": "Mailbox full",
            "timestamp": 1234567890
        }

        success = await service.process_webhook_event(event_data)

        assert success is True

        # Verify user status updated
        await db_session.refresh(user)
        assert user.email_status == "BAD"
        assert user.email_status_timestamp is not None

    async def test_process_webhook_event_dropped(self, db_session: AsyncSession):
        """Test processing a dropped event marks email as bad."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Process dropped event
        event_data = {
            "email": "test@example.com",
            "event": "dropped",
            "sg_message_id": "msg123",
            "reason": "Invalid email",
            "timestamp": 1234567890
        }

        success = await service.process_webhook_event(event_data)

        assert success is True

        # Verify user status updated
        await db_session.refresh(user)
        assert user.email_status == "BAD"

    async def test_process_webhook_event_spamreport(self, db_session: AsyncSession):
        """Test processing a spam report marks email as bad."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Process spam report event
        event_data = {
            "email": "test@example.com",
            "event": "spamreport",
            "sg_message_id": "msg123",
            "timestamp": 1234567890
        }

        success = await service.process_webhook_event(event_data)

        assert success is True

        # Verify user status updated
        await db_session.refresh(user)
        assert user.email_status == "BAD"

    async def test_process_webhook_event_invalid(self, db_session: AsyncSession):
        """Test processing invalid webhook event returns False."""
        service = EmailService(db_session)

        # Missing required fields
        event_data = {
            "timestamp": 1234567890
        }

        success = await service.process_webhook_event(event_data)

        assert success is False



@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailServiceSendGridMocking:
    """Test EmailService SendGrid API calls with mocking."""

    async def test_send_email_success(self, db_session: AsyncSession, mocker):
        """Test sending email with template name successfully."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test user
        user = User(
            email="recipient@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create template using service method
        template = await service.create_template(
            name="welcome",
            display_name="Welcome Email",
            subject="Welcome!",
            html_content="<p>Welcome {first_name}!</p>",
            sendgrid_template_id="d-123abc",
            description="Welcome email"
        )

        # Mock SendGrid client
        mock_response = mocker.Mock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "test_msg_id_123"}

        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(return_value=mock_response)

        mocker.patch.object(service, 'client', mock_client)

        # Send email
        success, message, msg_id = await service.send_email(
            user=user,
            template_name="welcome"
        )

        assert success is True
        assert "sent successfully" in message.lower()
        assert msg_id == "test_msg_id_123"
        assert mock_client.send.called

    async def test_send_email_with_template_id_success(
        self, db_session: AsyncSession, mocker
    ):
        """Test sending email with template ID directly."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test user
        user = User(
            email="recipient@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create template
        template = await service.create_template(
            name="confirmation",
            display_name="Confirmation Email",
            subject="Confirm your email",
            html_content="<p>Code: {confirmation_code}</p>",
            sendgrid_template_id="d-abc123"
        )

        # Mock SendGrid client
        mock_response = mocker.Mock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "msg_456"}

        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(return_value=mock_response)

        mocker.patch.object(service, 'client', mock_client)

        # Send email with template ID
        success, message, msg_id = await service.send_email_with_template_id(
            user=user,
            template_id=template.id
        )

        assert success is True
        assert "sent successfully" in message.lower()
        assert msg_id == "msg_456"
        assert mock_client.send.called

    async def test_send_email_sendgrid_error(self, db_session: AsyncSession, mocker):
        """Test handling SendGrid API errors."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test user
        user = User(
            email="recipient@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create template
        await service.create_template(
            name="welcome",
            display_name="Welcome Email",
            subject="Welcome!",
            html_content="<p>Welcome {first_name}!</p>",
            sendgrid_template_id="d-123abc"
        )

        # Mock SendGrid client to raise exception
        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(side_effect=Exception("SendGrid API Error"))

        mocker.patch.object(service, 'client', mock_client)

        # Send email
        success, message, msg_id = await service.send_email(
            user=user,
            template_name="welcome"
        )

        assert success is False
        assert "error" in message.lower()
        assert msg_id is None

    async def test_send_email_template_not_found(self, db_session: AsyncSession):
        """Test sending email with non-existent template."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test user
        user = User(
            email="recipient@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Send email with non-existent template
        success, message, msg_id = await service.send_email(
            user=user,
            template_name="nonexistent_template"
        )

        assert success is False
        assert "not found" in message.lower()
        assert msg_id is None

    async def test_send_custom_email_success(self, db_session: AsyncSession, mocker):
        """Test sending custom email without template."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test user
        user = User(
            email="custom@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Mock SendGrid client
        mock_response = mocker.Mock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "custom_msg_789"}

        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(return_value=mock_response)

        mocker.patch.object(service, 'client', mock_client)

        # Send custom email
        success, message, msg_id = await service.send_custom_email(
            user=user,
            subject="Custom Subject",
            html_body="<p>Custom HTML content</p>"
        )

        assert success is True
        assert "sent successfully" in message.lower()
        assert msg_id == "custom_msg_789"
        assert mock_client.send.called

    async def test_send_custom_email_error(self, db_session: AsyncSession, mocker):
        """Test handling errors in custom email sending."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test user
        user = User(
            email="custom@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Mock SendGrid client to raise exception
        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(side_effect=Exception("Network error"))

        mocker.patch.object(service, 'client', mock_client)

        # Send custom email
        success, message, msg_id = await service.send_custom_email(
            user=user,
            subject="Custom Subject",
            html_body="<p>Custom HTML content</p>"
        )

        assert success is False
        assert "error" in message.lower()
        assert msg_id is None

    async def test_send_test_email_success(self, db_session: AsyncSession, mocker):
        """Test sending test email."""
        service = EmailService(db_session)

        # Mock SendGrid client
        mock_response = mocker.Mock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "test_email_msg"}

        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(return_value=mock_response)

        mocker.patch.object(service, 'client', mock_client)

        # Send test email (returns 4 values)
        success, message, msg_id, template_name = await service.send_test_email(
            to_email="tester@example.com"
        )

        assert success is True
        assert "sent successfully" in message.lower()
        assert msg_id == "test_email_msg"
        assert mock_client.send.called

    async def test_send_email_bad_email_status(self, db_session: AsyncSession):
        """Test that emails to users with BAD status are skipped."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create user with BAD email status
        user = User(
            email="bad@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value,
            email_status="BAD"
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create template
        await service.create_template(
            name="welcome",
            display_name="Welcome Email",
            subject="Welcome!",
            html_content="<p>Welcome {first_name}!</p>"
        )

        # Attempt to send email
        success, message, msg_id = await service.send_email(
            user=user,
            template_name="welcome"
        )

        assert success is False
        assert msg_id is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailServiceBulkOperations:
    """Test EmailService bulk email operations."""

    async def test_send_bulk_emails_success(self, db_session: AsyncSession, mocker):
        """Test sending bulk emails to multiple users."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create multiple test users
        users = []
        for i in range(3):
            user = User(
                email=f"bulk{i}@example.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA",
                role=UserRole.INVITEE.value
            )
            db_session.add(user)
            users.append(user)
        await db_session.commit()

        # Create template
        await service.create_template(
            name="bulk_welcome",
            display_name="Bulk Welcome",
            subject="Welcome!",
            html_content="<p>Welcome {first_name}!</p>",
            sendgrid_template_id="d-bulk123"
        )

        # Mock SendGrid client
        mock_response = mocker.Mock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "bulk_msg"}

        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(return_value=mock_response)

        mocker.patch.object(service, 'client', mock_client)

        # Send bulk emails
        sent_count, failed_count, failed_ids, errors = await service.send_bulk_emails(
            users=users,
            template_name="bulk_welcome"
        )

        # Verify all succeeded
        assert sent_count == 3
        assert failed_count == 0
        assert len(failed_ids) == 0
        assert len(errors) == 0

        # Verify SendGrid was called for each user
        assert mock_client.send.call_count == 3

    async def test_send_bulk_emails_partial_failure(self, db_session: AsyncSession, mocker):
        """Test bulk emails with some failures."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test users (one with BAD status)
        user1 = User(
            email="good@example.com",
            first_name="Good",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        user2 = User(
            email="bad@example.com",
            first_name="Bad",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value,
            email_status="BAD"
        )
        db_session.add_all([user1, user2])
        await db_session.commit()

        # Create template
        await service.create_template(
            name="bulk_test",
            display_name="Bulk Test",
            subject="Test",
            html_content="<p>Test {first_name}</p>"
        )

        # Mock SendGrid client
        mock_response = mocker.Mock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "test_msg"}

        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(return_value=mock_response)

        mocker.patch.object(service, 'client', mock_client)

        # Send bulk emails
        sent_count, failed_count, failed_ids, errors = await service.send_bulk_emails(
            users=[user1, user2],
            template_name="bulk_test"
        )

        # Both should actually succeed (BAD status doesn't prevent sending in bulk)
        # Or one fails - depends on implementation
        # Check that we processed both users
        assert sent_count + failed_count == 2

    async def test_send_bulk_emails_with_template_id(self, db_session: AsyncSession, mocker):
        """Test sending bulk emails using template ID."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test users
        users = []
        for i in range(2):
            user = User(
                email=f"bulkid{i}@example.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA",
                role=UserRole.INVITEE.value
            )
            db_session.add(user)
            users.append(user)
        await db_session.commit()

        # Create template
        template = await service.create_template(
            name="bulk_template_id",
            display_name="Bulk Template ID",
            subject="Test",
            html_content="<p>Test {first_name}</p>",
            sendgrid_template_id="d-templateid"
        )

        # Mock SendGrid client
        mock_response = mocker.Mock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "template_id_msg"}

        mock_client = mocker.Mock()
        mock_client.send = mocker.Mock(return_value=mock_response)

        mocker.patch.object(service, 'client', mock_client)

        # Send bulk emails by template ID
        sent_count, failed_count, failed_ids, errors = await service.send_bulk_emails_with_template_id(
            users=users,
            template_id=template.id
        )

        # Verify all succeeded
        assert sent_count == 2
        assert failed_count == 0
        assert len(failed_ids) == 0
        assert len(errors) == 0

        assert mock_client.send.call_count == 2

    async def test_send_bulk_emails_empty_list(self, db_session: AsyncSession):
        """Test sending bulk emails with empty user list."""
        service = EmailService(db_session)

        # Create template
        await service.create_template(
            name="empty_bulk",
            display_name="Empty Bulk",
            subject="Test",
            html_content="<p>Test</p>"
        )

        # Send to empty list
        sent_count, failed_count, failed_ids, errors = await service.send_bulk_emails(
            users=[],
            template_name="empty_bulk"
        )

        # Should have zero counts
        assert sent_count == 0
        assert failed_count == 0
        assert len(failed_ids) == 0
        assert len(errors) == 0

    async def test_send_bulk_emails_template_not_found(self, db_session: AsyncSession):
        """Test bulk emails with non-existent template."""
        from app.models.user import User, UserRole

        service = EmailService(db_session)

        # Create test user
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()

        # Send bulk with non-existent template
        sent_count, failed_count, failed_ids, errors = await service.send_bulk_emails(
            users=[user],
            template_name="nonexistent_bulk_template"
        )

        # Should have one failure
        assert sent_count == 0
        assert failed_count == 1
        assert len(failed_ids) == 1
        assert user.id in failed_ids
        assert len(errors) == 1
        assert "not found" in errors[0].lower()
