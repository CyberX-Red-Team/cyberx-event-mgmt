# Event Lifecycle Management Implementation Guide

## Overview

This document provides the complete implementation plan for event lifecycle management with role-based invitation logic.

## Completed Components

1. ✅ **Event Model** - `/backend/app/models/event.py`
   - Event table with `is_active` and `registration_open` fields
   - EventParticipation for tracking user participation per event

2. ✅ **Event Service** - `/backend/app/services/event_service.py`
   - `get_current_event()` - Get active event
   - `can_send_invitations()` - Check if invitations should be sent

## Implementation Steps

### Step 1: Update User Model

Add confirmation and terms fields to `/backend/app/models/user.py`:

```python
# Add these fields to the User model class:

# Confirmation & Terms
confirmation_code = Column(String(100), unique=True, nullable=True, index=True)
confirmation_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
terms_accepted = Column(Boolean, default=False, nullable=False)
terms_accepted_at = Column(TIMESTAMP(timezone=True), nullable=True)
terms_version = Column(String(50), nullable=True)
```

### Step 2: Update Models __init__.py

Export Event model in `/backend/app/models/__init__.py`:

```python
from app.models.event import Event, EventParticipation, ParticipationStatus
```

### Step 3: Create Database Migration

File: `/backend/migrations/versions/YYYYMMDD_HHMMSS_add_event_lifecycle.py`

```python
"""add event lifecycle management

Revision ID: YYYYMMDD_HHMMSS
Revises: 20260131_205116
Create Date: 2026-01-31 XX:XX:XX

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'YYYYMMDD_HHMMSS'
down_revision = '20260131_205116'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add registration_open to events table (if not exists)
    op.add_column('events', sa.Column('registration_open', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('events', sa.Column('confirmation_expires_days', sa.Integer(), nullable=False, server_default='30'))

    # Add confirmation fields to users table
    op.add_column('users', sa.Column('confirmation_code', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('confirmation_sent_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_accepted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('terms_accepted_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_version', sa.String(50), nullable=True))

    # Create indexes
    op.create_index('idx_users_confirmation_code', 'users', ['confirmation_code'], unique=True)

    # Seed default event for 2026 (inactive by default)
    op.execute("""
        INSERT INTO events (year, name, is_active, registration_open, terms_version, terms_content, created_at)
        VALUES (
            2026,
            'CyberX Red Team Exercise 2026',
            false,
            false,
            '2026-v1',
            '# CyberX Red Team Exercise 2026 - Terms and Conditions

## Participation Agreement

By confirming your participation, you agree to:

1. **Code of Conduct**: Maintain professional behavior
2. **Confidentiality**: Keep sensitive information confidential
3. **Legal Compliance**: Operate only within authorized scope
4. **Data Usage**: Allow anonymized data usage for training
5. **Communication**: Maintain responsive communication

Last Updated: January 31, 2026
Version: 2026-v1',
            NOW()
        )
        ON CONFLICT (year) DO NOTHING
    """)

def downgrade() -> None:
    op.drop_index('idx_users_confirmation_code', 'users')
    op.drop_column('users', 'terms_version')
    op.drop_column('users', 'terms_accepted_at')
    op.drop_column('users', 'terms_accepted')
    op.drop_column('users', 'confirmation_sent_at')
    op.drop_column('users', 'confirmation_code')
    op.drop_column('events', 'confirmation_expires_days')
    op.drop_column('events', 'registration_open')
```

### Step 4: Update Participant Service

File: `/backend/app/services/participant_service.py`

Add role-aware invitation logic to `create_participant()`:

```python
async def create_participant(self, **kwargs) -> User:
    """Create user with role-based workflow triggering."""
    import secrets
    from app.models.user import UserRole
    from app.services.event_service import EventService

    # Create user
    participant = User(**kwargs)
    role = kwargs.get('role', UserRole.INVITEE.value)

    # Generate credentials
    if not participant.pandas_username:
        participant.pandas_username = self._generate_username(
            participant.first_name, participant.last_name
        )
    if not participant.pandas_password:
        participant.pandas_password = self._generate_password()

    participant.password_hash = hash_password(participant.pandas_password)

    self.session.add(participant)
    await self.session.commit()
    await self.session.refresh(participant)

    # Check if should send invitation
    is_event_participant = role in [UserRole.INVITEE.value, UserRole.SPONSOR.value]

    if is_event_participant:
        event_service = EventService(self.session)
        event = await event_service.get_current_event()

        if event and event.is_active and event.registration_open:
            # Generate confirmation code
            participant.confirmation_code = secrets.token_urlsafe(32)
            participant.confirmation_sent_at = datetime.now(timezone.utc)
            await self.session.commit()

            # Trigger invitation workflow
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
                    "role": role
                }
            )
            logger.info(f"Invitation sent to {role} {participant.id}")
        else:
            logger.info(f"{role} created but invitation NOT sent (event inactive)")

    return participant
```

