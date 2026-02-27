# Email Template Variables Guide

## Overview

This document defines where email template variables should be sourced from when building or modifying SendGrid dynamic templates. Variables flow through three layers before reaching SendGrid, each with a specific purpose.

## Variable Sources

### 1. Trigger-Time Code (per-send, computed)

Variables set in the API endpoint or service that fires the email (e.g., `admin.py`). Use this for values that are **derived from the specific action that triggered the email** and would differ for each individual send.

**Rule:** The value is computed from something that only exists at trigger time.

**Examples:**
- `password` — generated at user creation, unique per send
- `role_label`, `role_upper`, `role_display`, `a_or_an` — derived from the role being assigned right now
- `reset_code` — generated token for password reset
- `confirmation_url` — built from a freshly created token

**Where it lives:** The `custom_vars` dict passed to `WorkflowService.trigger_workflow()` in the API route handler.

```python
# backend/app/api/routes/admin.py
await workflow_service.trigger_workflow(
    trigger_event=trigger_event,
    user_id=participant.id,
    custom_vars={
        "first_name": participant.first_name,
        "role_display": "Administrator" if is_admin else "Sponsor",
        "password": temp_password,
        ...
    }
)
```

### 2. Workflow DB `custom_vars` (per-workflow, static config)

Variables stored in the `EmailWorkflow.custom_vars` JSON column in the database. Use this for values that are **the same regardless of which user triggered the email** — configuration that can be set once and updated without a code deploy.

**Rule:** The value would be identical for every send of this workflow.

**Examples:**
- `logo_url` — hosted image URL for the CyberX logo
- `org_address` — "123 Cyber Street, Austin, TX 78701"
- `privacy_url`, `contact_url` — static page links
- `responsibilities` — array of role responsibilities (different per workflow since ADMIN_CREATED and SPONSOR_CREATED are separate workflow rows)
- `assigned_by` — "CyberX Organizers"
- `venue_name`, `venue_address`, `meeting_point`, `directions`, `arrival_time`, `map_url` — venue details for attendance confirmation
- `response_deadline` — RSVP deadline

**Where it lives:** The `custom_vars` JSON column on the `email_workflows` table row, editable via the admin UI or direct DB update.

```json
{
  "logo_url": "https://cdn.example.com/cyberx-logo.png",
  "org_address": "123 Cyber Street, Austin, TX 78701",
  "privacy_url": "https://cyberx.example.com/privacy",
  "contact_url": "https://cyberx.example.com/contact",
  "responsibilities": [
    "Manage participant accounts and access control",
    "Monitor event infrastructure and escalate issues",
    "Coordinate with sponsors and support staff"
  ]
}
```

### 3. Email Service Defaults (per-app, auto-populated)

Variables automatically populated by `EmailService._create_sendgrid_dynamic_template_message()` from the User model and application settings. These apply to every email type and require no manual configuration.

**Rule:** The value comes from the User record or app-wide settings and is needed by most/all templates.

**Examples:**
- `first_name`, `last_name`, `email` — from User model
- `pandas_username`, `pandas_password` — from User model
- `login_url` — built from `settings.FRONTEND_URL`
- `confirmation_url` — built from `settings.FRONTEND_URL` + user's confirmation code
- `survey_url` — built from `settings.FRONTEND_URL`

**Where it lives:** Hard-coded in `email_service.py`, pulled from the User object and app settings at send time.

## Merge Order & Override Precedence

Variables are merged in this order (last write wins):

```
1. Email service defaults     (lowest priority)
2. Workflow DB custom_vars     ↓
3. Trigger-time custom_vars   (highest priority)
```

This is implemented across two merge points:

**First merge** — in `WorkflowService.trigger_workflow()`:
```python
merged_vars = {**(workflow.custom_vars or {}), **(custom_vars or {})}
```
Trigger-time vars override workflow DB defaults.

**Second merge** — in `EmailService._create_sendgrid_dynamic_template_message()`:
```python
dynamic_template_data = {"first_name": user.first_name, ...}  # service defaults
dynamic_template_data.update(custom_vars)  # merged vars override defaults
```

## Decision Checklist

When adding a new template variable, ask:

| Question | Source |
|---|---|
| Does this value change per-send? (e.g., generated password, computed from the triggering action) | Trigger-time code |
| Is this the same for every user who gets this workflow's email? (e.g., logo, address, venue info) | Workflow DB `custom_vars` |
| Is this pulled from the User model or app settings and used across many email types? | Email service defaults |

## Role-Specific Variables

For templates shared across roles (e.g., admin/sponsor account creation), role-derived variables should be set in trigger-time code since the role is determined at the moment the action fires:

```python
ROLE_TEMPLATE_VARS = {
    UserRole.ADMIN.value: {
        "role": "Admin",
        "role_label": "ADMIN",
        "role_upper": "ADMINISTRATOR",
        "role_display": "Administrator",
        "a_or_an": "an",
    },
    UserRole.SPONSOR.value: {
        "role": "Sponsor",
        "role_label": "SPONSOR",
        "role_upper": "SPONSOR",
        "role_display": "Sponsor",
        "a_or_an": "a",
    },
}
```

If additional roles are added, extend this mapping rather than adding more inline ternaries.

## Workflow-Configurable Email Flows

Several email flows use the `EmailWorkflow` table as a config store so that template names and static variables can be changed via the admin UI without a code deploy. Each flow looks up its workflow by trigger event, reads `template_name` and `custom_vars`, and falls back to a hardcoded default if no workflow row exists.

### Bulk Invite

| Trigger Event | Fallback Template | Code |
|---|---|---|
| `bulk_invite` | `sg_test_hacker_theme` | `email_service.py → queue_invitation_email_for_user()` |

Single workflow row. Available variables:

| Variable | Source |
|---|---|
| `first_name`, `last_name`, `email` | Trigger-time (User model) |
| `confirmation_url` | Trigger-time (generated token) |
| `event_name`, `event_date_range`, `event_time`, `event_location` | Trigger-time (`build_event_template_vars()`) |
| `logo_url`, `org_address`, etc. | Workflow DB `custom_vars` |

### Invitation Reminders (3 stages)

Each reminder stage has its own trigger event and workflow row, allowing independent template and variable configuration per stage.

| Stage | Trigger Event | Fallback Template | Timing |
|---|---|---|---|
| 1 | `event_reminder_1` | `invite_reminder_1` | ~7 days after invite |
| 2 | `event_reminder_2` | `invite_reminder_2` | ~14 days after invite |
| 3 | `event_reminder_final` | `invite_reminder_final` | ~3 days before event |

**Code:** `invitation_reminders.py → queue_reminders()` maps `stage` → trigger event via `stage_trigger_map`, looks up the workflow, and merges vars with the same precedence rules.

Available variables (all stages):

| Variable | Source |
|---|---|
| `first_name`, `last_name`, `email` | Trigger-time (User model) |
| `confirmation_url` | Trigger-time (freshly generated token) |
| `event_name`, `event_date_range`, `event_time`, `event_location` | Trigger-time (`build_event_template_vars()`) |
| `event_start_date` | Trigger-time (formatted start date) |
| `days_until_event` | Trigger-time (computed) |
| `reminder_stage` | Trigger-time (1, 2, or 3) |
| `is_final_reminder` | Trigger-time (`true` only for stage 3) |
| `logo_url`, `org_address`, etc. | Workflow DB `custom_vars` |

## Per-Workflow Sender Address Override

Each workflow can optionally override the default sender address (`SENDGRID_FROM_EMAIL` / `SENDGRID_FROM_NAME` env vars) by setting `from_email` and/or `from_name` on the `EmailWorkflow` row. This allows different email flows to send from different addresses — e.g., invitations from `invite@cyberxrt.com` and general emails from `hello@cyberxrt.com`.

### How It Works

1. **Model columns:** `EmailWorkflow.from_email` and `EmailWorkflow.from_name` (nullable strings). Set via admin UI or API.
2. **Queue time:** When a workflow is used as a config store (bulk invite, reminders, or `WorkflowService.trigger_workflow()`), the from fields are injected into `custom_vars` as reserved keys `__from_email` and `__from_name`.
3. **Send time:** `EmailService._send_email_with_template()` pops the reserved keys from `custom_vars` before template rendering and uses them to construct a per-message `Email()` sender. Falls back to the env var defaults if not present.

### Precedence

```
1. Workflow from_email/from_name   (highest — per-workflow override)
2. SENDGRID_FROM_EMAIL/FROM_NAME   (lowest — env var default)
```

### Example

| Workflow | from_email | from_name |
|---|---|---|
| `bulk_invite` | `invite@cyberxrt.com` | `CyberX Invitations` |
| `user_confirmed` | _(null — uses default)_ | _(null — uses default)_ |
| `event_reminder_1` | `invite@cyberxrt.com` | `CyberX Invitations` |

### Reserved Keys

The keys `__from_email` and `__from_name` are reserved and must not be used as template variable names. They are stripped from `custom_vars` before reaching SendGrid / Handlebars rendering.

### In-Person Attendance Details

| Trigger Event | Template | Code |
|---|---|---|
| `action_assigned` (or manual send) | `sg_in_person_details` | `admin_actions.py` bulk action creation |

This email notifies selected participants of their in-person seat assignment and provides all venue logistics. All venue/event variables are static per-event and belong in the workflow's `custom_vars`.

**Auto-populated (email service defaults):**

| Variable | Source |
|---|---|
| `first_name`, `last_name`, `email` | User model |
| `confirm_url` / `confirmation_url` | `FRONTEND_URL` + user's confirmation code |
| `login_url`, `support_email` | App settings |

