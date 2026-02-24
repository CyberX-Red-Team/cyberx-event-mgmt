"""Participant service for managing participants."""
import secrets
import string
import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import select, func, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User, UserRole
from app.models.vpn import VPNCredential
from app.models.session import Session
from app.models.email_queue import EmailQueue
from app.models.event import EventParticipation
from app.models.audit_log import VPNRequest
from app.utils.security import hash_password
from app.services.email_queue_service import EmailQueueService
from app.api.utils.validation import normalize_email

logger = logging.getLogger(__name__)


class ParticipantService:
    """Service for managing event participants."""

    # Email statuses that should NOT receive emails
    BLOCKED_EMAIL_STATUSES = {'BOUNCED', 'SPAM_REPORTED', 'UNSUBSCRIBED'}

    def __init__(self, session: AsyncSession):
        """Initialize participant service."""
        self.session = session

    def _can_send_email(self, email_status: str) -> bool:
        """
        Check if emails can be sent to this email status.

        Allows: GOOD, UNKNOWN (needs verification)
        Blocks: BOUNCED, SPAM_REPORTED, UNSUBSCRIBED
        """
        return email_status not in self.BLOCKED_EMAIL_STATUSES

    async def get_participant(self, participant_id: int) -> Optional[User]:
        """Get a participant by ID with sponsor and participation relationships loaded."""
        result = await self.session.execute(
            select(User)
            .options(
                selectinload(User.sponsor),
                selectinload(User.event_participations)
            )
            .where(User.id == participant_id)
        )
        return result.scalar_one_or_none()

    async def get_sponsor(self, sponsor_id: int) -> Optional[User]:
        """Get a sponsor by ID (must be admin or sponsor role)."""
        result = await self.session.execute(
            select(User).where(
                User.id == sponsor_id,
                User.role.in_([UserRole.ADMIN.value, UserRole.SPONSOR.value])
            )
        )
        return result.scalar_one_or_none()

    async def get_participant_by_email(self, email: str) -> Optional[User]:
        """Get a participant by email (case-insensitive, Gmail alias aware)."""
        normalized_email = normalize_email(email)
        result = await self.session.execute(
            select(User).where(User.email_normalized == normalized_email)
        )
        return result.scalar_one_or_none()

    async def list_participants(
        self,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        confirmed: Optional[str] = None,
        has_vpn: Optional[bool] = None,
        is_active: Optional[bool] = None,
        email_status: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        sponsor_id: Optional[int] = None,
        role: Optional[str] = None,
        country: Optional[str] = None,
        event_id: Optional[int] = None
    ) -> Tuple[List[User], int]:
        """
        List participants with filtering and pagination.

        Args:
            sponsor_id: If provided, only return participants sponsored by this user
            role: If provided, filter by role (admin, sponsor, participant)
            event_id: If provided with confirmed filter, uses event-specific EventParticipation status

        Returns:
            Tuple of (list of users, total count)
        """
        # Build base query with sponsor and participation relationships loaded
        query = select(User).options(
            selectinload(User.sponsor),
            selectinload(User.event_participations)
        )
        count_query = select(func.count(User.id))

        # Filter by sponsor if provided (for sponsor role users)
        if sponsor_id is not None:
            query = query.where(User.sponsor_id == sponsor_id)
            count_query = count_query.where(User.sponsor_id == sponsor_id)

        # Filter by role if provided
        if role:
            query = query.where(User.role == role)
            count_query = count_query.where(User.role == role)

        # Apply filters
        if search:
            search_filter = or_(
                User.email.ilike(f"%{search}%"),
                User.first_name.ilike(f"%{search}%"),
                User.last_name.ilike(f"%{search}%"),
                User.pandas_username.ilike(f"%{search}%"),
                User.discord_username.ilike(f"%{search}%")
            )
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        if confirmed:
            if event_id:
                # Event-specific filtering via EventParticipation
                from app.models.event import ParticipationStatus
                from sqlalchemy import and_

                # Map legacy confirmed values to EventParticipation status values
                status_map = {
                    'YES': [ParticipationStatus.CONFIRMED.value],
                    'NO': [ParticipationStatus.DECLINED.value],
                    'UNKNOWN': [ParticipationStatus.INVITED.value, ParticipationStatus.NO_RESPONSE.value]
                }

                if confirmed in status_map:
                    status_values = status_map[confirmed]
                    query = query.join(EventParticipation, and_(
                        EventParticipation.user_id == User.id,
                        EventParticipation.event_id == event_id
                    )).where(EventParticipation.status.in_(status_values))
                    count_query = count_query.join(EventParticipation, and_(
                        EventParticipation.user_id == User.id,
                        EventParticipation.event_id == event_id
                    )).where(EventParticipation.status.in_(status_values))
            else:
                # Legacy global filtering (backward compatible)
                query = query.where(User.confirmed == confirmed)
                count_query = count_query.where(User.confirmed == confirmed)

        if is_active is not None:
            query = query.where(User.is_active == is_active)
            count_query = count_query.where(User.is_active == is_active)

        if email_status:
            query = query.where(User.email_status == email_status)
            count_query = count_query.where(User.email_status == email_status)

        if country:
            query = query.where(User.country == country)
            count_query = count_query.where(User.country == country)

        # Get total count
        total_result = await self.session.execute(count_query)
        total = total_result.scalar()

        # Apply sorting
        sort_column = getattr(User, sort_by, User.created_at)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        # Execute query
        result = await self.session.execute(query)
        participants = result.scalars().all()

        # Filter by VPN status if needed (requires join)
        if has_vpn is not None:
            filtered = []
            for p in participants:
                vpn_result = await self.session.execute(
                    select(VPNCredential).where(VPNCredential.assigned_to_user_id == p.id)
                )
                vpn = vpn_result.scalar_one_or_none()
                if (has_vpn and vpn) or (not has_vpn and not vpn):
                    filtered.append(p)
            participants = filtered

        return list(participants), total

    async def create_participant(
        self,
        email: str,
        first_name: str,
        last_name: str,
        country: str = "USA",
        confirmed: str = "UNKNOWN",
        pandas_username: Optional[str] = None,
        pandas_password: Optional[str] = None,
        discord_username: Optional[str] = None,
        sponsor_email: Optional[str] = None,
        sponsor_id: Optional[int] = None,
        role: str = UserRole.INVITEE.value,
        is_admin: bool = False
    ) -> User:
        """Create a new participant."""
        # Store original email for sending, calculate normalized for lookups
        email_original = email.strip()  # Remove leading/trailing whitespace only
        email_normalized = normalize_email(email)

        # IMPORTANT: Only generate credentials if explicitly provided OR if user is already confirmed
        # For new invitees with UNKNOWN status, credentials are generated AFTER they accept terms (USER_CONFIRMED workflow)
        # Sponsors and admins always get immediate credentials
        should_generate_credentials = (
            confirmed == 'YES' or  # User is already confirmed
            pandas_username is not None or  # Credentials explicitly provided
            pandas_password is not None or  # Credentials explicitly provided
            role in [UserRole.ADMIN.value, UserRole.SPONSOR.value]  # Admin/sponsor get immediate credentials
        )

        if should_generate_credentials:
            # Generate pandas username if not provided
            if not pandas_username:
                pandas_username = await self._generate_username(first_name, last_name)

            # Generate password if not provided
            if not pandas_password:
                pandas_password = self._generate_password()
        else:
            # New invitees: credentials will be generated after confirmation
            pandas_username = None
            pandas_password = None

        # If is_admin is True (legacy), set role to admin
        if is_admin and role == UserRole.INVITEE.value:
            role = UserRole.ADMIN.value

        # Import locally to avoid circular dependency
        from app.api.routes.public import generate_phonetic_password

        participant = User(
            email=email_original,
            email_normalized=email_normalized,
            first_name=first_name,
            last_name=last_name,
            country=country,
            confirmed=confirmed,
            email_status="UNKNOWN",
            pandas_username=pandas_username,
            pandas_password=pandas_password,
            password_hash=hash_password(pandas_password) if pandas_password else None,
            password_phonetic=generate_phonetic_password(pandas_password) if pandas_password else None,
            discord_username=discord_username,
            sponsor_email=sponsor_email,
            sponsor_id=sponsor_id,
            role=role,
            is_admin=is_admin or role == UserRole.ADMIN.value,
            is_active=True
        )

        self.session.add(participant)
        await self.session.commit()
        await self.session.refresh(participant)

        # Check if should send invitation based on role and event status
        is_event_participant = role in [UserRole.INVITEE.value, UserRole.SPONSOR.value]

        if is_event_participant:
            from app.services.event_service import EventService
            from app.services.workflow_service import WorkflowService

            event_service = EventService(self.session)
            event = await event_service.get_current_event()

            # Send invitations if event is active and:
            # - TEST MODE ALWAYS RESTRICTS: Only send to sponsors if test mode is enabled
            # - Otherwise: Send if registration is open
            should_send_invitation = False
            if event and event.is_active:
                if event.test_mode:
                    # Test mode: Only sponsors receive invitations
                    should_send_invitation = (role == UserRole.SPONSOR.value)
                else:
                    # Normal mode: Send if registration is open
                    should_send_invitation = event.registration_open

            if should_send_invitation:
                # Generate confirmation code
                participant.confirmation_code = secrets.token_urlsafe(32)
                participant.confirmation_sent_at = datetime.now(timezone.utc)
                await self.session.commit()

                # Only trigger user_created workflow for users with credentials (sponsors/admins)
                # Invitees without credentials are handled by the automated invitation_emails task
                has_credentials = participant.pandas_username is not None and participant.pandas_password is not None

                if has_credentials:
                    # Trigger workflow for sponsors/admins who have immediate credentials
                    try:
                        workflow_service = WorkflowService(self.session)
                        await workflow_service.trigger_workflow(
                            trigger_event="user_created",
                            user_id=participant.id,
                            custom_vars={
                                "confirmation_code": participant.confirmation_code,
                                "confirmation_url": "https://portal.cyberxredteam.org/confirm",
                                "event_name": event.name,
                                "event_year": str(event.year),
                                "terms_version": event.terms_version,
                                "role": role,
                                "pandas_username": participant.pandas_username,
                                "pandas_password": participant.pandas_password,
                                "password_phonetic": participant.password_phonetic,
                                "login_url": "https://portal.cyberxredteam.org/login"
                            }
                        )
                        logger.info(f"Triggered user_created workflow for {role} {participant.id} with credentials")
                    except Exception as e:
                        logger.error(f"Failed to trigger workflow for {role} {participant.id}: {str(e)}")
                else:
                    logger.info(f"Skipped user_created workflow for {role} {participant.id} (no credentials yet - will be handled by invitation task)")
            else:
                # Log why invitation was not sent
                from app.services.audit_service import AuditService
                audit_service = AuditService(self.session)

                if event and event.is_active and event.test_mode and role != UserRole.SPONSOR.value:
                    # Blocked by test mode
                    reason = "test_mode_restricted_non_sponsor"
                    await audit_service.log_invitation_blocked(
                        user_id=participant.id,  # Self-action (user created themselves or admin created them)
                        target_user_id=participant.id,
                        reason=reason,
                        event_id=event.id if event else None
                    )
                    logger.info(f"{role} created but invitation BLOCKED by test mode (non-sponsor)")
                else:
                    # Blocked by registration closed or event inactive
                    logger.info(f"{role} created but invitation NOT sent (event inactive or registration closed)")

                # For sponsors created outside normal workflow, send credentials email immediately
                if role == UserRole.SPONSOR.value and self._can_send_email(participant.email_status):
                    try:
                        queue_service = EmailQueueService(self.session)
                        await queue_service.enqueue_email(
                            user_id=participant.id,
                            template_name="password",
                            priority=3,
                            custom_vars={
                                "first_name": participant.first_name,
                                "last_name": participant.last_name,
                                "email": participant.email,
                                "pandas_username": participant.pandas_username,
                                "pandas_password": participant.pandas_password,
                                "password_phonetic": participant.password_phonetic,
                                "login_url": "https://portal.cyberxredteam.org/login"
                            }
                        )
                        logger.info(
                            f"Queued credentials email for sponsor {participant.id} ({participant.email}) "
                            f"with username={participant.pandas_username}, password={participant.pandas_password}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to queue credentials email for sponsor {participant.id}: {str(e)}")

        # If user is already confirmed (legacy import or manual creation), queue password email
        # For invitees: Only send if there's an active event (no passwords before campaign starts)
        # For sponsors/admins: Always send (they need portal access regardless of event status)
        elif confirmed == 'YES' and self._can_send_email(participant.email_status):
            should_send_password = False

            if role == UserRole.INVITEE.value:
                # Invitees: Only send password if event is active
                from app.services.event_service import EventService
                event_service = EventService(self.session)
                event = await event_service.get_current_event()
                should_send_password = event and event.is_active

                if not should_send_password:
                    logger.info(
                        f"Skipping password email for invitee {participant.id} ({participant.email}) "
                        f"- no active event (passwords sent when event activates)"
                    )
            else:
                # Sponsors/admins: Always send password (need portal access)
                should_send_password = True

            if should_send_password:
                try:
                    queue_service = EmailQueueService(self.session)
                    await queue_service.enqueue_email(
                        user_id=participant.id,
                        template_name="password",
                        priority=3,
                        custom_vars={
                            "first_name": participant.first_name,
                            "last_name": participant.last_name,
                            "email": participant.email,
                            "pandas_username": participant.pandas_username,
                            "pandas_password": participant.pandas_password,
                            "password_phonetic": participant.password_phonetic,
                            "login_url": "https://portal.cyberxredteam.org/login"
                        }
                    )
                    logger.info(
                        f"Queued password email for confirmed {role} {participant.id} ({participant.email})"
                    )
                except Exception as e:
                    logger.error(f"Failed to queue email for user {participant.id}: {str(e)}")

        return participant

    async def update_participant(
        self,
        participant_id: int,
        **kwargs
    ) -> Optional[User]:
        """Update a participant."""
        participant = await self.get_participant(participant_id)
        if not participant:
            return None

        # Track if confirmation status changed to YES
        old_confirmed = participant.confirmed
        was_confirmed = old_confirmed == 'YES'

        # Update fields (allow None values for nullable fields like sponsor_id)
        for key, value in kwargs.items():
            if hasattr(participant, key):
                setattr(participant, key, value)

        # Set confirmed_at timestamp when user confirms participation
        newly_confirmed = participant.confirmed == 'YES' and not was_confirmed
        if newly_confirmed:
            participant.confirmed_at = datetime.now(timezone.utc)

        participant.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(participant)

        # EVENT: Trigger workflows for user confirmation
        newly_confirmed = participant.confirmed == 'YES' and not was_confirmed
        if newly_confirmed and self._can_send_email(participant.email_status):
            try:
                from app.services.workflow_service import WorkflowService
                from app.models.email_workflow import WorkflowTriggerEvent

                workflow_service = WorkflowService(self.session)
                queued_count = await workflow_service.trigger_workflow(
                    trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
                    user_id=participant.id,
                    custom_vars={
                        "login_url": "https://portal.cyberxredteam.org/login",
                        "event_name": "CyberX Red Team Exercise"
                    }
                )
                if queued_count > 0:
                    logger.info(
                        f"Triggered {queued_count} workflow(s) for newly confirmed user {participant.id} ({participant.email})"
                    )
            except Exception as e:
                logger.error(f"Failed to trigger workflows for user {participant.id}: {str(e)}")

        return participant

    async def delete_participant(self, participant_id: int) -> bool:
        """
        Delete a participant.

        Security considerations:
        - VPN credentials are deleted entirely, not recycled, as downloaded configs
          could still be in use even after user deletion
        - User is removed from Keycloak if integration is configured
        """
        participant = await self.get_participant(participant_id)
        if not participant:
            return False

        # Step 1: Delete all related records with CASCADE + NOT NULL constraints
        # These must be deleted explicitly before the user, otherwise SQLAlchemy
        # tries to set user_id to NULL which violates NOT NULL constraints

        # Delete sessions
        await self.session.execute(
            delete(Session).where(Session.user_id == participant_id)
        )

        # Delete email queue entries
        await self.session.execute(
            delete(EmailQueue).where(EmailQueue.user_id == participant_id)
        )

        # Delete event participations
        await self.session.execute(
            delete(EventParticipation).where(EventParticipation.user_id == participant_id)
        )

        # Delete VPN requests
        await self.session.execute(
            delete(VPNRequest).where(VPNRequest.user_id == participant_id)
        )

        # Step 2: Mark VPN credentials as permanently unavailable (security: don't recycle downloaded configs)
        # Keep credentials in database for audit trail, but mark as unavailable.
        # Even though the user is being removed, their VPN configs may still be in use.
        # The assigned_to_user_id will be set to NULL by CASCADE, but we explicitly mark unavailable.
        result = await self.session.execute(
            select(VPNCredential).where(VPNCredential.assigned_to_user_id == participant_id)
        )
        vpn_credentials = result.scalars().all()
        for vpn in vpn_credentials:
            vpn.is_available = False  # Never recycle
            vpn.is_active = False      # Mark as inactive

        # Step 3: Delete user from Keycloak (if implemented)
        # TODO: When Keycloak integration is implemented, add deletion here:
        # if participant.pandas_username:
        #     keycloak_service = KeycloakService()
        #     try:
        #         await keycloak_service.delete_user(participant.pandas_username)
        #     except Exception as e:
        #         logger.warning(f"Failed to delete user from Keycloak: {e}")

        # Step 4: Delete the participant from database
        await self.session.delete(participant)
        await self.session.commit()

        return True

    async def reset_password(
        self,
        participant_id: int,
        new_password: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Reset a participant's password.

        Returns:
            Tuple of (success, new_password)
        """
        participant = await self.get_participant(participant_id)
        if not participant:
            return False, ""

        if not new_password:
            new_password = self._generate_password()

        participant.pandas_password = new_password
        participant.password_hash = hash_password(new_password)
        participant.updated_at = datetime.now(timezone.utc)

        await self.session.commit()

        return True, new_password

    async def bulk_activate(self, participant_ids: List[int]) -> Tuple[int, List[int]]:
        """Activate multiple participants."""
        success_count = 0
        failed_ids = []

        for pid in participant_ids:
            participant = await self.get_participant(pid)
            if participant:
                participant.is_active = True
                success_count += 1
            else:
                failed_ids.append(pid)

        await self.session.commit()
        return success_count, failed_ids

    async def bulk_deactivate(self, participant_ids: List[int]) -> Tuple[int, List[int]]:
        """Deactivate multiple participants."""
        success_count = 0
        failed_ids = []

        for pid in participant_ids:
            participant = await self.get_participant(pid)
            if participant:
                participant.is_active = False
                success_count += 1
            else:
                failed_ids.append(pid)

        await self.session.commit()
        return success_count, failed_ids

    async def get_statistics(self, sponsor_id: Optional[int] = None) -> dict:
        """
        Get participant statistics.

        Args:
            sponsor_id: If provided, only count participants sponsored by this user
        """
        # Base filter for sponsor
        base_filter = []
        if sponsor_id is not None:
            base_filter.append(User.sponsor_id == sponsor_id)

        # Total count
        total_query = select(func.count(User.id))
        if base_filter:
            total_query = total_query.where(*base_filter)
        total_result = await self.session.execute(total_query)
        total = total_result.scalar()

        # Confirmed count - use EventParticipation for current event
        from app.services.event_service import EventService
        from app.models.event import ParticipationStatus
        from sqlalchemy import and_

        event_service = EventService(self.session)
        current_event = await event_service.get_current_event()

        if current_event:
            # Event-specific confirmed count
            confirmed_query = (
                select(func.count(User.id))
                .join(EventParticipation, and_(
                    EventParticipation.user_id == User.id,
                    EventParticipation.event_id == current_event.id
                ))
                .where(EventParticipation.status == ParticipationStatus.CONFIRMED.value)
            )
            if base_filter:
                confirmed_query = confirmed_query.where(*base_filter)
            confirmed_result = await self.session.execute(confirmed_query)
            confirmed = confirmed_result.scalar()
        else:
            # Fallback to legacy field if no active event
            confirmed_query = select(func.count(User.id)).where(User.confirmed == "YES")
            if base_filter:
                confirmed_query = confirmed_query.where(*base_filter)
            confirmed_result = await self.session.execute(confirmed_query)
            confirmed = confirmed_result.scalar()

        # Active count
        active_query = select(func.count(User.id)).where(User.is_active == True)
        if base_filter:
            active_query = active_query.where(*base_filter)
        active_result = await self.session.execute(active_query)
        active = active_result.scalar()

        # With VPN count - count distinct users who have at least one VPN
        if sponsor_id is not None:
            # Count sponsored participants who have at least one VPN
            vpn_result = await self.session.execute(
                select(func.count(func.distinct(VPNCredential.assigned_to_user_id)))
                .join(User, VPNCredential.assigned_to_user_id == User.id)
                .where(User.sponsor_id == sponsor_id)
                .where(VPNCredential.assigned_to_user_id.isnot(None))
            )
        else:
            # Count all users who have at least one VPN
            vpn_result = await self.session.execute(
                select(func.count(func.distinct(VPNCredential.assigned_to_user_id)))
                .where(VPNCredential.assigned_to_user_id.isnot(None))
            )
        with_vpn = vpn_result.scalar()

        # Role counts (only for full stats)
        admin_count = 0
        sponsor_count = 0
        invitee_count = 0
        chronic_non_participant_count = 0
        recommended_removal_count = 0

        if sponsor_id is None:
            admin_result = await self.session.execute(
                select(func.count(User.id)).where(User.role == UserRole.ADMIN.value)
            )
            admin_count = admin_result.scalar()

            sponsor_result = await self.session.execute(
                select(func.count(User.id)).where(User.role == UserRole.SPONSOR.value)
            )
            sponsor_count = sponsor_result.scalar()

            invitee_result = await self.session.execute(
                select(func.count(User.id)).where(User.role == UserRole.INVITEE.value)
            )
            invitee_count = invitee_result.scalar()

            # Count chronic non-participants and recommended removals
            # These require loading users with their participation records
            all_users_result = await self.session.execute(
                select(User).options(selectinload(User.event_participations))
            )
            all_users = all_users_result.scalars().all()
            for user in all_users:
                if user.is_chronic_non_participant:
                    chronic_non_participant_count += 1
                if user.should_recommend_removal:
                    recommended_removal_count += 1

        return {
            "total_invitees": total,
            "confirmed_count": confirmed,
            "unconfirmed_count": total - confirmed,
            "with_vpn_count": with_vpn,
            "without_vpn_count": total - with_vpn,
            "active_count": active,
            "inactive_count": total - active,
            "admin_count": admin_count,
            "sponsor_count": sponsor_count,
            "invitee_count": invitee_count,
            "chronic_non_participant_count": chronic_non_participant_count,
            "recommended_removal_count": recommended_removal_count
        }

    async def get_sponsored_participants(
        self,
        sponsor_id: int,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[List[User], int]:
        """Get all participants sponsored by a specific user."""
        return await self.list_participants(
            page=page,
            page_size=page_size,
            sponsor_id=sponsor_id
        )

    async def assign_sponsor(
        self,
        participant_id: int,
        sponsor_id: int
    ) -> Optional[User]:
        """Assign a sponsor to a participant."""
        participant = await self.get_participant(participant_id)
        if not participant:
            return None

        # Verify sponsor exists and has appropriate role
        sponsor = await self.get_sponsor(sponsor_id)
        if not sponsor:
            return None

        participant.sponsor_id = sponsor_id
        participant.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(participant)

        return participant

    async def update_role(
        self,
        participant_id: int,
        new_role: str
    ) -> Optional[User]:
        """Update a user's role."""
        participant = await self.get_participant(participant_id)
        if not participant:
            return None

        participant.role = new_role
        # Keep is_admin in sync for legacy compatibility
        participant.is_admin = new_role == UserRole.ADMIN.value
        participant.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(participant)

        return participant

    async def list_sponsors(self) -> List[User]:
        """Get all users who can be sponsors (admins and sponsors)."""
        result = await self.session.execute(
            select(User)
            .options(
                selectinload(User.sponsor),
                selectinload(User.event_participations)
            )
            .where(User.role.in_([UserRole.ADMIN.value, UserRole.SPONSOR.value]))
            .order_by(User.last_name, User.first_name)
        )
        return list(result.scalars().all())

    async def _generate_username(self, first_name: str, last_name: str) -> str:
        """
        Generate a pandas username from name with conflict resolution.

        Format: first_initial + lastname (e.g., jsmith for John Smith)
        If conflict exists, appends numbers (jsmith1, jsmith2, etc.)
        """
        # Get first initial and combine with last name
        first_initial = first_name[0].lower() if first_name else ""
        base = f"{first_initial}{last_name.lower()}"
        # Remove special characters (keep only alphanumeric)
        base = "".join(c for c in base if c.isalnum())
        base = base[:50]  # Max 50 chars

        # Check for conflicts and add number suffix if needed
        username = base
        counter = 1

        while True:
            # Check if username already exists
            result = await self.session.execute(
                select(User).where(User.pandas_username == username)
            )
            existing = result.scalar_one_or_none()

            if not existing:
                # Username is available
                return username

            # Username exists, try with number suffix
            # Ensure the username + number doesn't exceed 50 chars
            suffix = str(counter)
            max_base_len = 50 - len(suffix)
            username = f"{base[:max_base_len]}{suffix}"
            counter += 1

            # Safety check to prevent infinite loop
            if counter > 999:
                # Fallback to timestamp-based unique username
                import time
                timestamp = str(int(time.time()))[-6:]
                return f"{base[:44]}{timestamp}"

    def _generate_password(self, length: int = 12) -> str:
        """Generate a secure random password."""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))