### Step 5: Create Admin Event API

File: Add to `/backend/app/api/routes/admin.py`:

```python
@router.get("/event/current")
async def get_current_event(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Get current event configuration."""
    event_service = EventService(db)
    event = await event_service.get_current_event()

    if not event:
        return {"event": None}

    return {
        "event": {
            "id": event.id,
            "year": event.year,
            "name": event.name,
            "is_active": event.is_active,
            "registration_open": event.registration_open,
            "start_date": event.start_date.isoformat() if event.start_date else None,
            "end_date": event.end_date.isoformat() if event.end_date else None,
            "terms_version": event.terms_version,
            "max_participants": event.max_participants
        }
    }


@router.post("/event/toggle-active")
async def toggle_event_active(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Toggle event active status - ADMIN ONLY."""
    from app.models.user import UserRole

    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "Only administrators can toggle event status")

    event_service = EventService(db)
    event = await event_service.get_current_event()

    if not event:
        raise HTTPException(404, "No event configured")

    event.is_active = not event.is_active
    await db.commit()

    return {
        "success": True,
        "is_active": event.is_active,
        "message": f"Event {'activated' if event.is_active else 'deactivated'}"
    }
```

### Step 6: Create Public Confirmation Endpoints

File: Create `/backend/app/api/routes/public.py`:

```python
"""Public API endpoints (no authentication required)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.workflow_service import WorkflowService
from app.services.event_service import EventService
from app.models.email_workflow import WorkflowTriggerEvent
from app.dependencies import get_db

router = APIRouter(prefix="/api/public", tags=["Public"])

@router.get("/confirm/terms")
async def get_confirmation_terms(
    code: str,
    db: AsyncSession = Depends(get_db)
):
    """Get terms for confirmation (validates code)."""
    result = await db.execute(
        select(User).where(User.confirmation_code == code)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Invalid confirmation code")

    if user.confirmed == 'YES':
        return {"already_confirmed": True}

    event_service = EventService(db)
    event = await event_service.get_current_event()

    return {
        "user": {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email
        },
        "terms": {
            "content": event.terms_content if event else "",
            "version": event.terms_version if event else "2026-v1"
        },
        "event": {
            "name": event.name if event else "CyberX 2026",
            "year": event.year if event else 2026
        }
    }


@router.post("/confirm/accept")
async def confirm_participation(
    request: Request,
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """Confirm participation and accept terms."""
    code = data.get("confirmation_code")
    terms_accepted = data.get("terms_accepted")
    terms_version = data.get("terms_version")

    if not code or not terms_accepted:
        raise HTTPException(400, "Confirmation code and terms required")

    result = await db.execute(
        select(User).where(User.confirmation_code == code)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "Invalid confirmation code")

    if user.confirmed == 'YES':
        raise HTTPException(409, "Already confirmed")

    # Update user
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    user.confirmed = 'YES'
    user.confirmed_at = now
    user.terms_accepted = True
    user.terms_accepted_at = now
    user.terms_version = terms_version

    await db.commit()
    await db.refresh(user)

    # Audit log
    audit_service = AuditService(db)
    event_service = EventService(db)
    event = await event_service.get_current_event()

    await audit_service.log_terms_accept(
        user_id=user.id,
        event_id=event.id if event else 1,
        terms_version=terms_version,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    # Trigger credentials email
    workflow_service = WorkflowService(db)
    await workflow_service.trigger_workflow(
        trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
        user_id=user.id,
        custom_vars={
            "login_url": "https://portal.cyberxredteam.org/login",
            "event_name": event.name if event else "CyberX 2026"
        }
    )

    return {
        "success": True,
        "message": "Participation confirmed!",
        "user": {"first_name": user.first_name, "email": user.email}
    }
```

