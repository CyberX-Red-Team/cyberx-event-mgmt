"""
Unit tests for WorkflowService.

Tests workflow triggering, test mode restrictions, and workflow retrieval
operations.
"""

import pytest
from datetime import datetime, timezone, date
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workflow_service import WorkflowService
from app.models.email_workflow import EmailWorkflow, WorkflowTriggerEvent
from app.models.user import User, UserRole
from app.models.event import Event, generate_slug


@pytest.mark.unit
@pytest.mark.asyncio
class TestWorkflowServiceRetrieval:
    """Test workflow retrieval operations."""

    async def test_get_workflow_by_name(self, db_session: AsyncSession):
        """Test retrieving workflow by name."""
        service = WorkflowService(db_session)

        # Create workflow
        workflow = EmailWorkflow(
            name="user_confirmation",
            display_name="User Confirmation Email",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="confirmation",
            priority=5,
            is_enabled=True
        )
        db_session.add(workflow)
        await db_session.commit()

        # Retrieve
        retrieved = await service.get_workflow_by_name("user_confirmation")
        assert retrieved is not None
        assert retrieved.name == "user_confirmation"
        assert retrieved.template_name == "confirmation"

    async def test_get_nonexistent_workflow(self, db_session: AsyncSession):
        """Test retrieving non-existent workflow returns None."""
        service = WorkflowService(db_session)
        workflow = await service.get_workflow_by_name("nonexistent")
        assert workflow is None

    async def test_get_workflows_by_trigger_enabled_only(
        self, db_session: AsyncSession
    ):
        """Test getting workflows by trigger event (enabled only)."""
        service = WorkflowService(db_session)

        # Create workflows for same trigger
        enabled_workflow = EmailWorkflow(
            name="workflow1",
            display_name="Enabled Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="template1",
            priority=1,
            is_enabled=True
        )
        disabled_workflow = EmailWorkflow(
            name="workflow2",
            display_name="Disabled Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="template2",
            priority=2,
            is_enabled=False
        )
        db_session.add_all([enabled_workflow, disabled_workflow])
        await db_session.commit()

        # Get enabled only
        workflows = await service.get_workflows_by_trigger(
            WorkflowTriggerEvent.USER_CONFIRMED,
            enabled_only=True
        )

        assert len(workflows) == 1
        assert workflows[0].name == "workflow1"
        assert workflows[0].is_enabled is True

    async def test_get_workflows_by_trigger_all(self, db_session: AsyncSession):
        """Test getting all workflows by trigger event (including disabled)."""
        service = WorkflowService(db_session)

        # Create workflows
        enabled_workflow = EmailWorkflow(
            name="workflow1",
            display_name="Enabled Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="template1",
            priority=1,
            is_enabled=True
        )
        disabled_workflow = EmailWorkflow(
            name="workflow2",
            display_name="Disabled Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="template2",
            priority=2,
            is_enabled=False
        )
        db_session.add_all([enabled_workflow, disabled_workflow])
        await db_session.commit()

        # Get all
        workflows = await service.get_workflows_by_trigger(
            WorkflowTriggerEvent.USER_CONFIRMED,
            enabled_only=False
        )

        assert len(workflows) == 2
        assert workflows[0].priority == 1  # Ordered by priority
        assert workflows[1].priority == 2

    async def test_get_workflows_by_trigger_priority_order(
        self, db_session: AsyncSession
    ):
        """Test workflows are returned ordered by priority."""
        service = WorkflowService(db_session)

        # Create workflows with different priorities
        low_priority = EmailWorkflow(
            name="low",
            display_name="Low Priority",
            trigger_event=WorkflowTriggerEvent.VPN_ASSIGNED,
            template_name="template1",
            priority=10,
            is_enabled=True
        )
        high_priority = EmailWorkflow(
            name="high",
            display_name="High Priority",
            trigger_event=WorkflowTriggerEvent.VPN_ASSIGNED,
            template_name="template2",
            priority=1,
            is_enabled=True
        )
        medium_priority = EmailWorkflow(
            name="medium",
            display_name="Medium Priority",
            trigger_event=WorkflowTriggerEvent.VPN_ASSIGNED,
            template_name="template3",
            priority=5,
            is_enabled=True
        )
        db_session.add_all([low_priority, high_priority, medium_priority])
        await db_session.commit()

        workflows = await service.get_workflows_by_trigger(
            WorkflowTriggerEvent.VPN_ASSIGNED
        )

        # Should be ordered: high (1), medium (5), low (10)
        assert len(workflows) == 3
        assert workflows[0].name == "high"
        assert workflows[1].name == "medium"
        assert workflows[2].name == "low"


