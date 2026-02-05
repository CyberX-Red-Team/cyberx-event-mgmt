# CyberX Event Management System - Administrator Guide

**Version:** 0.9.0
**Last Updated:** February 2026

---

## Table of Contents

1. [System Overview](#system-overview)
2. [User Roles & Permissions](#user-roles--permissions)
3. [Database Schema](#database-schema)
4. [Field Reference](#field-reference)
5. [Webhook Endpoints](#webhook-endpoints)
6. [Workflow System](#workflow-system)
7. [Email Management](#email-management)
8. [VPN Credential Management](#vpn-credential-management)
9. [Event Lifecycle](#event-lifecycle)
10. [Background Tasks](#background-tasks)
11. [Common Administrative Tasks](#common-administrative-tasks)
12. [Troubleshooting](#troubleshooting)

---

## System Overview

The CyberX Event Management System is a comprehensive platform for managing annual cybersecurity red team exercises. It handles participant registration, invitation workflows, VPN credential distribution, email automation, and event participation tracking.

### Architecture Components

```mermaid
graph TB
    A[Web UI - Jinja2 Templates] --> B[FastAPI Application]
    B --> C[Services Layer]
    C --> D[(PostgreSQL Database)]
    C --> E[SendGrid API]
    C --> F[Background Scheduler]
    B --> G[Webhook Endpoints]
    G --> E
    F --> C

    subgraph "External Services"
        E
        H[Discord]
        I[Keycloak SSO]
    end

    H -.-> G
    I -.-> G
```

### Key Technologies

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy (async)
- **Database**: PostgreSQL (via Supabase)
- **Email**: SendGrid (transactional emails)
- **Scheduler**: APScheduler (background tasks)
- **Authentication**: Session-based with CSRF protection
- **Encryption**: Fernet (field-level), bcrypt (passwords)
- **VPN**: WireGuard configuration management

---

## User Roles & Permissions

### Role Hierarchy

```mermaid
graph TD
    A[ADMIN] --> B[Full System Access]
    A --> C[Manage All Users]
    A --> D[Manage Events]
    A --> E[View Audit Logs]
    A --> F[Send Bulk Emails]

    G[SPONSOR] --> H[Manage Sponsored Invitees]
    G --> I[Invite New Participants]
    G --> J[Reset Passwords]
    G --> K[View Sponsored Stats]

    L[INVITEE] --> M[Confirm/Decline Events]
    L --> N[Request VPN Credentials]
    L --> O[View Participation History]
    L --> P[Accept Terms]
```

### Permission Matrix

| Action | Admin | Sponsor | Invitee |
|--------|-------|---------|---------|
| Create/Edit Events | ✅ | ❌ | ❌ |
| Manage All Participants | ✅ | ❌ | ❌ |
| Manage Sponsored Invitees | ✅ | ✅ | ❌ |
| Send Bulk Emails | ✅ | ❌ | ❌ |
| View Audit Logs | ✅ | ❌ | ❌ |
| Assign VPN Credentials (Admin Only) | ✅ | ❌ | ❌ |
| Request VPN Credentials (Self-Service) | ✅ | ✅ | ✅ |
| Confirm Event Participation | ✅ | ✅ | ✅ |
| View Email Analytics | ✅ | ❌ | ❌ |
| Manage Email Workflows | ✅ | ❌ | ❌ |

### Special Role Properties

#### Admin (`is_admin_role`)
- Can manage events (create, update, activate, archive)
- Can view all participants regardless of sponsor
- Can send bulk emails to all users
- Can access audit logs and system settings
- Can manage email templates and workflows

#### Sponsor (`is_sponsor_role`)
- Can create and manage their sponsored invitees
- Can reset passwords for sponsored users
- Can resend invitations to sponsored users
- Can request VPN credentials (self-service)
- Receives emails even when event is in test mode

#### Invitee
- Can confirm or decline event participation
- Can accept terms and conditions
- Can request VPN credentials (when event.vpn_available)
- Can view their own participation history
- Limited to self-service operations

---

## Database Schema

### Entity Relationship Diagram

```mermaid
erDiagram
    USERS ||--o{ EVENT_PARTICIPATIONS : "participates in"
    USERS ||--o{ VPN_CREDENTIALS : "assigned"
    USERS ||--o{ EMAIL_QUEUE : "receives"
    USERS ||--o{ AUDIT_LOGS : "performs actions"
    USERS ||--o{ USERS : "sponsors"

    EVENTS ||--o{ EVENT_PARTICIPATIONS : "has"
    EVENTS ||--o{ EMAIL_WORKFLOWS : "triggers"

    EMAIL_TEMPLATES ||--o{ EMAIL_QUEUE : "used by"
    EMAIL_TEMPLATES ||--o{ EMAIL_WORKFLOWS : "referenced by"

    USERS {
        int id PK
        string email UK
        string first_name
        string last_name
        string country
        string role
        string confirmed
        string email_status
        text password_hash
        text pandas_password_encrypted
        int sponsor_id FK
        string theme_preference
        datetime created_at
    }

    EVENTS {
        int id PK
        int year
        string name
        string slug UK
        date start_date
        date end_date
        string event_time
        string event_location
        bool is_active
        bool registration_open
        bool vpn_available
        bool test_mode
        string terms_version
        text terms_content
    }

    EVENT_PARTICIPATIONS {
        int id PK
        int user_id FK
        int event_id FK
        string status
        datetime invited_at
        datetime confirmed_at
        datetime declined_at
        text declined_reason
        datetime terms_accepted_at
    }

    VPN_CREDENTIALS {
        int id PK
        string interface_ip
        text private_key
        text preshared_key
        string endpoint
        string key_type
        int assigned_to_user_id FK
        datetime assigned_at
    }

    EMAIL_QUEUE {
        int id PK
        int user_id FK
        string template_name
        string status
        int priority
        json custom_vars
        datetime scheduled_for
        int attempts
        text error_message
    }

    EMAIL_WORKFLOWS {
        int id PK
        string name UK
        string trigger_event
        string template_name FK
        int priority
        int delay_minutes
        bool is_enabled
        json custom_vars
    }

    EMAIL_TEMPLATES {
        int id PK
        string name UK
        string subject
        text html_content
        string sendgrid_template_id
        json available_variables
    }

    AUDIT_LOGS {
        int id PK
        int user_id FK
        string action
        string resource_type
        string ip_address
        json details
        datetime created_at
    }
```

### Database Tables Summary

| Table | Purpose | Key Constraints |
|-------|---------|----------------|
| `users` | User accounts and participant information | email UNIQUE |
| `events` | Annual CyberX event instances | slug UNIQUE |
| `event_participations` | User participation tracking per event | (user_id, event_id) UNIQUE |
| `vpn_credentials` | WireGuard VPN configuration storage | - |
| `email_templates` | Email template definitions | name UNIQUE |
| `email_queue` | Queue for batched email sending | - |
| `email_workflows` | Automated email workflow configuration | name UNIQUE |
| `email_batch_logs` | Email batch processing history | - |
| `email_events` | SendGrid webhook event tracking | - |
| `vpn_requests` | VPN credential request tracking | - |
| `audit_logs` | System activity audit trail | - |
| `sessions` | User session management | - |
| `scheduler_status` | Background scheduler heartbeat | - |

---

## Field Reference

### User Fields

#### Core Identity
- **`id`** (int, PK): Unique user identifier
- **`email`** (string, UNIQUE): User's email address (login username)
- **`first_name`** (string): Given name
- **`last_name`** (string): Family name
- **`full_name`** (computed): `first_name + " " + last_name`
- **`country`** (string): Country code (e.g., "USA", "GBR")

#### Role & Access
- **`role`** (enum): User role - `ADMIN`, `SPONSOR`, or `INVITEE`
- **`is_admin`** (bool): Deprecated admin flag (use role instead)
- **`sponsor_id`** (int, FK): ID of sponsoring user (for invitees)
- **`is_active`** (bool): Account enabled status

#### Participation Status
- **`confirmed`** (enum): Registration confirmation status
  - `"YES"`: Participant has confirmed attendance
  - `"NO"`: Participant declined
  - `"UNKNOWN"`: No response yet (invited but no action)
- **`confirmation_code`** (string): Unique code for email confirmation link
- **`confirmation_sent_at`** (datetime): When confirmation email was sent
- **`confirmed_at`** (datetime): When user confirmed participation

#### Email Status
- **`email_status`** (enum): Email deliverability status
  - `"VALID"`: Email is working
  - `"BOUNCED"`: Email bounced (hard bounce)
  - `"SPAM_REPORTED"`: User marked emails as spam
  - `"UNSUBSCRIBED"`: User unsubscribed
  - `null`: Unknown/not yet validated
- **`password_email_sent`** (datetime): When credentials email was sent

#### Credentials
- **`password_hash`** (text): Bcrypt hash for portal login
- **`_pandas_password_encrypted`** (text): Fernet-encrypted password for Pandas
- **`pandas_password`** (property): Decrypts pandas password on access
- **`password_reset_token`** (string): Token for password reset flow
- **`password_reset_expires`** (datetime): Reset token expiration

#### Terms & Compliance
- **`terms_accepted`** (bool): Whether user accepted T&Cs
- **`terms_accepted_at`** (datetime): When terms were accepted
- **`terms_version`** (string): Version of terms accepted (e.g., "2026-v1")

#### Preferences
- **`theme_preference`** (string): UI theme - `"light"` or `"dark"`

#### Timestamps
- **`created_at`** (datetime): User account creation
- **`updated_at`** (datetime): Last modification

---

### Event Fields

#### Core Identity
- **`id`** (int, PK): Unique event identifier
- **`year`** (int): Event year (e.g., 2026) - **no longer unique**
- **`name`** (string): Event name (e.g., "CyberX Red Team Exercise 2026")
- **`slug`** (string, UNIQUE): URL-friendly identifier (e.g., "cyberx-red-team-exercise-2026")
  - Auto-generated from name if not provided
  - Allows multiple events per year

#### Event Dates
- **`start_date`** (date): Event start date
- **`end_date`** (date): Event end date
- **`event_time`** (string): Time description (e.g., "Doors open 18:00 UTC")
- **`event_location`** (string): Location (e.g., "Austin, TX" or "Virtual")

#### Registration
- **`registration_opens`** (datetime): When registration starts
- **`registration_closes`** (datetime): When registration ends
- **`registration_open`** (bool): Quick toggle to open/close registration

#### Terms & Conditions
- **`terms_version`** (string): Version identifier (e.g., "2026-v1")
- **`terms_content`** (text): Full terms text (markdown supported)
- **`terms_updated_at`** (datetime): When terms were last updated

#### Status & Mode
- **`is_active`** (bool): Whether event is currently active
  - Only one event should be active at a time
  - Controls invitation sending
- **`is_archived`** (bool): Whether event is archived
- **`vpn_available`** (bool): Whether users can request VPN credentials
- **`test_mode`** (bool): Test mode restricts operations to sponsors only
  - When enabled, only sponsors receive emails
  - Used for testing before full launch

#### Configuration
- **`max_participants`** (int): Maximum participant limit
- **`confirmation_expires_days`** (int): Days until confirmation expires (default: 30)

#### Timestamps
- **`created_at`** (datetime): Event creation time
- **`updated_at`** (datetime): Last modification time

---

### Event Participation Fields

#### Core References
- **`id`** (int, PK): Unique participation record ID
- **`user_id`** (int, FK): Reference to user
- **`event_id`** (int, FK): Reference to event
- **Unique Constraint**: (user_id, event_id) - one record per user per event

#### Invitation Tracking
- **`invited_at`** (datetime): When invitation was sent
- **`invited_by_user_id`** (int, FK): Who sent the invitation (admin/sponsor)

#### Response Status
- **`status`** (enum): Participation status
  - `"invited"`: Invitation sent, no response
  - `"confirmed"`: User confirmed attendance
  - `"declined"`: User declined
  - `"no_response"`: Expired without response
- **`responded_at`** (datetime): When user responded

#### Terms Acceptance
- **`terms_accepted_at`** (datetime): When user accepted event terms
- **`terms_version_accepted`** (string): Version of terms accepted

#### Confirmation/Decline Details
- **`confirmed_at`** (datetime): When user confirmed
- **`declined_at`** (datetime): When user declined
- **`declined_reason`** (text): Optional reason for declining

#### Notes
- **`notes`** (text): Admin/sponsor notes about participation

#### Timestamps
- **`created_at`** (datetime): Record creation
- **`updated_at`** (datetime): Last modification

---

### VPN Credential Fields

#### Core Identity
- **`id`** (int, PK): Unique credential ID
- **`file_hash`** (string): SHA-256 hash of source file
- **`file_id`** (string): Original filename identifier
- **`run_id`** (string): Import batch identifier

#### IP Addresses
- **`interface_ip`** (text): Comma-separated IP addresses
  - Format: `"IPv4,IPv6_local,IPv6_global"`
  - Example: `"10.20.200.149,fd00:a:14:c8:95::95,fd00:a:14:c8:95:ffff:a14:c895"`
- **`ipv4_address`** (string): Extracted IPv4 address
- **`ipv6_local`** (string): Extracted IPv6 local address
- **`ipv6_global`** (string): Extracted IPv6 global address

#### WireGuard Configuration
- **`private_key`** (text): Base64-encoded WireGuard private key
- **`preshared_key`** (text, optional): Base64-encoded pre-shared key (post-quantum security)
- **`endpoint`** (string): VPN server endpoint (e.g., "216.208.235.11:51020")

#### Assignment
- **`assigned_to_user_id`** (int, FK): User who has this credential
- **`assigned_to_username`** (string): Cached username for quick lookup
- **`assigned_at`** (datetime): When credential was assigned

#### Configuration Type
- **`key_type`** (enum): Credential type
  - `"cyber"`: Cyber team credentials
  - `"kinetic"`: Kinetic team credentials

#### Request Tracking
- **`request_batch_id`** (string): Batch ID if requested via bulk request

#### Timestamps
- **`created_at`** (datetime): Credential import time
- **`updated_at`** (datetime): Last modification

---

### Email Queue Fields

#### Core Identity
- **`id`** (int, PK): Unique queue entry ID
- **`user_id`** (int, FK): Recipient user
- **`template_name`** (string): Email template to use

#### Processing Status
- **`status`** (enum): Queue processing status
  - `"pending"`: Waiting to be sent
  - `"processing"`: Currently being sent
  - `"sent"`: Successfully sent
  - `"failed"`: Failed to send (see error_message)
- **`batch_id`** (string): Batch processing group identifier
- **`worker_id`** (string): Worker that processed this email

#### Priority & Scheduling
- **`priority`** (int): Send priority (lower number = higher priority)
  - Default: 5
  - Urgent: 1
  - Low priority: 10
- **`scheduled_for`** (datetime): When to send (for delayed emails)
  - null = send immediately

#### Retry Logic
- **`attempts`** (int): Number of send attempts
- **`max_attempts`** (int): Maximum retry attempts (default: 3)
- **`last_attempt_at`** (datetime): When last send was attempted
- **`error_message`** (text): Error details if failed

#### Customization
- **`custom_vars`** (JSON): Template variable overrides
  - Example: `{"event_name": "CyberX 2026", "custom_message": "Welcome!"}`

#### Timestamps
- **`created_at`** (datetime): When queued
- **`updated_at`** (datetime): Last status update
- **`sent_at`** (datetime): When successfully sent

---

### Email Workflow Fields

#### Core Identity
- **`id`** (int, PK): Unique workflow ID
- **`name`** (string, UNIQUE): Workflow identifier (e.g., "welcome_email")

#### Trigger Configuration
- **`trigger_event`** (enum): Event that triggers this workflow
  - `"user_created"`: New user created
  - `"user_confirmed"`: User confirmed participation
  - `"password_reset"`: Password reset initiated
  - `"vpn_assigned"`: VPN credential assigned
  - `"participation_confirmed"`: Event participation confirmed
  - `"event_reminder"`: Event reminder time reached
  - `"bulk_invite"`: Bulk invitation sent
  - `"custom_email"`: Admin-triggered custom email

#### Email Configuration
- **`template_name`** (string, FK): Email template to use
- **`priority`** (int): Queue priority (1-10)
- **`delay_minutes`** (int): Delay before sending (0 = immediate)
  - Example: 30 = send 30 minutes after trigger

#### Workflow Control
- **`is_enabled`** (bool): Whether workflow is active
  - Disabled workflows are not triggered

#### Customization
- **`custom_vars`** (JSON): Default template variables
  - Merged with trigger-specific variables
  - Example: `{"sender_name": "CyberX Team"}`

#### Timestamps
- **`created_at`** (datetime): Workflow creation
- **`updated_at`** (datetime): Last modification

---

### Email Template Fields

#### Core Identity
- **`id`** (int, PK): Unique template ID
- **`name`** (string, UNIQUE): Template identifier (e.g., "invitation")

#### Email Content
- **`subject`** (string): Email subject line
  - Supports Jinja2 variables: `{{ first_name }}` `{{ last_name }}`
- **`html_content`** (text): HTML email body
  - Full Jinja2 template support
  - CSS inlining recommended for email clients
- **`text_content`** (text, optional): Plain text fallback

#### SendGrid Integration
- **`sendgrid_template_id`** (string, optional): SendGrid dynamic template ID
  - If provided, uses SendGrid template instead of html_content
- **`sendgrid_version_id`** (string, optional): Specific template version

#### Template Documentation
- **`description`** (text): Template purpose and usage notes
- **`available_variables`** (JSON): List of supported variables
  - Example:
    ```json
    {
      "first_name": "User's first name",
      "last_name": "User's last name",
      "event_name": "Name of the event",
      "confirmation_url": "URL for confirmation"
    }
    ```

#### Timestamps
- **`created_at`** (datetime): Template creation
- **`updated_at`** (datetime): Last modification

---

### Audit Log Fields

#### Core Identity
- **`id`** (int, PK): Unique log entry ID
- **`user_id`** (int, FK, optional): User who performed action

#### Action Details
- **`action`** (string): Action performed
  - Examples: `"login"`, `"create_participant"`, `"assign_vpn"`, `"send_email"`
- **`resource_type`** (string): Type of resource affected
  - Examples: `"user"`, `"event"`, `"vpn_credential"`, `"email"`
- **`resource_id`** (int, optional): ID of affected resource

#### Context
- **`ip_address`** (string): IP address of request
- **`user_agent`** (string, optional): Browser/client user agent
- **`details`** (JSON): Additional action-specific details
  - Example for email send:
    ```json
    {
      "template": "invitation",
      "recipient_email": "user@example.com",
      "status": "sent"
    }
    ```

#### Timestamp
- **`created_at`** (datetime): When action occurred

---

## Webhook Endpoints

### Overview

The system provides webhooks for external service integration. All webhook endpoints are located at `/api/webhooks/`.

### SendGrid Email Events

**Endpoint:** `POST /api/webhooks/sendgrid`

Receives email event notifications from SendGrid.

#### Event Types

| Event Type | Description | Action Taken |
|------------|-------------|--------------|
| `processed` | Email accepted by SendGrid | Log to EmailEvent |
| `delivered` | Email delivered to recipient | Update EmailQueue.status to SENT |
| `open` | Recipient opened email | Log to EmailEvent |
| `click` | Recipient clicked link | Log to EmailEvent |
| `bounce` | Email bounced (hard bounce) | Set User.email_status = BOUNCED |
| `dropped` | Email dropped by SendGrid | Log to EmailEvent |
| `spamreport` | Marked as spam by recipient | Set User.email_status = SPAM_REPORTED |
| `unsubscribe` | User unsubscribed | Set User.email_status = UNSUBSCRIBED |
| `deferred` | Delivery temporarily deferred | Log to EmailEvent |

#### Webhook Payload Example

```json
[
  {
    "email": "user@example.com",
    "event": "delivered",
    "timestamp": 1643723400,
    "smtp-id": "<message-id@sendgrid.net>",
    "sg_message_id": "filter-123.456.789.0",
    "category": ["invitation"],
    "user_id": 123
  }
]
```

#### Configuration

1. Log into SendGrid dashboard
2. Navigate to Settings → Mail Settings → Event Webhook
3. Set webhook URL: `https://your-domain.com/api/webhooks/sendgrid`
4. Enable events: delivered, open, click, bounce, spam_report, unsubscribe
5. **Enable Signature Verification** (recommended for production):
   - Toggle "Signature Verification" to ON
   - Copy the "Verification Key" (public key)
   - Add to your `.env` file: `SENDGRID_WEBHOOK_VERIFICATION_KEY=<verification-key>`
   - This uses HMAC-SHA256 to verify webhook authenticity and prevent tampering
6. Click "Test Your Integration" to verify webhook is working

---

### SendGrid Inbound Email

**Endpoint:** `POST /api/webhooks/sendgrid/inbound`

Handles incoming email replies (currently stubbed for future implementation).

**Use Cases:**
- Email reply processing
- Auto-response handling
- Support ticket creation

---

### Discord Integration

**Endpoint:** `POST /api/webhooks/discord`

Receives Discord server events.

#### Supported Events

- `GUILD_MEMBER_ADD`: New member joined Discord server
- `GUILD_MEMBER_REMOVE`: Member left Discord server

**Future Use Cases:**
- Auto-invite Discord users to CyberX events
- Sync Discord roles with participant status
- Send event notifications to Discord channels

---

### Keycloak SSO Events

**Endpoint:** `POST /api/webhooks/keycloak`

Receives Keycloak authentication events.

#### Supported Events

- `LOGIN`: User logged in via SSO
- `REGISTER`: New user registered via SSO

**Future Use Cases:**
- Auto-create participant records from SSO
- Sync user attributes
- Track SSO login activity

---

### Health Check

**Endpoint:** `GET /api/webhooks/health`

Returns status of all webhook integrations.

**Response:**
```json
{
  "status": "healthy",
  "webhooks": {
    "sendgrid": "configured",
    "discord": "available",
    "keycloak": "available"
  },
  "timestamp": "2026-02-05T18:00:00Z"
}
```

---

## Workflow System

### Email Workflow Architecture

```mermaid
flowchart TD
    A[Trigger Event Occurs] --> B{Workflow Enabled?}
    B -->|No| Z[End]
    B -->|Yes| C{Test Mode?}
    C -->|Yes| D{User is Sponsor?}
    D -->|No| Z
    D -->|Yes| E[Get Workflow Config]
    C -->|No| E
    E --> F[Merge Custom Variables]
    F --> G{Delay Configured?}
    G -->|Yes| H[Calculate scheduled_for]
    G -->|No| I[Set scheduled_for = now]
    H --> J[Check for Duplicates]
    I --> J
    J --> K{Duplicate Found?}
    K -->|Yes| L{Force Send?}
    L -->|No| Z
    L -->|Yes| M[Enqueue Email]
    K -->|No| M
    M --> N[Log to Audit]
    N --> O[Background Processor]
    O --> P[Send via SendGrid]
    P --> Q[Update Status]
    Q --> R[Webhook Confirms Delivery]
```

### Workflow Trigger Events

#### User Lifecycle
- **`user_created`**: New user account created
  - **Default Template**: Welcome email with credentials
  - **Variables**: `first_name`, `last_name`, `email`, `pandas_username`, `pandas_password`, `login_url`

- **`user_confirmed`**: User confirmed event participation
  - **Default Template**: Confirmation acknowledgment
  - **Variables**: `first_name`, `last_name`, `event_name`, `event_start_date`

- **`user_activated`**: User account activated
- **`user_deactivated`**: User account deactivated

#### Credentials & Access
- **`password_reset`**: Password reset initiated
  - **Default Template**: Password reset link
  - **Note**: Password reset flow is handled through the portal; specific template variables depend on implementation

- **`vpn_assigned`**: VPN credential assigned to user
  - **Status**: Trigger event defined but **not automatically fired**
  - **Reason**: VPN configs are accessed via portal (self-service download)
  - **Manual Option**: Admins can manually send VPN config emails if needed via admin panel
  - **Note**: VPN configs are typically downloaded directly from portal, not emailed

#### Event Participation
- **`participation_confirmed`**: User confirmed event participation
  - **Default Template**: Event confirmation
  - **Variables**: `event_name`, `start_date`, `location`, `event_time`

- **`event_reminder`**: Event reminder scheduled
  - **Default Template**: Reminder to confirm/prepare
  - **Variables**: `days_until_event`, `event_name`

- **`event_started`**: Event has started
- **`event_ended`**: Event has ended

#### Admin Actions
- **`bulk_invite`**: Bulk invitation sent
  - **Default Template**: Event invitation
  - **Variables**: `first_name`, `last_name`, `email`, `event_name`, `event_date_range`, `event_start_date`, `event_time`, `event_location`, `days_until_event`, `confirmation_url`

- **`custom_email`**: Admin-triggered custom email
  - **Variables**: User-defined

### Workflow Configuration Example

```json
{
  "name": "invitation_workflow",
  "trigger_event": "bulk_invite",
  "template_name": "event_invitation",
  "priority": 5,
  "delay_minutes": 0,
  "is_enabled": true,
  "custom_vars": {
    "sender_name": "CyberX Operations Team",
    "reply_to": "noreply@cyberx.com"
  }
}
```

### Email Queue Processing

```mermaid
sequenceDiagram
    participant T as Trigger Event
    participant W as WorkflowService
    participant Q as EmailQueueService
    participant D as Database
    participant B as Background Processor
    participant S as SendGrid

    T->>W: trigger_workflow(event, user_id)
    W->>D: Get enabled workflows for event
    D-->>W: Workflow configs

    loop For each workflow
        W->>W: Check test mode restrictions
        W->>W: Merge custom variables
        W->>Q: enqueue_email(user, template, vars)
        Q->>D: Check for duplicates
        alt Duplicate found
            D-->>Q: Existing email
            Q-->>W: Skip (duplicate)
        else No duplicate
            Q->>D: INSERT into email_queue
            D-->>Q: Queue entry created
            Q-->>W: Queued successfully
        end
    end

    Note over B: Every 15 minutes
    B->>D: SELECT pending emails (batch_size=50)
    D-->>B: Email batch

    loop For each email
        B->>S: Send email via API
        S-->>B: Success/Failure
        alt Success
            B->>D: UPDATE status='sent'
        else Failure
            B->>D: UPDATE attempts++, error_message
        end
    end

    B->>D: INSERT email_batch_log

    Note over S: Event occurs
    S->>W: POST /webhooks/sendgrid
    W->>D: INSERT email_event
    alt Event is 'delivered'
        W->>D: UPDATE email_queue.status='sent'
    else Event is 'bounce'
        W->>D: UPDATE user.email_status='BOUNCED'
    end
```

---

## Email Management

### Email Template System

#### Template Variables

Common variables available in all templates:

| Variable | Description | Example |
|----------|-------------|---------|
| `first_name` | User's first name | "John" |
| `last_name` | User's last name | "Doe" |
| `email` | User's email address | "john@example.com" |
| `event_name` | Current event name | "CyberX 2026" |

Event-specific variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `event_date_range` | Formatted date range | "June 1-7, 2026" |
| `event_start_date` | Event start date formatted | "June 1, 2026" |
| `event_time` | Event time description | "Doors open 18:00 UTC" |
| `event_location` | Event location | "Austin, TX" |
| `days_until_event` | Days until start | "45" |

Credential variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `pandas_username` | Pandas system username | "johndoe" |
| `pandas_password` | Pandas system password | "SecurePass123!" |
| `confirmation_url` | Confirmation URL with unique token | "https://app.cyberx.com/confirm?code=abc123xyz..." |
| `login_url` | Portal login URL | "https://app.cyberx.com/login" |

**Note:** VPN configurations are accessed via the portal's self-service download feature, not emailed to users.

#### Template Syntax

Templates use Jinja2 syntax:

```html
<h1>Welcome {{ first_name }} {{ last_name }}!</h1>

<p>You've been invited to {{ event_name }}.</p>

{% if event_location %}
<p>Location: {{ event_location }}</p>
{% endif %}

<p>Event dates: {{ event_date_range }}</p>

<p>Confirm your attendance:
  <a href="{{ confirmation_url }}">Click Here</a>
</p>
```

### Email Queue Management

#### Queue Priorities

- **Priority 1**: Critical emails (password resets, urgent notifications)
- **Priority 2-4**: Important emails (confirmations, VPN configs)
- **Priority 5**: Standard emails (invitations, reminders)
- **Priority 6-10**: Low priority (surveys, follow-ups)

#### Batch Processing

- **Batch Size**: 50 emails per batch
- **Frequency**: Every 15 minutes
- **Rate Limiting**: Respects SendGrid API limits
- **Retry Logic**: Up to 3 attempts with exponential backoff

#### Duplicate Prevention

The system prevents duplicate emails:

1. **PENDING check**: Blocks duplicate queue entries for same user+template
2. **24-hour check**: Prevents resending recently sent emails
3. **Force flag**: Admins can bypass 24-hour protection

#### Queue Statistics

Available metrics:
- Total pending emails
- Emails sent in last 24 hours
- Failed email count
- Average send time
- Queue processing rate

---

## VPN Credential Management

### VPN Lifecycle

```mermaid
flowchart LR
    A[Import ZIP File] --> B[Parse Configs]
    B --> C[Extract IP Addresses]
    C --> D[Store in Database]
    D --> E{Assignment Method}
    E -->|Manual| F[Admin Assigns to User]
    E -->|Bulk| G[CSV/Batch Assignment]
    E -->|Request| H[User Requests VPN]
    F --> I[Generate WireGuard Config]
    G --> I
    H --> I
    I --> J[Email Config to User]
    J --> K[Audit Log Created]
```

### WireGuard Configuration Format

Generated configuration example:

```ini
[Interface]
PrivateKey = yAnz5TF+lXXJte14tji3zlMNftft3UL4DigaVcq+rFc=
Address = 10.20.200.149/32, fd00:a:14:c8:95::95/128, fd00:a:14:c8:95:ffff:a14:c895/128
DNS = 1.1.1.1, 1.0.0.1

[Peer]
PublicKey = HIgo9xNzJMWLKASShiTqIybxZ0U3wGLiUeJ1PKf8ykw=
PresharedKey = FJHcW/9mYm6ktw9pT9wEFKEGWvB5N9RlNkUSoqy3ykw=
Endpoint = 216.208.235.11:51020
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
```

### IP Address Management

#### IPv4 Allocation
- **Format**: `10.20.200.X`
- **Range**: Varies by import
- **CIDR**: /32 (single IP)

#### IPv6 Allocation
- **Local Address**: `fd00:a:14:c8:95::XX`
  - Private IPv6 range
  - Used for local network
- **Global Address**: `fd00:a:14:c8:95:ffff:a14:c8XX`
  - Globally routable
  - Unique per user

### VPN Request Flow

```mermaid
sequenceDiagram
    participant U as User
    participant P as Portal
    participant A as API
    participant D as Database
    participant E as Email Service

    U->>P: Click "Request VPN"
    P->>A: POST /api/vpn/request
    A->>A: Verify user eligibility
    A->>A: Check event.vpn_available
    A->>D: Find unassigned credential
    D-->>A: VPN credential
    A->>D: Assign to user
    A->>A: Generate WireGuard config
    A->>E: Send VPN config email
    E->>U: Email with config
    A->>D: Log audit entry
    A-->>P: Success response
    P-->>U: "VPN assigned!"
```

### Bulk VPN Import

1. **Prepare ZIP File**: Contains WireGuard `.conf` files
2. **Upload**: Admin uploads via `/api/vpn/import`
3. **Parse**: Extract private key, preshared key, IPs
4. **Validate**: Check for duplicates, valid format
5. **Store**: Save to `vpn_credentials` table
6. **Report**: Return import statistics

Import response example:
```json
{
  "success": true,
  "imported_count": 150,
  "skipped_count": 5,
  "skipped_reasons": [
    "Duplicate IP: 10.20.200.100"
  ]
}
```

---

## Event Lifecycle

### Event States

```mermaid
stateDiagram-v2
    [*] --> Created
    Created --> Configured: Add details
    Configured --> TestMode: Enable test_mode
    TestMode --> Active: Disable test_mode & activate
    Configured --> Active: Activate
    Active --> Archived: Archive
    Archived --> [*]

    Active --> Active: Update settings
    TestMode --> TestMode: Test workflows

    note right of TestMode
        Only sponsors receive emails
        Can test VPN assignment
        Can verify workflows
    end note

    note right of Active
        All participants can register
        Invitations sent
        VPN requests enabled
    end note
```

### Event Activation Workflow

```mermaid
flowchart TD
    A[Admin Activates Event] --> B{registration_open?}
    B -->|No| C[Set is_active=true]
    B -->|Yes| D{test_mode?}

    C --> Z[Event Active]

    D -->|Yes| E[Queue Emails for Sponsors Only]
    D -->|No| F[Queue Emails for All Invitees]

    E --> G[Schedule Invitation Workflow]
    F --> G

    G --> H[Wait 30 seconds]
    H --> I[Trigger Bulk Invite Event]
    I --> J[Email Queue Processes Invitations]
    J --> K[SendGrid Sends Emails]
    K --> L[Webhooks Track Delivery]
    L --> Z
```

### Event Timeline

```mermaid
gantt
    title Event Lifecycle Timeline
    dateFormat YYYY-MM-DD
    section Planning
    Create Event           :a1, 2026-01-01, 30d
    Configure Details      :a2, after a1, 15d
    section Testing
    Enable Test Mode       :b1, 2026-02-15, 14d
    Test Workflows         :b2, after b1, 7d
    section Registration
    Open Registration      :c1, 2026-03-01, 60d
    Send Invitations       :c2, 2026-03-01, 1d
    Reminder 1 (7 days)    :c3, 2026-03-08, 1d
    Reminder 2 (14 days)   :c4, 2026-03-15, 1d
    Final Reminder (3 days before) :c5, 2026-04-27, 1d
    Close Registration     :c6, 2026-04-30, 1d
    section Event
    Event Runs             :d1, 2026-06-01, 7d
    section Cleanup
    Archive Event          :e1, 2026-06-15, 1d
```

### Event Invitation Workflow

The invitation workflow is triggered automatically when an event is activated with `registration_open = true`. Understanding this flow is critical for successful event launches.

#### Invitation Flow Diagram

```mermaid
flowchart TD
    A[Admin Updates Event Settings] --> B{is_active changed<br/>from false to true?}
    B -->|No| Z[No invitations sent]
    B -->|Yes| C{registration_open = true?}
    C -->|No| Z
    C -->|Yes| D[Activation Detected]

    D --> E[Schedule Invitation Job]
    E --> F[Wait 30 seconds]
    F --> G{test_mode enabled?}

    G -->|Yes| H[Query Sponsors Only]
    G -->|No| I[Query All Invitees]

    H --> J{Filter: confirmation_sent_at IS NULL}
    I --> J

    J --> K[Build Recipient List]
    K --> L{Any recipients?}
    L -->|No| M[Log: No new invitations needed]
    L -->|Yes| N[For Each Recipient]

    N --> O[Trigger bulk_invite Workflow]
    O --> P[EmailQueueService.enqueue_email]
    P --> Q[Check Duplicate Protection]
    Q --> R{Duplicate?}
    R -->|Yes| S[Skip User]
    R -->|No| T[Add to Queue]

    S --> U{More recipients?}
    T --> U
    U -->|Yes| N
    U -->|No| V[Update confirmation_sent_at]
    V --> W[Log Invitation Batch]
    W --> X[Background Processor Sends Emails]
    X --> Y[Invitations Delivered]
```

#### How Event Activation Triggers Invitations

**Trigger Conditions (ALL must be true):**
1. `event.is_active` changes from `false` → `true` (or is updated while already true)
2. `event.registration_open = true`
3. Event update operation completes successfully

**What Happens Next:**
1. **Immediate**: Event activation is saved to database
2. **30 seconds later**: Invitation email job executes
3. **Recipient Query**: System finds users to invite
4. **Queue Emails**: Each user's invitation is queued
5. **Background Processing**: Batch processor sends emails (runs every 15 minutes)

#### Test Mode vs Production Mode

**Test Mode (`test_mode = true`):**
```sql
-- Only sponsors receive invitations
SELECT * FROM users
WHERE (role = 'sponsor' OR is_sponsor = true)
  AND confirmation_sent_at IS NULL
  AND email_status NOT IN ('BOUNCED', 'SPAM_REPORTED', 'UNSUBSCRIBED')
```

**Production Mode (`test_mode = false`):**
```sql
-- All invitees and sponsors receive invitations
SELECT * FROM users
WHERE (role IN ('invitee', 'sponsor'))
  AND confirmation_sent_at IS NULL
  AND email_status NOT IN ('BOUNCED', 'SPAM_REPORTED', 'UNSUBSCRIBED')
```

#### Which Roles Receive Invitations

The system uses the `role` field (and legacy `is_sponsor` flag) to determine invitation recipients:

**User Roles in Database:**
- **`admin`**: System administrators
- **`sponsor`**: Users who can sponsor and manage invitees
- **`invitee`**: Invited participants

**Invitation Rules by Mode:**

**Test Mode Recipients (`test_mode = true`):**
- ✅ **Sponsors only** (`role = 'sponsor'` OR `is_sponsor = true`)
- ❌ **Invitees excluded** (`role = 'invitee'`)
- ❌ **Admins excluded** (`role = 'admin'`)

**Production Mode Recipients (`test_mode = false`):**
- ✅ **Sponsors** (`role = 'sponsor'`)
- ✅ **Invitees** (`role = 'invitee'`)
- ❌ **Admins excluded** (`role = 'admin'`)

**Why Admins Don't Receive Invitations:**
- Admins manage the system but are not event participants by design
- Admins have full portal access without needing invitation/confirmation
- **Admins cannot go through the normal confirmation flow** (no invite = no confirmation link)
- **If an admin should participate as an attendee**, they must have a separate account with `invitee` or `sponsor` role

**Important Architectural Note:**
The invitation/confirmation system is designed for participant management, not admin access. Admins bypass this flow entirely. This means:
- ✅ Admins can manage events, users, and view all data
- ❌ Admins cannot confirm participation (no EventParticipation record created)
- ❌ Admins don't appear in participant statistics or attendance tracking
- ❌ Admins won't receive event-related emails (invitations, reminders, confirmations)

**Best Practice for Admin Participation:**
If a person needs both admin capabilities AND event participation:
1. Create admin account: `admin@example.com` with `role = 'admin'`
2. Create separate participant account: `admin.participant@example.com` with `role = 'invitee'` or `'sponsor'`
3. Use admin account for system management
4. Use participant account for event confirmation, VPN requests, etc.

**Role Assignment:**
- **Sponsors**: Manually assigned via admin panel or bulk import with `role = 'sponsor'`
- **Invitees**: Default role for new participants created by sponsors or bulk import
- **Admins**: Bootstrap admin or manually promoted via database/admin panel

**Legacy `is_sponsor` Flag:**
- Older field that marks sponsor users (boolean)
- Query checks both `role = 'sponsor'` OR `is_sponsor = true` for compatibility
- New users should use `role` field instead
- Will be deprecated in future versions

**Key Differences:**

| Feature | Test Mode | Production Mode |
|---------|-----------|-----------------|
| **Invitation Recipients** | Sponsors only (`role = 'sponsor'`) | Invitees + Sponsors (`role IN ('invitee', 'sponsor')`) |
| **Admin Users** | Not invited | Not invited |
| **VPN Requests** | Sponsors only | All confirmed users (invitees + sponsors) |
| **Email Workflows** | Sponsors only | All users (invitees + sponsors) |
| **Portal Access** | All roles (limited for invitees) | All roles (full access for confirmed users) |
| **Invitation Count** | ~5-20 (sponsors) | 100-500+ (all invitees + sponsors) |
| **Purpose** | Pre-launch validation | Actual event invitations |
| **Recommended For** | Testing workflows, email templates, VPN flow | Live event registration |

#### Practical Example: Role-Based Invitation Filtering

**Scenario**: Event database contains:
- 3 admin users (`role = 'admin'`)
- 10 sponsor users (`role = 'sponsor'`)
- 200 invitee users (`role = 'invitee'`)
- Total: 213 users

**Event Activation in Test Mode:**
```
Admin activates event with:
- is_active = true
- registration_open = true
- test_mode = true

Result:
✅ 10 sponsors receive invitation emails
❌ 200 invitees do NOT receive emails
❌ 3 admins do NOT receive emails
Total emails sent: 10
```

**Event Activation in Production Mode:**
```
Admin changes settings to:
- is_active = true
- registration_open = true
- test_mode = false

Result:
✅ 10 sponsors receive invitation emails*
✅ 200 invitees receive invitation emails
❌ 3 admins do NOT receive emails
Total emails sent: 210

*Note: If sponsors already received invitations in test mode,
they won't receive duplicates (blocked by confirmation_sent_at check)
```

**Why This Matters:**
- **Test mode prevents accidental mass emails** to all invitees during testing
- **Sponsors act as test group** to validate email templates, workflows, and portal
- **Admins are excluded** because they manage the system, not participate in events
- **Role-based filtering is automatic** - no manual selection needed
- **Duplicate protection ensures** sponsors don't get spammed when switching from test to production

#### Duplicate Prevention

The system prevents duplicate invitations:

1. **`confirmation_sent_at` check**: Only users with `NULL` value receive invitations
2. **Email queue duplicate check**: Prevents multiple queue entries for same user+template
3. **24-hour resend protection**: Won't resend if email sent recently (unless forced)

**After invitation sent:**
- User's `confirmation_sent_at` is set to current timestamp
- User won't receive duplicate invitation even if event is activated again
- Admins can manually resend via "Resend Invitation" button (bypasses duplicate protection)

#### Invitation Email Contents

The `bulk_invite` workflow email typically includes:

| Variable | Example Value | Usage |
|----------|---------------|-------|
| `first_name` | "John" | Personalized greeting |
| `last_name` | "Doe" | Personalized greeting |
| `event_name` | "CyberX Red Team Exercise 2026" | Event identification |
| `event_date_range` | "June 1-7, 2026" | Event dates |
| `event_start_date` | "June 1, 2026" | Event start date |
| `event_location` | "Austin, TX" | Location info |
| `event_time` | "Doors open 18:00 UTC" | Timing details |
| `days_until_event` | "45" | Days until event starts |
| `confirmation_url` | "https://app.cyberx.com/confirm?code=abc123xyz..." | Confirmation link with unique token |

#### Common Invitation Workflow Scenarios

**Scenario 1: Initial Event Launch (Production)**
```
1. Admin creates event with test_mode = true
2. Admin tests workflows with sponsors
3. Admin sets: test_mode = false, registration_open = true, is_active = true
4. System sends invitations to ALL invitees (sponsors already received in test)
5. Sponsors receive second invitation (harmless, or can be prevented with confirmation_sent_at check)
```

**Scenario 2: Test-Only Launch**
```
1. Admin creates event: test_mode = true, registration_open = true, is_active = true
2. System sends invitations ONLY to sponsors
3. Sponsors can test confirmation flow, VPN requests, portal access
4. Admin verifies everything works
5. When ready: set test_mode = false
6. System sends invitations to remaining invitees
```

**Scenario 3: Event Re-activation**
```
1. Event was previously active and sent invitations
2. Admin deactivates (is_active = false) for changes
3. Admin makes updates (date changes, location, etc.)
4. Admin re-activates (is_active = true)
5. System checks confirmation_sent_at
6. Only NEW users (added since last activation) receive invitations
7. Existing invitees do NOT receive duplicate emails
```

**Scenario 4: Staggered Registration**
```
1. Event activated with 100 invitees
2. Invitations sent to all 100
3. Admin adds 50 more invitees later
4. Admin can either:
   a. Manually resend individual invitations via admin panel
   b. Toggle is_active off/on to trigger workflow (only new 50 receive emails)
```

### Event Settings Guide

#### When to Use Test Mode

**Enable `test_mode` when:**
- Testing email workflows before launch
- Verifying VPN assignment process
- Checking invitation emails with real sponsors
- Training sponsors on the system
- Ensuring integrations work correctly
- Validating portal functionality

**Test mode restrictions:**
- **Invitations**: Only sponsors receive invitation emails
- **VPN Requests**: Only sponsors can request VPN credentials
- **Email Workflows**: All workflow triggers limited to sponsors
- **Portal Access**: Invitees can log in but most actions blocked
- Perfect for pre-launch validation without spamming invitees

**Recommended Test Mode Workflow:**
1. Create event with `test_mode = true`
2. Set `registration_open = true`
3. Activate event (`is_active = true`)
4. Sponsors receive invitations (5-20 emails)
5. Test confirmation flow, VPN requests, portal
6. Verify email templates look correct
7. Check audit logs for any errors
8. When satisfied, disable test mode (`test_mode = false`)
9. System automatically sends invitations to all remaining invitees

#### When to Open Registration

**Enable `registration_open` when:**
- Event details are finalized
- Terms and conditions are ready
- VPN credentials are imported
- Email templates are tested
- Ready to accept confirmations

**Registration controls:**
- Gates invitation sending
- Controls confirmation flow
- Can be toggled during event lifetime

#### When to Enable VPN Availability

**Enable `vpn_available` when:**
- VPN credentials are imported and assigned
- Network infrastructure is ready
- Event is close to start date
- Users need access for preparation

**Note**: VPN availability is independent of registration status

---

## Background Tasks

### Scheduler Overview

The system uses APScheduler to run background tasks:

```mermaid
flowchart TD
    A[APScheduler] --> B[Email Discovery]
    A --> C[Batch Email Processor]
    A --> D[Invitation Reminders]
    A --> E[Session Cleanup]
    A --> F[Scheduler Heartbeat]

    B -->|Every 2 hours| G[Find Users Needing Credentials]
    C -->|Every 15 minutes| H[Send Queued Emails]
    D -->|Daily| I[Send Reminder Emails]
    E -->|Daily| J[Delete Expired Sessions]
    F -->|Every 60 seconds| K[Update Scheduler Status]
```

### Task Schedules

| Task | Frequency | Purpose | Configuration |
|------|-----------|---------|---------------|
| Batch Processor | Every 15-45 minutes | Send queued emails | `BULK_EMAIL_INTERVAL_MINUTES` |
| Invitation Reminders | Daily (configurable interval) | Send staged reminders | `REMINDER_CHECK_INTERVAL_HOURS` |
| Session Cleanup | Daily at 03:00 UTC | Remove expired sessions | Hardcoded in task |
| Heartbeat | Every 60 seconds | Update scheduler status | Built-in |

### Invitation Reminder System

**Three-Stage Reminder Process:**

```mermaid
flowchart TD
    A[User Invited] --> B{7 Days Passed?}
    B -->|Yes| C{Still No Response?}
    C -->|Yes| D[Send Reminder 1]
    C -->|No| Z[End]

    D --> E{14 Days Passed?}
    E -->|Yes| F{Still No Response?}
    F -->|Yes| G[Send Reminder 2]
    F -->|No| Z

    G --> H{3 Days Before Event?}
    H -->|Yes| I{Still No Response?}
    I -->|Yes| J[Send Final Reminder]
    I -->|No| Z
    J --> Z
```

**Configuration:**
```python
REMINDER_1_DAYS_AFTER_INVITE = 7
REMINDER_2_DAYS_AFTER_INVITE = 14
REMINDER_3_DAYS_BEFORE_EVENT = 3

# Minimum days before event to send reminders
REMINDER_1_MIN_DAYS_BEFORE_EVENT = 21
REMINDER_2_MIN_DAYS_BEFORE_EVENT = 14
```

**Example Timeline:**
- March 1: User invited
- March 8: Reminder 1 sent (7 days after)
- March 15: Reminder 2 sent (14 days after)
- May 28: Final reminder (3 days before June 1 event)

### Batch Email Processor

**Purpose**: Send queued emails in batches

**Process:**
1. Query pending emails (ordered by priority, scheduled_for)
2. Group into batch (max 50)
3. For each email:
   - Build template variables
   - Send via SendGrid
   - Update status
   - Log result
4. Record batch statistics
5. Retry failed emails (up to max_attempts)

**Batch Size Calculation:**
```python
BATCH_SIZE = 50  # SendGrid rate-limit friendly
PROCESSING_TIMEOUT = 300  # 5 minutes max per batch
```

### Scheduler Health Monitoring

**Heartbeat System:**
- Updates `scheduler_status` table every 60 seconds
- Records: service_name, is_running, jobs, last_heartbeat
- Admin dashboard shows scheduler status
- Alerts if heartbeat > 5 minutes old

---

## Common Administrative Tasks

### Creating a New Event

1. **Navigate to Events**: Admin Dashboard → Events → Create Event
2. **Fill Required Fields**:
   - Event Year: `2027`
   - Event Name: `CyberX Red Team Exercise 2027`
   - Slug: Auto-generated or custom (e.g., `cyberx-2027`)
3. **Set Dates**:
   - Start Date: `2027-06-01`
   - End Date: `2027-06-07`
   - Event Time: `Doors open 18:00 UTC`
   - Event Location: `Austin, TX`
4. **Configure Terms**:
   - Terms Version: `2027-v1`
   - Terms Content: Paste markdown terms
5. **Set Initial Status**:
   - ✅ Test Mode: ON (for testing)
   - ❌ Is Active: OFF
   - ❌ Registration Open: OFF
   - ❌ VPN Available: OFF
6. **Save Event**

### Activating an Event

**Pre-activation Checklist:**
- [ ] Event details are complete
- [ ] Terms and conditions finalized
- [ ] Email templates tested
- [ ] VPN credentials imported
- [ ] Test mode workflows verified
- [ ] Sponsors notified of launch

**Activation Steps:**
1. Disable test mode: `test_mode = false`
2. Enable registration: `registration_open = true`
3. Activate event: `is_active = true`
4. System automatically:
   - Queues invitation emails
   - Triggers bulk_invite workflow
   - Sends emails within 30 seconds
   - Logs activation to audit

### Managing Participants

#### Adding Individual Participant

1. Navigate to Admin → Participants → Add Participant
2. Fill details:
   - Email: `user@example.com`
   - First Name: `John`
   - Last Name: `Doe`
   - Country: `USA`
   - Role: `INVITEE`
   - Sponsor: Select sponsor (if invitee)
3. System automatically:
   - Generates confirmation code
   - Sets confirmed = 'UNKNOWN'
   - Creates event participation record
   - Queues invitation email (if event is active)

#### Bulk Import Participants

1. Prepare CSV file:
   ```csv
   email,first_name,last_name,country,role,sponsor_email
   user1@example.com,John,Doe,USA,INVITEE,sponsor@example.com
   user2@example.com,Jane,Smith,GBR,INVITEE,sponsor@example.com
   ```
2. Navigate to Admin → Participants → Bulk Import
3. Upload CSV file
4. Review preview
5. Confirm import
6. System processes:
   - Creates user records
   - Assigns sponsors
   - Generates confirmation codes
   - Queues invitation emails

#### Resetting Password

1. Navigate to Participant Details
2. Click "Reset Password"
3. System:
   - Generates random secure password
   - Updates pandas_password
   - Queues password email
   - Logs action to audit

### Managing VPN Credentials

#### Importing VPN Credentials

1. Prepare ZIP file with WireGuard configs
2. Navigate to Admin → VPN → Import Credentials
3. Upload ZIP file
4. Select key type: `cyber` or `kinetic`
5. System parses and stores:
   - Private keys
   - Preshared keys (if present)
   - IP addresses (IPv4, IPv6)
   - Endpoint information
6. Review import report

#### VPN Assignment Methods

**Method 1: Self-Service (Recommended)**
- Users request VPN via portal: "Request VPN" button
- System automatically assigns available credential
- User immediately downloads config from portal
- No email needed - instant access

**Method 2: Admin Assignment (Optional)**
- Navigate to Admin → VPN → Assign
- Select user and credential
- System assigns credential
- User downloads from portal
- Admin can manually email config if needed

**Bulk Assignment (Admin Only):**
1. Navigate to VPN → Bulk Assign
2. Upload CSV:
   ```csv
   user_email,vpn_ip
   user@example.com,10.20.200.149
   ```
3. System matches and assigns
4. Users download from portal

**Note:** VPN config emails are **manual only** - the system does not automatically email configs. Users access their VPN configs instantly through the portal.

### Managing Email Templates

#### Creating Email Template

1. Navigate to Admin → Email → Templates → Create
2. Fill details:
   - Name: `custom_invite` (no spaces)
   - Subject: `You're Invited to {{ event_name }}`
   - HTML Content: Paste template
3. Document available variables:
   ```json
   {
     "first_name": "User's first name",
     "last_name": "User's last name",
     "email": "User's email",
     "event_name": "Name of event",
     "event_date_range": "Event date range",
     "confirmation_url": "URL for confirmation"
   }
   ```
4. Test template with preview
5. Save template

#### Creating Email Workflow

1. Navigate to Admin → Email → Workflows → Create
2. Configure:
   - Name: `welcome_workflow`
   - Trigger Event: `user_created`
   - Template: `custom_invite`
   - Priority: `5`
   - Delay: `0` minutes (immediate)
   - Enabled: ✅
3. Set custom variables (optional):
   ```json
   {
     "sender_name": "CyberX Operations",
     "support_email": "support@cyberx.com"
   }
   ```
4. Save workflow

### Sending Bulk Emails

#### Method 1: Using Workflows (Recommended)

1. Create/enable workflow for desired trigger
2. Trigger event (e.g., activate event)
3. System automatically queues emails
4. Background processor sends in batches

#### Method 2: Manual Bulk Send

1. Navigate to Admin → Email → Send Bulk Email
2. Select template
3. Choose recipients:
   - All users
   - By role
   - By confirmation status
   - By country
   - Custom filter
4. Preview email
5. Confirm send
6. System queues all emails
7. Monitor queue status

### Viewing Audit Logs

1. Navigate to Admin → Audit Logs
2. Filter by:
   - User
   - Action type
   - Resource type
   - Date range
3. Export to CSV for analysis

Common audit queries:
- Who assigned VPN credentials?
- When were invitations sent?
- Password reset activity
- Login attempts

---

## Troubleshooting

### Common Issues

#### Emails Not Sending

**Symptoms**: Emails stuck in PENDING status

**Checks:**
1. Verify scheduler is running: Admin → Scheduler Status
2. Check last heartbeat < 5 minutes ago
3. Review email queue: Admin → Email Queue
4. Check SendGrid API key: Settings → Email
5. Review error messages in queue entries

**Solutions:**
- Restart scheduler if heartbeat stale
- Manually trigger batch processor
- Check SendGrid account status
- Review API key permissions
- Check for rate limiting

#### User Can't Log In

**Symptoms**: Login fails with "Invalid credentials"

**Checks:**
1. Verify user email is correct
2. Check user.is_active = true
3. Confirm password_hash exists
4. Check confirmation_code if new user
5. Review audit logs for login attempts

**Solutions:**
- Reset password via Admin → Participant → Reset Password
- Activate account if disabled
- Resend confirmation email
- Check for email typos

#### User Can't Access VPN Config

**Symptoms**: User says they can't find their VPN config

**Checks:**
1. Verify VPN credential is assigned: Admin → Participants → User → VPN Tab
2. Check user can log into portal
3. Verify event.vpn_available is enabled (or test_mode for sponsors)
4. Check if credential exists in database

**Solutions:**
- **Primary**: Direct user to portal VPN section for instant download
- If not assigned: User can request via "Request VPN" button (self-service)
- If request fails: Check if VPN pool has available credentials
- **Optional**: Admin can manually email config via Email → Send VPN Config (rarely needed)

#### Invitation Emails Not Triggered

**Symptoms**: Event activated but no invitations sent

**Checks:**
1. Verify event.is_active = true
2. Check event.registration_open = true
3. Confirm workflow exists for bulk_invite trigger
4. Review email queue for pending emails
5. Check test_mode setting

**Solutions:**
- Enable registration if closed
- Create bulk_invite workflow if missing
- Disable test_mode for production
- Manually trigger invitation workflow
- Check scheduler is running

#### User Not Receiving Invitation (Role Issues)

**Symptoms**: Specific user not receiving invitation email despite event activation

**Common Causes & Solutions:**

1. **User has wrong role**
   - **Check**: View user in admin panel → verify `role` field
   - **Problem**: User has `role = 'admin'` (admins never receive invitations)
   - **Solution Options**:
     - **Recommended**: Create a separate participant account with `invitee` or `sponsor` role
     - **Alternative**: Change existing admin role to `invitee` (loses admin privileges)
     - **Not Recommended**: Manually create EventParticipation record (bypasses invitation system)

2. **Test mode is enabled**
   - **Check**: Event settings → `test_mode` status
   - **Problem**: User is invitee but test_mode = true (only sponsors receive invitations)
   - **Solution**: Either disable test_mode OR temporarily change user to sponsor for testing

3. **User already received invitation**
   - **Check**: User record → `confirmation_sent_at` field
   - **Problem**: Field has timestamp (user was already invited)
   - **Solution**: Use "Resend Invitation" button to bypass duplicate protection

4. **User email status is blocked**
   - **Check**: User record → `email_status` field
   - **Problem**: Status is BOUNCED, SPAM_REPORTED, or UNSUBSCRIBED
   - **Solution**: Update email address, verify it's valid, reset status to VALID

**SQL Query to Check User Status:**
```sql
SELECT
    id,
    email,
    role,
    confirmation_sent_at,
    email_status,
    CASE
        WHEN role = 'admin' THEN 'Admins never receive invitations'
        WHEN confirmation_sent_at IS NOT NULL THEN 'Already invited'
        WHEN email_status IN ('BOUNCED', 'SPAM_REPORTED', 'UNSUBSCRIBED') THEN 'Email blocked'
        WHEN role NOT IN ('sponsor', 'invitee') THEN 'Invalid role for invitations'
        ELSE 'Should receive invitation'
    END as invitation_status
FROM users
WHERE email = 'user@example.com';
```

**Role Assignment Quick Fix:**
```sql
-- Change admin to invitee (if they should participate)
UPDATE users SET role = 'invitee' WHERE email = 'admin@example.com';

-- Change invitee to sponsor (for test mode access)
UPDATE users SET role = 'sponsor' WHERE email = 'user@example.com';

-- Reset confirmation_sent_at to allow re-invitation
UPDATE users SET confirmation_sent_at = NULL WHERE email = 'user@example.com';
```

#### Admin Wants to Participate in Event

**Symptoms**: Admin user needs to attend event but can't receive invitation or confirm participation

**Problem**: Admins are excluded from invitation workflow by design. The `role = 'admin'` prevents:
- Receiving invitation emails
- Accessing confirmation links
- Creating EventParticipation records
- Appearing in participant lists/statistics
- Requesting VPN credentials via normal flow

**Solution Options:**

**Option 1: Create Separate Participant Account (Recommended)**
```sql
-- Create a new participant account for the admin
INSERT INTO users (email, first_name, last_name, country, role, password_hash, is_active, confirmed)
VALUES (
    'admin.participant@example.com',  -- Different email
    'John',
    'Doe',
    'USA',
    'invitee',  -- or 'sponsor' if they need to sponsor others
    '<password_hash>',  -- Use hash_password() function
    true,
    'UNKNOWN'
);
```
- Admin uses `admin@example.com` for system management
- Admin uses `admin.participant@example.com` for event participation
- Keeps admin and participant roles separate and clean

**Option 2: Temporarily Change Role (Not Recommended)**
```sql
-- Change admin to invitee for event duration
UPDATE users SET role = 'invitee' WHERE email = 'admin@example.com';

-- After event, change back to admin
UPDATE users SET role = 'admin' WHERE email = 'admin@example.com';
```
- ⚠️ **Warning**: User loses admin access while role is 'invitee'
- Can't manage event while participating
- Risk of forgetting to restore admin role

**Option 3: Manual EventParticipation Record (Advanced)**
```sql
-- Manually create participation record (bypasses invitation system)
INSERT INTO event_participations (user_id, event_id, status, invited_at, confirmed_at)
SELECT
    u.id,
    e.id,
    'confirmed',
    NOW(),
    NOW()
FROM users u, events e
WHERE u.email = 'admin@example.com'
  AND e.slug = 'cyberx-red-team-exercise-2026';
```
- ⚠️ **Warning**: Bypasses normal workflow and validations
- No invitation email sent (user won't have confirmation link in email)
- No audit trail of invitation
- Only use if you understand the implications

**Recommended Approach**: Always use Option 1 (separate accounts) for production systems. This maintains clear separation between administrative and participant roles.

#### Duplicate Emails Being Sent

**Symptoms**: Users receive multiple identical emails

**Checks:**
1. Review email queue for duplicates
2. Check workflow configuration
3. Verify duplicate protection is working
4. Review audit logs for manual sends

**Solutions:**
- Enable 24-hour duplicate protection
- Disable duplicate workflows
- Set force_send = false
- Review admin actions

### Error Messages

#### "Email already in queue for this user and template"

**Meaning**: Duplicate protection blocked email

**Action**: Wait for pending email to process, or use force_send flag

#### "No VPN credentials available"

**Meaning**: All credentials assigned or no credentials imported

**Action**: Import new credentials or unassign unused ones

#### "User email status is BOUNCED"

**Meaning**: Previous email bounced, account flagged

**Action**: Update email address, verify it's valid, reset status to VALID

#### "Event registration is closed"

**Meaning**: Trying to send invitations with registration_open = false

**Action**: Enable registration: Event Settings → Registration Open

#### "Test mode is enabled - operation restricted to sponsors"

**Meaning**: Non-sponsor trying to act while test_mode = true

**Action**: Disable test mode or wait for production launch

### Performance Issues

#### Slow Email Sending

**Symptoms**: Email queue backing up

**Diagnosis:**
- Check batch size configuration
- Review SendGrid API rate limits
- Check database query performance
- Review scheduler logs

**Solutions:**
- Increase batch processor frequency
- Reduce batch size to avoid timeouts
- Add database indexes
- Optimize email templates

#### Database Slow Queries

**Common Slow Queries:**
- Large email queue queries
- Event participation with statistics
- User listing with filters

**Solutions:**
- Add indexes on frequently filtered columns
- Implement query result caching
- Archive old events
- Paginate large result sets

### Data Integrity Issues

#### Orphaned VPN Credentials

**Issue**: VPN assigned but user deleted

**Fix:**
```sql
UPDATE vpn_credentials
SET assigned_to_user_id = NULL,
    assigned_at = NULL
WHERE assigned_to_user_id NOT IN (SELECT id FROM users);
```

#### Missing Event Participations

**Issue**: User exists but no event participation record

**Fix**: Create participation record via Admin → Participants → Edit → Add to Event

#### Inconsistent Email Status

**Issue**: Email marked SENT but webhook shows bounce

**Fix**: Run status sync job or manually update based on webhook events

---

## Appendix

### Environment Variables Reference

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname

# SendGrid
SENDGRID_API_KEY=SG.xxx
SENDGRID_FROM_EMAIL=noreply@cyberx.com
SENDGRID_FROM_NAME=CyberX Red Team
SENDGRID_SANDBOX_MODE=false
SENDGRID_WEBHOOK_VERIFICATION_KEY=your-verification-key-from-sendgrid

# Application
SECRET_KEY=your-secret-key-here
CSRF_SECRET_KEY=your-csrf-key-here
ENCRYPTION_KEY=your-fernet-key-here
SESSION_EXPIRY_HOURS=72

# Email Processing
BULK_EMAIL_INTERVAL_MINUTES=15

# Reminders
REMINDER_CHECK_INTERVAL_HOURS=24
REMINDER_1_DAYS_AFTER_INVITE=7
REMINDER_2_DAYS_AFTER_INVITE=14
REMINDER_3_DAYS_BEFORE_EVENT=3

# Bootstrap Admin
ADMIN_EMAIL=admin@cyberx.com
ADMIN_PASSWORD=change-me-please

# Frontend
FRONTEND_URL=https://app.cyberx.com

# VPN
VPN_SERVER_PUBLIC_KEY=base64-encoded-key
VPN_SERVER_ENDPOINT=vpn.cyberx.com:51820

# Environment
ENVIRONMENT=production
DEBUG=false
```

### API Endpoints Quick Reference

See [API Routes/Endpoints](#4-api-routesendpoints---backendappapiroutes) section for full list.

### Database Backup Recommendations

1. **Automated Daily Backups**: 3AM UTC
2. **Pre-Event Backups**: Before event activation
3. **Pre-Migration Backups**: Before running migrations
4. **Retention**: 30 days rolling, 1 year for major events

### Security Best Practices

1. **Rotate Keys Regularly**: API keys, encryption keys
2. **Use Strong Passwords**: Enforce password complexity
3. **Enable 2FA**: For admin accounts (future feature)
4. **Monitor Audit Logs**: Weekly review
5. **Review Permissions**: Quarterly sponsor audit
6. **HTTPS Only**: Enforce SSL/TLS
7. **CSRF Protection**: Enabled by default
8. **Rate Limiting**: Configure for API endpoints

### Support Contacts

- **Technical Issues**: Open GitHub issue
- **Security Concerns**: security@cyberx.com
- **Feature Requests**: GitHub discussions

---

**Document Version**: 1.0
**Last Updated**: February 5, 2026
**Maintainer**: CyberX Operations Team