### Step 7: Register Public Routes

Add to `/backend/app/main.py`:

```python
from app.api.routes import public

app.include_router(public.router)
```

### Step 8: Frontend Dashboard Update

See full HTML in previous message for event status card.

## Testing Checklist

- [ ] Run database migration
- [ ] Create test event via SQL
- [ ] Toggle event active as admin
- [ ] Verify sponsor cannot toggle event
- [ ] Create invitee when event active → invitation sent
- [ ] Create invitee when event inactive → no invitation
- [ ] Create sponsor when event active → invitation sent
- [ ] Create admin when event active → no invitation
- [ ] Test confirmation flow with terms
- [ ] Verify credentials email sent after confirmation

## Role-Based Invitation Matrix

| Role | Event Active | Event Inactive |
|------|-------------|----------------|
| Invitee | ✅ Sent | ❌ Not sent |
| Sponsor | ✅ Sent | ❌ Not sent |
| Admin | ❌ Never | ❌ Never |

## Credential Generation Workflow

### Overview

User credentials (pandas_username and pandas_password) are generated at different times based on user role and confirmation status. This prevents premature credential creation and ensures proper workflow timing.

### Timing Rules

#### Immediate Credential Generation (At User Creation)

The following users receive credentials immediately when created:

1. **Sponsors** - Always get credentials at creation time
   - Can log in immediately after account creation
   - Keep the same credentials across years (unless manually reset)
   - No terms acceptance required for initial credentials

2. **Admins** - Always get credentials at creation time
   - Immediate access to admin portal
   - No confirmation workflow needed

3. **Pre-confirmed Users** - Any user with `confirmed='YES'`
   - Useful for bulk imports or returning participants
   - Bypasses confirmation workflow

4. **Explicitly Provided Credentials** - Any user creation with credentials specified
   - Allows manual credential assignment
   - Overrides automatic generation

#### Deferred Credential Generation (After Terms Acceptance)

**Invitees with UNKNOWN Status**:
- Created with `confirmed='UNKNOWN'` → NO credentials generated
- Receive invitation email with confirmation link
- Must accept terms and conditions
- Credentials generated at confirmation time via USER_CONFIRMED workflow

### Implementation Details

#### Participant Service Logic

File: `/backend/app/services/participant_service.py` (lines 190-210)

```python
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
```

#### Confirmation Endpoint Logic

File: `/backend/app/api/routes/public.py` (lines 213-231)

When an invitee accepts terms and conditions:

```python
# Generate credentials if not already set
# Username: Only generate if missing (returning participants keep their existing username)
if not user.pandas_username:
    user.pandas_username = await generate_username(user.first_name, user.last_name, db)

# Password: Different behavior based on role
# - Invitees: Always generate new password each year (for security)
# - Sponsors: Keep existing password across years (only generate if missing)
should_generate_password = False
if user.role == 'invitee':
    should_generate_password = True  # Always generate new password for invitees
elif not user.pandas_password:
    should_generate_password = True  # Generate for sponsors only if missing

if should_generate_password:
    password = generate_password(12)
    user.pandas_password = password  # Store plaintext for email (will be synced to Keycloak)
    user.password_hash = pwd_context.hash(password)  # Store hash for local auth
    user.password_phonetic = generate_phonetic_password(password)  # For easy communication
```

#### Workflow Trigger

After credentials are generated during confirmation:

```python
# Trigger credentials email
workflow_service = WorkflowService(db)
await workflow_service.trigger_workflow(
    trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
    user_id=user.id,
    custom_vars={
        "login_url": "https://portal.cyberxredteam.org/login",
        "event_name": event.name if event else "CyberX 2026",
        "pandas_username": user.pandas_username,
        "pandas_password": user.pandas_password,
        "password_phonetic": user.password_phonetic
    }
)
```

### Complete User Journey

#### Invitee Journey

1. **Admin creates invitee** (`confirmed='UNKNOWN'`, `role='invitee'`)
   - ❌ NO credentials generated
   - User record: `pandas_username=None`, `pandas_password=None`

2. **Event becomes active** (if not already)
   - Automated invitation workflow triggered after 30 seconds
   - Confirmation code generated and stored
   - Invitation email queued with confirmation link

