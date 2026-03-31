# Developer's Guide: CyberX Event Management Platform

This guide is the architecture and integration reference for developers (and AI sessions) building features into the platform. Before writing new code, read this guide to understand what already exists and how to integrate with it. The goal is to prevent duplicating existing services, breaking current features, or introducing patterns that conflict with the codebase.

## Table of Contents

- [Project Structure](#project-structure)
- [Backend Architecture](#backend-architecture)
  - [FastAPI Application](#fastapi-application)
  - [Database & ORM](#database--orm)
  - [Migrations](#migrations)
  - [Authentication & Authorization](#authentication--authorization)
  - [Permissions System](#permissions-system)
  - [Dependency Injection](#dependency-injection)
  - [Service Layer](#service-layer)
  - [API Routes](#api-routes)
  - [Pydantic Schemas](#pydantic-schemas)
  - [Field Encryption](#field-encryption)
  - [Audit Logging](#audit-logging)
  - [Background Tasks](#background-tasks)
  - [Email System](#email-system)
  - [Webhook Handling](#webhook-handling)
  - [Cloud Provider Integration](#cloud-provider-integration)
  - [Error Handling](#error-handling)
- [Frontend Architecture](#frontend-architecture)
  - [Template System](#template-system)
  - [Layouts & Inheritance](#layouts--inheritance)
  - [CSS & Dark Mode](#css--dark-mode)
  - [JavaScript Patterns](#javascript-patterns)
  - [CSRF Protection](#csrf-protection)
  - [Common UI Components](#common-ui-components)
  - [Admin Page Pattern](#admin-page-pattern)
  - [Participant Portal](#participant-portal)
- [Testing](#testing)
- [Adding a New Feature Checklist](#adding-a-new-feature-checklist)

---

## Project Structure

```
cyberx-event-mgmt/
├── backend/
│   ├── app/
│   │   ├── api/routes/          # FastAPI route handlers
│   │   ├── middleware/          # CSRF middleware
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # Business logic layer
│   │   ├── tasks/               # Background scheduler jobs
│   │   ├── utils/               # Encryption, permissions, helpers
│   │   ├── config.py            # Settings (env vars via Pydantic)
│   │   ├── database.py          # Async SQLAlchemy engine & session
│   │   ├── dependencies.py      # FastAPI dependency injection
│   │   └── main.py              # App setup, middleware, routers
│   ├── migrations/versions/     # Alembic migration files
│   └── tests/                   # pytest test suite
├── frontend/
│   ├── templates/
│   │   ├── layouts/             # base.html, dashboard.html, auth.html
│   │   └── pages/               # admin/, participant/, public/, redirectors/
│   └── static/
│       ├── js/                  # csrf.js, sortable-table.js
│       └── img/                 # Logo assets
├── scripts/                     # Utility scripts
└── docs/                        # Additional documentation
```

---

## Backend Architecture

### FastAPI Application

**Entry point:** `backend/app/main.py`

The app uses async FastAPI with a lifespan manager that handles startup/shutdown. Key startup steps:
1. Install memory log handler (for in-app log viewer)
2. Initialize Fernet encryption
3. Seed email templates and roles (idempotent)
4. Bootstrap admin user (only if no admins exist)
5. Start background scheduler

**Middleware stack** (order matters — listed innermost to outermost):
1. `SecurityHeadersMiddleware` — X-Frame-Options, X-Content-Type-Options, etc.
2. `CORSMiddleware` — configured via `CORS_ORIGINS` setting
3. `CSRFMiddleware` — token-based CSRF protection with exempt paths for webhooks, agents, and public endpoints

When adding middleware, understand the execution order: the last registered middleware runs first on request (outermost).

### Database & ORM

**File:** `backend/app/database.py`

- **PostgreSQL** with **SQLAlchemy 2.0 async** via `asyncpg`
- Pool: 20 connections, 50 max overflow, pre-ping enabled
- Sessions: `expire_on_commit=False`, `autoflush=False` — you manage commits explicitly

**Session pattern in routes:**
```python
from app.dependencies import get_db

async def my_endpoint(db: AsyncSession = Depends(get_db)):
    svc = MyService(db)
    result = await svc.do_something()
    # Session is scoped to the request and cleaned up automatically
```

**Do not** create your own engine or session factory. Always use `get_db`.

### Migrations

**Location:** `backend/migrations/versions/`

- **Alembic** with async support
- **Naming convention:** `YYYYMMDD_HHMMSS_description.py`
- **Revision chain:** Each migration's `down_revision` points to the previous one

**To create a migration:**
```bash
cd backend
alembic revision -m "add_my_new_column" --autogenerate
```

Then rename the file to match the convention (e.g., `20260401_000000_add_my_new_column.py`) and update the `revision` string to match.

**Important:** Always verify `down_revision` points to the actual latest migration, not a guessed one. Check with:
```bash
ls -1 backend/migrations/versions/*.py | tail -5
```

### Authentication & Authorization

**File:** `backend/app/dependencies.py`

The platform uses **session-based authentication** with bcrypt password hashing. Sessions are stored in the database.

**Dependency functions for route protection:**

| Dependency | Use when |
|-----------|----------|
| `get_current_user` | Any authenticated user |
| `get_current_active_user` | Must be active (not disabled) |
| `get_current_admin_user` | Must have admin role |
| `get_current_sponsor_user` | Must be sponsor or admin |
| `get_optional_user` | User may or may not be logged in |
| `require_permission("perm.name")` | Fine-grained permission check |

**For new endpoints, prefer `require_permission()` over role-based checks.** This is the current standard:
```python
@router.post("/my-endpoint")
async def my_endpoint(
    current_user: User = Depends(require_permission("myfeature.manage")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

**Agent authentication** (for VM-to-platform communication) uses Bearer tokens with SHA-256 hashing and IP binding. See `get_current_agent_instance` in dependencies.py.

### Permissions System

**File:** `backend/app/utils/permissions.py`

49 permissions organized by domain. Three base roles with permission sets:

| Role | Permissions |
|------|------------|
| **Admin** | All 49 permissions |
| **Sponsor** | 19 permissions (participants, instances, VPN, TLS, CPE, Discord, redirectors) |
| **Invitee** | 13 permissions (instances, VPN, TLS, CPE, Discord, redirectors) |

**Permission naming convention:** `domain.action` (e.g., `events.create`, `vpn.manage_pool`, `redirectors.view_all`)

**When adding a new feature:**
1. Define permissions in `permissions.py` under the appropriate category
2. Add them to the role defaults (admin gets all; add to sponsor/invitee as appropriate)
3. Update the seeder count in tests (`test_permissions.py`)
4. Use `require_permission("myfeature.manage")` in your routes

**Permission resolution supports per-user overrides:**
```python
effective = resolve_permissions(base=role_perms, add=user_adds, remove=user_removes)
```

**Checking permissions in templates:**
```jinja2
{% if 'myfeature.manage' in perms %}
    <a href="/admin/myfeature">My Feature</a>
{% endif %}
```

### Dependency Injection

**File:** `backend/app/dependencies.py`

Beyond auth, this file provides service factories and a `PermissionChecker` class for resource-level access control:

```python
checker = PermissionChecker(current_user)
if not checker.can_view_participant(target_user):
    raise HTTPException(403)
```

For simple permission checks, use `require_permission()`. For resource-level checks (e.g., "can this user edit this specific participant?"), use `PermissionChecker`.

### Service Layer

**Location:** `backend/app/services/`

Business logic lives in services, not routes. Routes handle HTTP concerns (parsing requests, returning responses); services handle domain logic.

**Key services to know about:**

| Service | What it does | When to reuse |
|---------|-------------|---------------|
| `audit_service.py` | Records audit log entries | Any security-relevant action |
| `auth_service.py` | Login, sessions, passwords | Authentication flows |
| `participant_service.py` | Participant CRUD, email lookup | Working with users/participants |
| `event_service.py` | Event lifecycle, participations | Anything event-scoped |
| `email_service.py` | SendGrid, template rendering | Sending emails |
| `email_queue_service.py` | Queue processing, dedup | Queuing emails (not direct send) |
| `workflow_service.py` | Event-triggered email workflows | Automating email on user actions |
| `vpn_service.py` | WireGuard credential management | VPN assignment/download |
| `instance_service.py` | Cloud instance lifecycle | Creating/managing VMs |
| `cloud_provider_factory.py` | Provider selection (OpenStack/DO) | Multi-cloud operations |
| `redirector_service.py` | Redirector + stream CRUD | Redirector management |
| `ssh_service.py` | SSH operations on redirectors | Remote server operations |
| `nginx_config_service.py` | Generate nginx stream configs | Redirector deployment |
| `license_service.py` | License products/tokens/slots | License management |
| `tls_certificate_service.py` | TLS cert issuance (step-ca) | Certificate operations |
| `cpe_certificate_service.py` | CPE document generation | CPE cert operations |
| `discord_invite_service.py` | Discord invite generation | Discord integration |
| `download_service.py` | Signed download URLs (R2/nginx) | Secure file downloads |
| `keycloak_sync_service.py` | User sync with Keycloak | Identity federation |
| `log_buffer.py` | In-memory log ring buffer | Log viewer feature |

**Service pattern:**
```python
class MyService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_thing(self, data: dict) -> Thing:
        thing = Thing(**data)
        self.session.add(thing)
        await self.session.commit()
        await self.session.refresh(thing)
        return thing
```

**Do not** duplicate logic that already exists in a service. If you need to send an email, use `EmailService` or `EmailQueueService`. If you need to log an audit event, use `AuditService`. Check the services list before building something new.

### API Routes

**Location:** `backend/app/api/routes/`

Routes are organized by domain. Each file defines an `APIRouter` with a tag and optional prefix.

**Current route files and their prefixes:**

| File | Prefix | Purpose |
|------|--------|---------|
| `auth.py` | `/api/auth` | Login, logout, password ops |
| `admin.py` | `/api/admin` | Admin dashboard, participant CRUD |
| `admin_actions.py` | `/api/admin/actions` | Participant action management |
| `admin_api_keys.py` | `/api/admin/api-keys` | Service API keys |
| `admin_cpe.py` | `/api/admin/cpe` | CPE certificate admin |
| `admin_keycloak.py` | `/api/admin/keycloak` | Keycloak sync controls |
| `admin_pages.py` | (varies) | HTML pages for admin tools (logs) |
| `admin_roles.py` | `/api/admin/roles` | Role/permission management |
| `admin_tls.py` | `/api/admin/tls` | TLS CA chain admin |
| `event.py` | `/api/events` | Event CRUD, bulk invite |
| `instances.py` | `/api/instances` | Admin instance management |
| `instance_templates.py` | `/api/admin/instance-templates` | Instance template CRUD |
| `participant_instances.py` | `/api/participants/instances` | Self-service provisioning |
| `redirectors.py` | `/api/redirectors` | Redirector REST API |
| `redirectors_pages.py` | (varies) | Redirector HTML pages (admin + participant portal) |
| `vpn.py` | `/api/vpn` | VPN credential management |
| `email.py` | `/api/email` | Email template/workflow admin |
| `webhooks.py` | `/api/webhooks` | SendGrid, Keycloak, Discord webhooks |
| `public.py` | `/api/public` | Confirm/decline (no auth) |
| `views.py` | `/` | HTML page routes (login, dashboard) |
| `bot.py` | `/api/bot` | Discord bot callbacks |
| `agent.py` | `/api/agent` | Instance agent API |
| `license.py` | `/api/license` | License management |
| `settings.py` | `/api/settings` | System settings |

**Adding a new route file:**
1. Create the file in `backend/app/api/routes/`
2. Define `router = APIRouter(prefix="/api/myfeature", tags=["My Feature"])`
3. Register it in `main.py`: `app.include_router(myfeature.router)`
4. If it needs CSRF exemption, add the path pattern to the exempt list in `main.py`

### Pydantic Schemas

**Location:** `backend/app/schemas/`

Every route should use Pydantic schemas for request validation and response serialization. Do not return raw dicts from endpoints — define a schema.

**Pattern:**
```python
# schemas/myfeature.py
class MyFeatureCreate(BaseModel):
    name: str
    description: Optional[str] = None

class MyFeatureResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    model_config = {"from_attributes": True}  # Allows ORM → schema conversion
```

### Field Encryption

**File:** `backend/app/utils/encryption.py`

Fernet encryption (AES-128 CBC + HMAC-SHA256) for sensitive fields that need to be retrieved (not just hashed).

```python
from app.utils.encryption import encrypt_field, decrypt_field

# Encrypt before storing
redirector.ssh_private_key = encrypt_field(plaintext_key)

# Decrypt when needed
plaintext = decrypt_field(redirector.ssh_private_key)
```

**Use this for:** SSH keys, API tokens, credentials that the app needs to read back.
**Do not use for:** Passwords (use bcrypt via `auth_service`).

### Audit Logging

**File:** `backend/app/services/audit_service.py`

Log security-relevant actions. The service accepts arbitrary action strings — use SCREAMING_SNAKE_CASE by convention.

```python
audit = AuditService(db)
await audit.log(
    action="MYFEATURE_CREATED",
    user_id=current_user.id,
    resource_type="MYFEATURE",
    resource_id=thing.id,
    details={"name": thing.name},
    ip_address=request.client.host if request.client else None,
)
```

The audit service also snapshots `user_email` and `user_name` at log time so entries survive user deletion.

**Convenience methods exist for common actions:**
- `log_login()`, `log_logout()`
- `log_user_create()`, `log_user_update()`, `log_user_delete()`
- `log_role_change()`, `log_password_reset()`, `log_bulk_action()`

Use the convenience methods when they fit. Use the generic `log()` for new action types.

### Background Tasks

**File:** `backend/app/tasks/scheduler.py`

APScheduler with AsyncIOScheduler handles recurring jobs:

| Job | Interval | Purpose |
|-----|----------|---------|
| Bulk email processing | 45 min | Discovers users needing emails, queues them |
| Session cleanup | Periodic | Purges expired sessions |
| Invitation reminders | Periodic | 3 stages: 7 days, 14 days, 3 days before event |
| Instance status sync | Periodic | Polls OpenStack/DO for VM status changes |
| License slot reaper | Periodic | Reclaims unused license slots |
| Keycloak sync | Periodic | Syncs user data with Keycloak |
| Agent task timeout | Periodic | Marks stale agent tasks as timed out |

**To add a new background job:**
1. Create a task file in `backend/app/tasks/`
2. Register it in `scheduler.py` with an appropriate interval
3. Use `AsyncIOScheduler.add_job()` with `coalesce=True`, `max_instances=1`

### Email System

The platform has a queue-based email system with workflow triggers.

**Components:**
- `EmailService` — SendGrid API client, template variable building
- `EmailQueueService` — Queue with priority, 24-hour dedup, retry logic
- `WorkflowService` — Event-triggered email automation (e.g., USER_CONFIRMED triggers a credentials email)

**To send an email from new code:**
```python
# Option 1: Queue directly (preferred for one-off emails)
queue_svc = EmailQueueService(db)
await queue_svc.enqueue(
    user_id=user.id,
    template_id=template.id,
    priority=3,
)

# Option 2: Trigger a workflow (preferred when responding to a user action)
workflow_svc = WorkflowService(db)
await workflow_svc.trigger("MY_WORKFLOW_EVENT", user_id=user.id)
```

**Do not** call SendGrid directly. Always go through the queue or workflow system.

### Webhook Handling

**File:** `backend/app/api/routes/webhooks.py`

Three webhook endpoints exist:
- `POST /api/webhooks/sendgrid` — ECDSA signature verification, processes email events
- `POST /api/webhooks/keycloak` — HMAC-SHA256 verification
- `POST /api/webhooks/discord` — Guild member events

All webhook endpoints are CSRF-exempt (added to the exempt list in `main.py`).

**When adding a new webhook:**
1. Add the route to `webhooks.py`
2. Add the path to CSRF exempt list in `main.py`
3. Implement signature verification (do not accept unsigned webhooks)
4. Return 200 even on processing errors to prevent retry storms
5. Log errors for debugging

### Cloud Provider Integration

**Pattern:** Factory + Protocol

```python
from app.services.cloud_provider_factory import CloudProviderFactory

provider = CloudProviderFactory.get_provider("openstack", db)
await provider.authenticate()
instance = await provider.create_instance(name="my-vm", ...)
```

Both `OpenStackService` and `DigitalOceanService` implement the `CloudProviderInterface` protocol. Status strings are normalized to: `BUILDING`, `ACTIVE`, `ERROR`, `SHUTOFF`, `DELETED`.

### Error Handling

**Standard error response format:**
```json
{"detail": "Error message here"}
```

**Pattern for raising errors:**
```python
from fastapi import HTTPException, status

raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Resource not found.",
)
```

**Do not** leak internal error details to the client in production. Log the full error server-side, return a sanitized message:
```python
logger.error("SSH command failed: %s", exc)
raise HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="An SSH command failed. Check server logs for details.",
)
```

**401 handling:** Browser requests get redirected to `/login`. API requests get JSON. This is handled globally in `main.py`.

---

## Frontend Architecture

### Template System

- **Engine:** Jinja2 (server-side rendering, no frontend build system)
- **No webpack, Vite, or React.** Pages are HTML templates with inline JavaScript.
- **CSS:** Bootstrap 5.3.2 from CDN
- **Icons:** Feather Icons 4.29.1 (SVG via `<i data-feather="icon-name"></i>`)

### Layouts & Inheritance

```
base.html                    # Root: CSS variables, theme system, global JS utilities
├── dashboard.html           # Admin: sidebar nav + navbar + content area
│   └── pages/admin/*.html   # Admin pages extend dashboard
│   └── pages/redirectors/   # Admin redirector pages extend dashboard
├── auth.html                # Auth: cyberpunk-themed full-page layout
│   └── pages/auth/*.html    # Login, forgot password, reset
└── pages/participant/       # Participant portal extends base directly (no sidebar)
    ├── portal.html          # Main portal with inline cards (VPN, TLS, instances, redirectors)
    └── redirector_detail.html  # Redirector stream management (portal navbar)
```

**Template blocks you can override:**
- `{% block title %}` — HTML title
- `{% block body_class %}` — Body CSS classes
- `{% block content %}` — Main page content (inside dashboard layout)
- `{% block extra_css %}` — Page-specific styles
- `{% block extra_js %}` — Page-specific scripts

**Template globals available in all templates:**
- `app_version` — e.g., "1.4.0"
- `app_environment` — "development", "staging", "production"
- `sendgrid_sandbox_mode` — Boolean
- `url_prefix` — "/admin"
- `current_user` — Authenticated user object
- `now` — `datetime.now()`
- `active_page` — String for sidebar highlighting

### CSS & Dark Mode

Dark mode uses CSS custom properties on `<html data-theme="dark">`.

**Key variables:** `--bg-primary`, `--text-primary`, `--border-color`, `--input-bg`, etc.

**Theme persistence:** localStorage (fast) + API call to `/api/user/theme` (durable).

**When adding new UI components**, use CSS variables for colors instead of hardcoding. If you must use a fixed color, provide a `[data-theme="dark"]` override:
```css
.my-component { background: var(--bg-primary); color: var(--text-primary); }
/* Or if you need a specific color: */
.my-highlight { background: rgba(220,53,69,0.15); }
[data-theme="dark"] .my-highlight { background: rgba(220,53,69,0.25); }
```

### JavaScript Patterns

All JS is inline in templates (no build step, no modules). Global utilities are defined in `base.html`:

**`csrfFetch(url, options)`** — Use this instead of `fetch()`. It:
- Adds CSRF token header automatically for POST/PUT/DELETE/PATCH
- Handles 401 (redirects to login)
- Handles 403 CSRF mismatch (auto-refreshes token and retries)
- Auto-stringifies plain objects as JSON

```javascript
const resp = await csrfFetch('/api/myfeature', {
    method: 'POST',
    body: JSON.stringify({ name: 'test' })
});
const data = await resp.json();
```

**`showToast(message, type)`** — Toast notifications. Types: `success`, `danger`, `warning`, `info`. Auto-dismisses after 5s, click to dismiss.

**`escHtml(str)`** — HTML-escape a string for safe insertion into DOM. **Always use this** when inserting dynamic content into template literals:
```javascript
showToast(`Created <strong>${escHtml(data.name)}</strong>`, 'success');
tbody.innerHTML = `<td>${escHtml(item.name)}</td>`;
```

**`formatDateTime(isoString)`** — Formats ISO dates to locale string with timezone preference.

### CSRF Protection

**File:** `frontend/static/js/csrf.js`

- Cookie name: `csrf_token`
- Header name: `X-CSRF-Token`
- All state-changing requests (POST, PUT, DELETE, PATCH) must include the token
- `csrfFetch()` handles this automatically — **always use it instead of raw `fetch()`**

### Common UI Components

**Tables:**
```html
<table class="table table-hover mb-0">
    <thead>
        <tr>
            <th>Name</th>
            <th>Status</th>
            <th class="text-end">Actions</th>
        </tr>
    </thead>
    <tbody id="myTableBody"></tbody>
</table>
```

**Modals (Bootstrap 5):**
```html
<div class="modal fade" id="myModal" tabindex="-1">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">Title</h5>
                <button class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <!-- Form fields -->
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                <button class="btn btn-primary" onclick="save()">Save</button>
            </div>
        </div>
    </div>
</div>
<script>
const myModal = new bootstrap.Modal(document.getElementById('myModal'));
</script>
```

**Badges:**
```html
<span class="badge bg-success">Active</span>
<span class="badge bg-danger">Error</span>
<span class="badge bg-warning">Pending</span>
```

**Feather icons** (must call `feather.replace()` after inserting new HTML):
```html
<i data-feather="check-circle" class="text-success"></i>
<script>feather.replace();</script>
```

### Admin Page Pattern

Every admin page follows this structure:

1. **Extends `dashboard.html`** — gets sidebar, navbar, footer
2. **Sets `active_page`** — for sidebar highlighting
3. **Stats cards** (optional) — Bootstrap grid with `.card .stats-card`
4. **Filter section** (optional) — Form inputs for search/filter
5. **Data table** — populated by JavaScript via API calls
6. **CRUD modals** — Bootstrap modals for create/edit/delete
7. **JavaScript block** — loads data on `DOMContentLoaded`, renders tables, handles forms

**CRUD flow:**
```javascript
// Load
async function loadItems() {
    const resp = await csrfFetch('/api/myfeature');
    const data = await resp.json();
    renderTable(data.items);
}

// Create
async function createItem() {
    const resp = await csrfFetch('/api/myfeature', {
        method: 'POST',
        body: JSON.stringify({ name: document.getElementById('name').value })
    });
    if (resp.ok) {
        myModal.hide();
        showToast('Created successfully', 'success');
        loadItems();
    } else {
        const err = await resp.json();
        showToast(escHtml(err.detail || 'Error'), 'danger');
    }
}
```

**Sidebar navigation** — to add a new nav item, edit `frontend/templates/layouts/dashboard.html`:
```jinja2
{% if 'myfeature.view' in perms %}
<a class="nav-link {% if active_page == 'myfeature' %}active{% endif %}" href="/admin/myfeature">
    <i data-feather="icon-name"></i>
    <span>My Feature</span>
</a>
{% endif %}
```

### Participant Portal

The participant portal (`frontend/templates/pages/participant/portal.html`) differs from admin pages:
- Extends `base.html` directly (no sidebar)
- Navbar-only navigation (dark theme)
- Full-width content area
- Simpler UI focused on self-service actions (VPN download, instance provisioning, etc.)

---

## Testing

**Framework:** pytest with pytest-asyncio

**Location:** `backend/tests/`

```
tests/
├── conftest.py          # Fixtures: db session, clients, users, roles
├── unit/                # Unit tests (28+ files)
└── integration/         # Integration tests
```

**Key fixtures provided by conftest.py:**
- `db_session` — Async SQLAlchemy session (in-memory SQLite, rolled back after each test)
- `client` — AsyncClient with ASGI transport (CSRF disabled for tests)
- `admin_user`, `sponsor_user`, `invitee_user` — Pre-created test users with roles
- `admin_session_token` — Authenticated session cookie
- `authenticated_admin_client` — Client pre-authenticated as admin
- `active_event` — Future-dated active event

**Test pattern:**
```python
@pytest.mark.unit
@pytest.mark.asyncio
class TestMyFeature:
    async def test_create(self, db_session: AsyncSession):
        svc = MyService(db_session)
        result = await svc.create({"name": "test"})
        assert result.name == "test"

    async def test_api_requires_auth(self, client):
        resp = await client.post("/api/myfeature", json={"name": "test"})
        assert resp.status_code == 401

    async def test_api_create(self, authenticated_admin_client):
        resp = await authenticated_admin_client.post(
            "/api/myfeature", json={"name": "test"}
        )
        assert resp.status_code == 201
```

**Running tests:**
```bash
cd backend
pytest tests/ -v
pytest tests/unit/test_myfeature.py -v  # Single file
pytest -k "test_create" -v               # By name
```

---

## Adding a New Feature Checklist

Use this checklist when integrating a new feature to avoid breaking existing functionality:

### Before writing code
- [ ] Read this guide to identify existing services you should reuse
- [ ] Check if similar functionality already exists (search the services/ directory)
- [ ] Decide where the feature fits in the existing permission categories
- [ ] Plan your migration — check the latest migration file for `down_revision`

### Backend
- [ ] **Model** — Add to `backend/app/models/`. Follow existing column patterns (timestamps, nullable, etc.)
- [ ] **Migration** — Create in `backend/migrations/versions/` with correct `down_revision`
- [ ] **Schema** — Add Pydantic schemas in `backend/app/schemas/`. Use `model_config = {"from_attributes": True}`
- [ ] **Service** — Add business logic in `backend/app/services/`. Accept `AsyncSession` in `__init__`
- [ ] **Route** — Add to `backend/app/api/routes/`. Use `require_permission()` for auth
- [ ] **Register router** — Add `app.include_router()` in `main.py`
- [ ] **Permissions** — Add to `permissions.py` and role defaults. Update test count
- [ ] **Audit logging** — Log security-relevant actions via `AuditService`
- [ ] **Error messages** — Sanitize error details in production (log full errors server-side)
- [ ] **Encryption** — Use `encrypt_field()`/`decrypt_field()` for sensitive stored data

### Frontend
- [ ] **Template** — Create in `frontend/templates/pages/`. Extend `dashboard.html` for admin pages
- [ ] **Sidebar nav** — Add permission-gated nav link in `dashboard.html`
- [ ] **CSRF** — Use `csrfFetch()` for all API calls, never raw `fetch()`
- [ ] **XSS prevention** — Use `escHtml()` for all dynamic content in JS template literals. Use `| e` or `| tojson` in Jinja2 templates
- [ ] **Dark mode** — Use CSS variables for colors, test in both themes
- [ ] **Feather icons** — Call `feather.replace()` after inserting new HTML with icons

### Testing
- [ ] **Unit tests** — Add to `backend/tests/unit/`
- [ ] **Permission tests** — Verify endpoints reject unauthorized access
- [ ] **Run existing tests** — `pytest tests/` to confirm nothing is broken

### Do not
- [ ] Create a separate database connection or session factory
- [ ] Call SendGrid directly (use EmailQueueService)
- [ ] Return raw dicts from API endpoints (use Pydantic schemas)
- [ ] Use `fetch()` instead of `csrfFetch()` in frontend JS
- [ ] Hardcode colors without dark mode support
- [ ] Skip audit logging for security-relevant actions
- [ ] Expose internal error details in HTTP responses
- [ ] Add middleware without understanding the execution order
