# Roles & Permissions System

**Status:** Implemented
**Last Updated:** 2026-03-09

---

## Overview

The system uses a hybrid approach combining:
- **Legacy base types** (`admin`, `sponsor`, `invitee`) for sidebar visibility, login redirects, and data scoping
- **Dynamic roles** stored in a `roles` table with JSON permission arrays
- **Per-user overrides** for adding/removing specific permissions on top of role defaults

### Key Files

| File | Purpose |
|------|---------|
| `backend/app/models/role.py` | Role model (name, slug, base_type, permissions, is_system) |
| `backend/app/utils/permissions.py` | ALL_PERMISSIONS constant, ROLE_PERMISSIONS defaults, permission categories |
| `backend/app/models/user.py` | `has_permission()`, `get_effective_permissions()`, `permission_overrides` |
| `backend/app/dependencies.py` | `require_permission()`, `require_role()` FastAPI dependencies |
| `backend/app/services/role_seeder.py` | Idempotent seed of system roles on startup |
| `backend/app/api/routes/admin_roles.py` | Role CRUD API endpoints |

---

## System Roles (3 built-in)

### Admin
- **Slug:** `admin`
- **Base type:** `admin`
- **System role:** Yes (cannot be deleted)
- **Permissions:** All 46 permissions
- **Description:** Full system access. Manages users, roles, events, email, infrastructure, and all platform features.

### Sponsor
- **Slug:** `sponsor`
- **Base type:** `sponsor`
- **System role:** Yes (cannot be deleted)
- **Permissions:** 15 (all invitee self-service + participant management)
- **Description:** Manages their own sponsored participants. Can create, edit, invite, and view participant resources. Also has full self-service access.

**Sponsor-specific permissions (beyond invitee):**
- `participants.view` — view sponsored participants
- `participants.create` — create new participants
- `participants.edit` — edit participant records
- `participants.invite` — send invitations

### Invitee
- **Slug:** `invitee`
- **Base type:** `invitee`
- **System role:** Yes (cannot be deleted)
- **Permissions:** 11 (self-service only)
- **Description:** Standard participant. Can provision instances, request VPN, download certificates, and manage their own resources.

**Invitee permissions:**
`instances.view`, `instances.provision`, `instances.delete`, `instances.manage_agent`, `vpn.view`, `vpn.request`, `vpn.download`, `tls.request`, `tls.download`, `cpe.download`, `discord.view`

---

## All Permissions (46)

### Events (4)
| Permission | Description |
|-----------|-------------|
| `events.view` | View event list and event details |
| `events.create` | Create new events |
| `events.edit` | Update event details, activate/archive events |
| `events.delete` | Delete events |

### Participants (6)
| Permission | Description |
|-----------|-------------|
| `participants.view` | View own/sponsored participants |
| `participants.view_all` | View all participants system-wide, dashboard stats |
| `participants.create` | Create new participants |
| `participants.edit` | Update participant details, role, sponsor assignment |
| `participants.remove` | Delete/remove participants |
| `participants.invite` | Send invitations, resend, trigger reminders |

### Instances (6)
| Permission | Description |
|-----------|-------------|
| `instances.view` | View own instances (self-service) |
| `instances.view_all` | View all instances across all users |
| `instances.provision` | Create instances (self-service or admin bulk) |
| `instances.delete` | Delete/terminate instances |
| `instances.manage_agent` | Create/view agent tasks on instances |
| `instances.sync_status` | Sync instance status from cloud provider |

### VPN (4)
| Permission | Description |
|-----------|-------------|
| `vpn.view` | View own VPN credentials and config |
| `vpn.request` | Self-service VPN credential request |
| `vpn.download` | Download VPN config files |
| `vpn.manage_pool` | Import, assign, bulk delete VPN credentials |

### Email (6)
| Permission | Description |
|-----------|-------------|
| `email.view` | View email analytics, history, queue stats |
| `email.send` | Send individual and custom emails |
| `email.send_bulk` | Send bulk emails (high-impact) |
| `email.manage_templates` | CRUD email templates, import/sync from SendGrid |
| `email.manage_queue` | Process email queue batches, cancel queued emails |
| `email.manage_workflows` | Create/edit/delete automated email workflows |

### TLS Certificates (3)
| Permission | Description |
|-----------|-------------|
| `tls.request` | Request own TLS certificate (self-service) |
| `tls.download` | Download own TLS certificates |
| `tls.manage` | Manage CA chains, admin TLS cert operations |