3. **Invitee clicks confirmation link**
   - Sees terms and conditions
   - Must accept to proceed

4. **Invitee accepts terms**
   - ✅ Credentials generated NOW
   - Username: `firstname.lastname` (or variant if duplicate)
   - Password: Random 12-character password
   - Password phonetic: For easy communication
   - `confirmed='YES'`, `confirmed_at=NOW()`

5. **USER_CONFIRMED workflow triggers**
   - Credentials email queued
   - Email contains: username, password, phonetic password, login URL
   - User can now log in

#### Sponsor Journey

1. **Admin creates sponsor** (`confirmed='UNKNOWN'`, `role='sponsor'`)
   - ✅ Credentials generated IMMEDIATELY
   - User record: `pandas_username='john.smith'`, `pandas_password='xyz123...'`

2. **Sponsor can log in immediately** (if portal is active)
   - No terms acceptance required for initial access
   - Credentials sent via email immediately

3. **Event becomes active** (if applicable)
   - Sponsor receives invitation email (same as invitees)
   - Must accept terms to participate in event
   - Keeps existing credentials (no new password generated)

#### Admin Journey

1. **Admin creates admin account**
   - ✅ Credentials generated IMMEDIATELY
   - Full portal access
   - No event confirmation workflow

### Security Rationale

**Why defer credentials for invitees?**

1. **Prevents credential waste** - No unused credentials for users who never confirm
2. **Reduces attack surface** - Fewer active credentials in system
3. **Terms acceptance enforcement** - Users must accept terms before getting access
4. **Audit trail** - Clear link between terms acceptance and credential generation
5. **Annual password rotation** - Invitees get fresh passwords each year

**Why immediate credentials for sponsors?**

1. **Continuity** - Sponsors need consistent access across years
2. **Portal access** - Sponsors need to manage their invitees before event starts
3. **Different use case** - Sponsors are vetted, trusted participants
4. **Workflow efficiency** - Reduces administrative overhead

### Credential Generation Matrix

| User Type | Confirmed Status | Credentials Generated | Timing |
|-----------|------------------|----------------------|--------|
| Invitee | UNKNOWN | ❌ No | After terms acceptance |
| Invitee | YES | ✅ Yes | At creation |
| Sponsor | UNKNOWN | ✅ Yes | At creation |
| Sponsor | YES | ✅ Yes | At creation |
| Admin | Any | ✅ Yes | At creation |

### Testing Credential Workflows

#### Test 1: New Invitee (Deferred Credentials)
```bash
# Create invitee
POST /api/admin/participants
{
  "email": "invitee@test.com",
  "first_name": "Test",
  "last_name": "Invitee",
  "role": "invitee",
  "confirmed": "UNKNOWN"
}

# Verify NO credentials in database
SELECT pandas_username, pandas_password FROM users WHERE email = 'invitee@test.com';
# Expected: NULL, NULL

# Simulate confirmation
POST /api/public/confirm/accept
{
  "confirmation_code": "...",
  "terms_accepted": true,
  "terms_version": "2026-v1"
}

# Verify credentials NOW exist
SELECT pandas_username, pandas_password FROM users WHERE email = 'invitee@test.com';
# Expected: test.invitee, <random_password>
```

#### Test 2: New Sponsor (Immediate Credentials)
```bash
# Create sponsor
POST /api/admin/participants
{
  "email": "sponsor@test.com",
  "first_name": "Test",
  "last_name": "Sponsor",
  "role": "sponsor",
  "confirmed": "UNKNOWN"
}

# Verify credentials exist IMMEDIATELY
SELECT pandas_username, pandas_password FROM users WHERE email = 'sponsor@test.com';
# Expected: test.sponsor, <random_password>
```

#### Test 3: Pre-confirmed Invitee (Immediate Credentials)
```bash
# Create pre-confirmed invitee
POST /api/admin/participants
{
  "email": "preconf@test.com",
  "first_name": "Pre",
  "last_name": "Confirmed",
  "role": "invitee",
  "confirmed": "YES"
}

# Verify credentials exist IMMEDIATELY
SELECT pandas_username, pandas_password FROM users WHERE email = 'preconf@test.com';
# Expected: pre.confirmed, <random_password>
```