**Workflow DB `custom_vars`** (set once per event, same for all recipients):

| Variable | Example | Required |
|---|---|---|
| `event_name` | `CyberX 2026` | Yes |
| `event_date_range` | `Jun 9–13, 2026` | Yes |
| `event_hours` | `0830–1830` | Yes |
| `venue_name` | `Hopper Hall` | Yes |
| `venue_room` | `War Room, Rm. 402` | No |
| `venue_address` | `597 McNair Rd, Naval Academy, MD 21402` | Yes |
| `equipment_info` | `USB-C KVM, monitor, keyboard, and mouse at each station` | No |
| `id_requirements` | `Bring a valid government-issued photo ID` | Yes |
| `id_requirements_url` | `https://usna.edu/Visit/index.php` | No |
| `gate_name` | `Gate 8` | Yes |
| `gate_address` | `485 Bowyer Rd, Naval Academy, MD 21402` | Yes |
| `parking_directions` | `Follow Decatur Ave to the parking garage. If full, park along Sims Rd.` | Yes |
| `map_gate_url` | Image URL — gate to parking map | No |
| `map_building_url` | Image URL — parking to venue map | No |
| `contacts` | `[{"name": "Mike Shuck", "handle": "@m1k3work"}, {"name": "Wes Huang", "handle": "@iwanteggroll"}]` | No |
| `ground_rules` | `["Limit hallway conversations — classes nearby", "Clean up your area at end of day", "Redirect visitors to site leads"]` | No |
| `logo_url` | CyberX logo image URL | No |
| `org_address` | `7802 Montreal Ct, Severn, MD 21144` | Yes |

**Notes:**
- `contacts` is a JSON array of objects with `name` and `handle` keys — rendered via `{{#each contacts}}`.
- `ground_rules` is a JSON array of strings — rendered via `{{#each ground_rules}}`.
- `map_gate_url` and `map_building_url` are conditionally rendered — sections only appear when set.
- `venue_room` and `equipment_info` are conditionally rendered.
- `confirm_url` can be overridden in custom_vars to point to a participant action URL instead of the default confirmation page.

**Example workflow `custom_vars` JSON:**
```json
{
  "event_name": "CyberX 2026",
  "event_date_range": "Jun 9–13, 2026",
  "event_hours": "0830–1830",
  "venue_name": "Hopper Hall",
  "venue_room": "War Room, Rm. 402",
  "venue_address": "597 McNair Rd, Naval Academy, MD 21402",
  "equipment_info": "USB-C (non-powered) KVM, monitor, keyboard, and mouse at each station",
  "id_requirements": "Bring a valid government-issued photo ID",
  "id_requirements_url": "https://usna.edu/Visit/index.php",
  "gate_name": "Gate 8",
  "gate_address": "485 Bowyer Rd, Naval Academy, MD 21402",
  "parking_directions": "Follow Decatur Ave to the parking garage. If both levels are full, park along Sims Rd. See maps below for the walking route to Hopper Hall.",
  "contacts": [
    {"name": "Mike Shuck", "handle": "@m1k3work"},
    {"name": "Wes Huang", "handle": "@iwanteggroll"}
  ],
  "ground_rules": [
    "Limit hallway conversations — classes nearby",
    "Clean up your sitting area at end of each day",
    "Redirect USNA visitors to site leads (Mike or Wes)"
  ],
  "logo_url": "https://cdn.example.com/cyberx-logo.png",
  "org_address": "7802 Montreal Ct, Severn, MD 21144"
}
```

## SendGrid Dynamic Templates

The templates themselves live in SendGrid and use Handlebars syntax:
- Simple variables: `{{variable_name}}`
- Conditionals: `{{#if variable_name}}...{{/if}}`
- Iteration: `{{#each array_name}}{{this}}{{/each}}`
- Object property access in loops: `{{#each contacts}}{{this.name}}{{/each}}`
- Equality checks: `{{#equals variable "value"}}...{{/equals}}`

Template HTML source files are maintained locally at:
```
website-nextgen/templates/sendgrid/
  account_created_admin_sponsor.html
  action_needed_attendance.html
  credentials_email.html
  hacker_theme_invite.html
  in_person_details.html
  password_reset.html
```

## Related Files

- `backend/app/api/routes/admin.py` — trigger-time variable construction + trigger event registry
- `backend/app/services/workflow_service.py` — workflow trigger + first merge
- `backend/app/services/email_service.py` — service defaults + second merge + SendGrid send + invitation workflow lookup
- `backend/app/services/email_queue_service.py` — queue storage + batch processing
- `backend/app/tasks/invitation_reminders.py` — multi-stage reminder scheduler + workflow lookup
- `backend/app/tasks/invitation_emails.py` — bulk invitation scheduler
- `backend/app/models/email_workflow.py` — workflow model with `custom_vars` column + trigger event constants
- `backend/app/models/email_queue.py` — queue model with `custom_vars` column