### CPE Certificates (2)
| Permission | Description |
|-----------|-------------|
| `cpe.download` | Download own CPE certificates |
| `cpe.manage` | Check eligibility, issue/revoke/regenerate CPE certificates |

### Discord (2)
| Permission | Description |
|-----------|-------------|
| `discord.view` | View Discord integration and invite card |
| `discord.manage` | Configure Discord integration |

### Cloud Infrastructure (3)
| Permission | Description |
|-----------|-------------|
| `cloud.manage_providers` | View provider stats, manage provider limits |
| `cloud.manage_templates` | CRUD instance templates (OpenStack/DO configurations) |
| `cloud.manage_images` | CRUD cloud-init templates |

### Licenses (2)
| Permission | Description |
|-----------|-------------|
| `licenses.view` | View license products and stats |
| `licenses.manage` | CRUD license products, queue operations |

### Participant Actions (2)
| Permission | Description |
|-----------|-------------|
| `actions.view` | View all participant actions and statistics |
| `actions.manage` | Create bulk actions, assign to participants, revoke |

### Keycloak (1)
| Permission | Description |
|-----------|-------------|
| `keycloak.manage` | View sync status, trigger sync, retry, setup webhook |

### Admin / System (5)
| Permission | Description |
|-----------|-------------|
| `admin.manage_users` | Create/edit/delete user accounts, reset passwords |
| `admin.manage_roles` | Create/edit/delete roles, assign permissions |
| `admin.view_audit_log` | View audit log entries and stats |
| `admin.manage_settings` | Update application settings |
| `scheduler.view` | View scheduler jobs and status |

---

## Permission Resolution

Effective permissions for a user are computed as:

```
effective = (role.permissions + overrides.add) - overrides.remove
```

**Resolution order:**
1. Load role permissions from `user.role_obj.permissions` (JSON array)
2. Add any permissions from `user.permission_overrides.add`
3. Remove any permissions from `user.permission_overrides.remove`
4. Fallback: if no `role_obj`, use legacy `ROLE_PERMISSIONS[user.role]` dict

**User model methods:**
```python
user.has_permission("events.view")              # Requires ALL listed permissions (AND)
user.has_any_permission("events.view", "...")    # Requires ANY listed permission (OR)
user.get_effective_permissions()                 # Returns set of all effective permissions
```

---

## Route Protection

### Permission-based (primary)
```python
@router.get("/endpoint")
async def endpoint(user: User = Depends(require_permission("events.view"))):
    ...
```

### Role-based (legacy, for sidebar/redirects)
```python
@router.get("/admin")
async def admin_page(user: User = Depends(require_role(UserRole.ADMIN))):
    ...
```

### Resource-level scoping
`PermissionChecker` applies fine-grained access:
- Users with `participants.view_all` can see any participant
- Users with `participants.view` can only see their sponsored participants
- All users can view/manage their own resources

---

## Custom Roles

Custom roles can be created via the admin UI or API:

1. **Settings → Roles → New Role** (or clone existing)
2. Choose a **base type** — controls navigation tier:
   - `admin` → admin sidebar + dashboard
   - `sponsor` → sponsor sidebar + participant management
   - `invitee` → participant portal
3. Toggle permissions on/off
4. For sponsor-type roles, set **Allowed Role IDs** to restrict which invitee types they can assign

### API

All require `admin.manage_roles` permission:

| Endpoint | Description |
|----------|-------------|
| `GET /api/admin/roles` | List all roles with user counts |
| `POST /api/admin/roles` | Create custom role |
| `GET /api/admin/roles/{id}` | Get single role |
| `PUT /api/admin/roles/{id}` | Update role |
| `DELETE /api/admin/roles/{id}` | Delete custom role (reassigns users) |
| `POST /api/admin/roles/{id}/clone` | Clone role |
| `GET /api/admin/roles/permissions` | List all permissions grouped by category |

**Constraints:**
- System roles cannot be deleted
- System role permissions are synced from code on startup (not editable via API)
- Role slugs must be unique
- Deleting a custom role reassigns its users to the default invitee role

---

## Role Seeding

On application startup, `role_seeder.py` runs idempotently:
- Creates missing system roles (admin, sponsor, invitee)
- Updates existing system role permissions to match code definitions
- Does not modify custom roles
- Populates `role_id` from legacy `role` string column for existing users