@pytest.mark.unit
@pytest.mark.asyncio
class TestWorkflowServiceTrigger:
    """Test workflow trigger operations."""

    async def test_trigger_workflow_no_workflows(self, db_session: AsyncSession):
        """Test triggering with no workflows returns 0."""
        service = WorkflowService(db_session)

        # Create user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)
        await db_session.commit()

        # Trigger non-existent workflow
        count = await service.trigger_workflow(
            "nonexistent_event",
            user.id
        )

        assert count == 0

    async def test_trigger_workflow_success(self, db_session: AsyncSession):
        """Test successfully triggering workflow."""
        service = WorkflowService(db_session)

        # Create user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)

        # Create workflow
        workflow = EmailWorkflow(
            name="test_workflow",
            display_name="Test Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="confirmation",
            priority=5,
            is_enabled=True
        )
        db_session.add(workflow)
        await db_session.commit()

        # Trigger
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.USER_CONFIRMED,
            user.id
        )

        assert count == 1

    async def test_trigger_workflow_with_custom_vars(
        self, db_session: AsyncSession
    ):
        """Test triggering workflow with custom variables."""
        service = WorkflowService(db_session)

        # Create user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)

        # Create workflow with custom vars
        workflow = EmailWorkflow(
            name="test_workflow",
            display_name="Test Workflow",
            trigger_event=WorkflowTriggerEvent.VPN_ASSIGNED,
            template_name="vpn_assigned",
            priority=5,
            is_enabled=True,
            custom_vars={"default_var": "default_value"}
        )
        db_session.add(workflow)
        await db_session.commit()

        # Trigger with additional custom vars
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.VPN_ASSIGNED,
            user.id,
            custom_vars={"vpn_ip": "10.66.66.10"}
        )

        assert count == 1

    async def test_trigger_multiple_workflows(self, db_session: AsyncSession):
        """Test triggering multiple workflows for same event."""
        service = WorkflowService(db_session)

        # Create user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)

        # Create multiple workflows for same trigger
        workflow1 = EmailWorkflow(
            name="workflow1",
            display_name="Workflow 1",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="template1",
            priority=1,
            is_enabled=True
        )
        workflow2 = EmailWorkflow(
            name="workflow2",
            display_name="Workflow 2",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="template2",
            priority=2,
            is_enabled=True
        )
        db_session.add_all([workflow1, workflow2])
        await db_session.commit()

        # Trigger should queue both
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.USER_CONFIRMED,
            user.id
        )

        assert count == 2

    async def test_trigger_skips_disabled_workflows(
        self, db_session: AsyncSession
    ):
        """Test triggering skips disabled workflows."""
        service = WorkflowService(db_session)

        # Create user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)

        # Create enabled and disabled workflows
        enabled = EmailWorkflow(
            name="enabled",
            display_name="Enabled",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="template1",
            priority=1,
            is_enabled=True
        )
        disabled = EmailWorkflow(
            name="disabled",
            display_name="Disabled",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="template2",
            priority=2,
            is_enabled=False
        )
        db_session.add_all([enabled, disabled])
        await db_session.commit()

        # Should only trigger enabled
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.USER_CONFIRMED,
            user.id
        )

        assert count == 1

    async def test_trigger_workflow_with_delay(self, db_session: AsyncSession):
        """Test triggering workflow with delay_minutes schedules for future."""
        from sqlalchemy import select
        from app.models.email_queue import EmailQueue

        service = WorkflowService(db_session)

        # Create user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)

        # Create workflow with delay
        workflow = EmailWorkflow(
            name="delayed_workflow",
            display_name="Delayed Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="confirmation",
            priority=5,
            delay_minutes=30,  # 30 minute delay
            is_enabled=True
        )
        db_session.add(workflow)
        await db_session.commit()

        # Trigger
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.USER_CONFIRMED,
            user.id
        )

        assert count == 1

        # Verify email was scheduled for future
        result = await db_session.execute(
            select(EmailQueue).where(EmailQueue.user_id == user.id)
        )
        email = result.scalar_one_or_none()
        assert email is not None
        assert email.scheduled_for is not None
        # Should be scheduled approximately 30 minutes in future
        from datetime import timedelta
        expected_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        # Handle timezone-naive datetime from SQLite
        scheduled_time = email.scheduled_for
        if scheduled_time.tzinfo is None:
            scheduled_time = scheduled_time.replace(tzinfo=timezone.utc)
        time_diff = abs((scheduled_time - expected_time).total_seconds())
        assert time_diff < 5  # Within 5 seconds

    async def test_trigger_workflow_error_handling(
        self, db_session: AsyncSession, mocker
    ):
        """Test workflow continues on error and logs failure."""
        service = WorkflowService(db_session)

        # Create user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user)

        # Create workflows - first will fail, second should succeed
        workflow1 = EmailWorkflow(
            name="failing_workflow",
            display_name="Failing Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="nonexistent_template",
            priority=1,
            is_enabled=True
        )
        workflow2 = EmailWorkflow(
            name="succeeding_workflow",
            display_name="Succeeding Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="confirmation",
            priority=2,
            is_enabled=True
        )
        db_session.add_all([workflow1, workflow2])
        await db_session.commit()

        # Mock EmailQueueService.enqueue_email to fail for first call
        from app.services.email_queue_service import EmailQueueService
        original_enqueue = EmailQueueService.enqueue_email
        call_count = [0]

        async def mock_enqueue(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Simulated queue failure")
            return await original_enqueue(self, *args, **kwargs)

        mocker.patch.object(
            EmailQueueService,
            'enqueue_email',
            mock_enqueue
        )

        # Trigger - should log error for first but continue
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.USER_CONFIRMED,
            user.id
        )

        # Only second workflow should succeed
        assert count == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestWorkflowServiceTestMode:
    """Test workflow test mode restrictions."""

    async def test_trigger_in_test_mode_sponsor_allowed(
        self, db_session: AsyncSession
    ):
        """Test workflows trigger for sponsors in test mode."""
        service = WorkflowService(db_session)

        # Create test mode event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True,
            test_mode=True
        )
        db_session.add(event)

        # Create sponsor user
        sponsor = User(
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )
        db_session.add(sponsor)

        # Create workflow
        workflow = EmailWorkflow(
            name="test_workflow",
            display_name="Test Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="confirmation",
            priority=5,
            is_enabled=True
        )
        db_session.add(workflow)
        await db_session.commit()

        # Sponsor should be allowed in test mode
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.USER_CONFIRMED,
            sponsor.id
        )

        assert count == 1

    async def test_trigger_in_test_mode_invitee_blocked(
        self, db_session: AsyncSession
    ):
        """Test workflows blocked for invitees in test mode."""
        service = WorkflowService(db_session)

        # Create test mode event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True,
            test_mode=True
        )
        db_session.add(event)

        # Create invitee user
        invitee = User(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(invitee)

        # Create workflow
        workflow = EmailWorkflow(
            name="test_workflow",
            display_name="Test Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="confirmation",
            priority=5,
            is_enabled=True
        )
        db_session.add(workflow)
        await db_session.commit()

        # Invitee should be blocked in test mode
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.USER_CONFIRMED,
            invitee.id
        )

        assert count == 0

    async def test_trigger_not_in_test_mode_all_allowed(
        self, db_session: AsyncSession
    ):
        """Test workflows trigger for all users when not in test mode."""
        service = WorkflowService(db_session)

        # Create normal (non-test) event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True,
            test_mode=False
        )
        db_session.add(event)

        # Create invitee user
        invitee = User(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(invitee)

        # Create workflow
        workflow = EmailWorkflow(
            name="test_workflow",
            display_name="Test Workflow",
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            template_name="confirmation",
            priority=5,
            is_enabled=True
        )
        db_session.add(workflow)
        await db_session.commit()

        # Invitee should be allowed when not in test mode
        count = await service.trigger_workflow(
            WorkflowTriggerEvent.USER_CONFIRMED,
            invitee.id
        )

        assert count == 1
