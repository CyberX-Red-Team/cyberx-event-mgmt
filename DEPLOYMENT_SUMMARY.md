# Deployment Guide — Render + Supabase

Complete guide for deploying the CyberX Event Management System on Render.com with Supabase database, including external service configuration.

**Last Updated:** 2026-03-09

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Infrastructure Setup](#infrastructure-setup)
  - [Supabase (Database)](#1-supabase-database)
  - [Render (Application)](#2-render-application)
  - [Gotenberg (PDF Sidecar)](#3-gotenberg-pdf-sidecar)
- [External Service Configuration](#external-service-configuration)
  - [SendGrid (Email)](#sendgrid-email)
  - [Cloudflare R2 (File Storage)](#cloudflare-r2-file-storage)
  - [Keycloak (SSO & Password Sync)](#keycloak-sso--password-sync)
  - [Discord (Invite Links)](#discord-invite-links)
  - [OpenStack (VM Provisioning)](#openstack-vm-provisioning)
  - [DigitalOcean (VM Provisioning)](#digitalocean-vm-provisioning)
  - [PowerDNS-Admin (DNS Management)](#powerdns-admin-dns-management)
  - [Render API (Sidecar Management)](#render-api-sidecar-management)
- [Roles & Permissions](#roles--permissions)
- [Related Documentation](#related-documentation)

---

## Architecture Overview

```
┌─────────────────────┐    ┌──────────────────────┐
│  Render.com          │    │  Supabase             │
│                      │    │                       │
│  ┌────────────────┐  │    │  PostgreSQL (Pro)      │
│  │ Web Service     │──────│  - 8GB storage         │
│  │ (FastAPI)       │  │    │  - Point-in-time       │
│  │ uvicorn + APSch │  │    │    recovery (7 days)   │
│  └────────────────┘  │    │  - Daily backups        │
│                      │    └──────────────────────┘
│  ┌────────────────┐  │
│  │ Gotenberg       │  │    ┌──────────────────────┐
│  │ (Private Svc)   │  │    │  External Services     │
│  │ DOCX→PDF        │  │    │                       │
│  └────────────────┘  │    │  SendGrid (email)      │
└─────────────────────┘    │  Cloudflare R2 (files)  │
                           │  Keycloak (SSO)         │
                           │  Discord (invites)      │
                           │  OpenStack / DO (VMs)   │
                           │  PowerDNS (DNS)         │
                           └──────────────────────┘
```

**Monthly Cost:** ~$32 ($7 Render Starter + $25 Supabase Pro)

---

## Infrastructure Setup

### 1. Supabase (Database)

See [SUPABASE_SETUP.md](SUPABASE_SETUP.md) for the full Supabase setup guide.

**Quick summary:**

1. Create project at [supabase.com](https://supabase.com) — Pro plan ($25/month)
2. Copy the **Connection Pooler** URI (Transaction mode):
   ```
   postgresql://postgres.xxxxx:[PASSWORD]@aws-0-us-west-1.pooler.supabase.com:6543/postgres
   ```
3. URL-encode special characters in password (`@` → `%40`, `#` → `%23`)
4. The app auto-converts `postgresql://` to `postgresql+asyncpg://`

### 2. Render (Application)

The app deploys as a single **Web Service** on Render:

1. Connect your GitHub repository to Render
2. Create a **Web Service** from the `render.yaml` blueprint, or manually:
   - **Runtime:** Python 3.12
   - **Build command:** `cd backend && pip install -r requirements.txt`
   - **Start command:** `cd backend && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
   - **Health check:** `/health`
   - **Plan:** Starter ($7/month)
   - **Region:** Virginia (US East) — closest to Supabase US East
   - **Branch:** `staging` or `main`

3. Set environment variables in the Render dashboard (see [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md)):

   **Auto-generated (use `generateValue: true` in render.yaml):**
   - `SECRET_KEY`, `CSRF_SECRET_KEY`, `ENCRYPTION_KEY`

   **Manual configuration (set `sync: false` in render.yaml):**
   - `DATABASE_URL` — Supabase connection string
   - `ENVIRONMENT` — `staging` or `production`
   - `FRONTEND_URL` — e.g., `https://events.cyberxredteam.org`
   - `ALLOWED_HOSTS` — e.g., `events.cyberxredteam.org`
   - `ADMIN_EMAIL`, `ADMIN_PASSWORD` — bootstraps first admin on fresh DB
   - All external service credentials (see sections below)

### 3. Gotenberg (PDF Sidecar)

Required for CPE certificate generation (DOCX → PDF conversion).

1. Create a **Private Service** on Render:
   - **Name:** `cyberx-gotenberg`
   - **Runtime:** Docker
   - **Dockerfile:** `Dockerfile.gotenberg` (in repo root)
   - **Plan:** Starter (512MB RAM minimum)
   - **Region:** Same as web service

2. The Dockerfile disables Chromium to save RAM (only LibreOffice is used):
   ```dockerfile
   FROM gotenberg/gotenberg:8
   CMD ["gotenberg", "--chromium-disable-javascript=true", "--chromium-auto-start=false"]
   ```

3. Note the Render service ID (format: `srv_xxxxxxxxxxxx`) for `GOTENBERG_RENDER_SERVICE_ID`

4. The app manages Gotenberg lifecycle automatically (suspend when idle, resume on demand)

---

## External Service Configuration

Each section below explains both the **environment variables** needed and the **external service setup** steps.

### SendGrid (Email)

Email delivery for invitations, confirmations, password resets, and bulk communications.

**Features used:** Mail Send API (v3), Event Webhooks, Dynamic Templates

#### Setup Steps

1. **Create API key:**
   - Dashboard → Settings → API Keys → Create API Key
   - Permissions: Full Access, or restricted to `Mail Send`
   - Copy the key (only shown once) → `SENDGRID_API_KEY`

2. **Verify sender identity:**
   - Dashboard → Sender Authentication
   - Option A: Domain Authentication (recommended) — add DNS records for DKIM/SPF
   - Option B: Single Sender Verification — verify a single email address
   - The verified email/domain must match `SENDGRID_FROM_EMAIL`

3. **Configure Event Webhook (delivery tracking):**
   - Dashboard → Settings → Mail Settings → Event Webhook
   - HTTP POST URL: `https://your-domain/api/webhooks/sendgrid`
   - Select events: `processed`, `delivered`, `bounce`, `dropped`, `deferred`, `open`, `click`, `unsubscribe`, `spamreport`
   - Enable **Signature Verification** → copy the verification key → `SENDGRID_WEBHOOK_VERIFICATION_KEY`

4. **Dynamic Templates (optional):**
   - Dashboard → Email API → Dynamic Templates
   - Create templates with Handlebars syntax
   - Template IDs are stored per email template in the app database
   - If not using SendGrid templates, the app renders templates server-side with Jinja2

#### Environment Variables

```bash
SENDGRID_API_KEY=SG.xxxxx
SENDGRID_FROM_EMAIL=noreply@cyberxredteam.org
SENDGRID_FROM_NAME=CyberX Red Team            # optional, default: "CyberX Red Team"
SENDGRID_SANDBOX_MODE=false                    # true = validate but don't deliver
SENDGRID_WEBHOOK_VERIFICATION_KEY=<key>        # ECDSA public key from SendGrid
TEST_EMAIL_OVERRIDE=                           # redirect ALL emails to this address (testing)
BULK_EMAIL_INTERVAL_MINUTES=45                 # email queue processing interval
```

---

### Cloudflare R2 (File Storage)

S3-compatible object storage for CPE certificate templates, signature images, TLS certificates, and downloadable files.

#### Setup Steps

1. **Create R2 bucket:**
   - Cloudflare Dashboard → R2 → Create bucket
   - Name: e.g., `cyberx-assets`
   - Location: Auto (recommended)

2. **Create API token:**
   - R2 → Manage R2 API Tokens → Create API Token
   - Permissions: Object Read & Write
   - Specify bucket (or all buckets)
   - Copy Access Key ID and Secret Access Key

3. **Find Account ID:**
   - Cloudflare Dashboard → right sidebar → Account ID (32-char hex)

4. **Upload initial files:**
   - CPE certificate DOCX template → note object key for `CPE_TEMPLATE_R2_KEY`
   - Signature images (PNG, transparent background) → note keys for `CPE_SIGNATURE_1_R2_KEY`, `CPE_SIGNATURE_2_R2_KEY`

5. **Custom domain (optional):**
   - R2 → Bucket → Settings → Custom Domains
   - Connect a domain (e.g., `assets.cyberxredteam.org`)
   - Set → `R2_CUSTOM_DOMAIN`

#### Environment Variables

```bash
R2_ACCOUNT_ID=<32-char-hex>
R2_ACCESS_KEY_ID=<access-key>
R2_SECRET_ACCESS_KEY=<secret-key>
R2_BUCKET=cyberx-assets
R2_CUSTOM_DOMAIN=                              # optional custom domain for URLs
DOWNLOAD_LINK_MODE=r2                          # or "nginx" for self-hosted
DOWNLOAD_LINK_EXPIRY=3600                      # presigned URL lifetime (seconds)
```

---

### Keycloak (SSO & Password Sync)

Syncs participant credentials to Keycloak for SSO access to exercise infrastructure (PowerDNS-Admin, Guacamole, etc.). Receives event webhooks for automatic user-account association.

#### Keycloak Server Setup

1. **Create or select a realm** (e.g., `cyberx`):
   - Keycloak Admin Console → Create Realm → name: `cyberx`

2. **Create a confidential client for the app:**
   - Realm → Clients → Create Client
   - Client ID: `admin-cli` (or custom name → set in `KEYCLOAK_ADMIN_CLIENT_ID`)
   - Client Protocol: `openid-connect`
   - Access Type: **Confidential**
   - Enable: **Service Accounts Enabled** = ON
   - Enable: **Client Authentication** = ON (Keycloak 20+)
   - Save

3. **Assign realm management roles to the client:**
   - Clients → your client → Service Account Roles tab
   - Click "Assign role" → filter by "realm-management"
   - Assign all of the following:
     - **`manage-users`** — create, update, delete users; set passwords; manage group memberships
     - **`view-users`** — search/find users by username (required for user lookup before create/update)
     - **`query-groups`** — search groups by name (required for auto-assigning users to groups)
     - **`manage-realm`** — required by the p2-inc webhook plugin to list/create webhooks
   - This gives the app permission to manage Keycloak users and configure webhooks programmatically

4. **Copy the client secret:**
   - Clients → your client → Credentials tab
   - Copy the Secret → `KEYCLOAK_ADMIN_CLIENT_SECRET`

5. **Create user groups (if using auto-assignment):**
   - Realm → Groups → Create Group
   - Create groups matching `KEYCLOAK_USER_GROUPS` (e.g., `cyberx-users`, `participants`)
   - Synced users are automatically added to these groups

6. **Install the webhook plugin** (for event-driven integration):
   - Plugin: [p2-inc/keycloak-events](https://github.com/p2-inc/keycloak-events)
   - Deploy the JAR to Keycloak's `providers/` directory
   - Restart Keycloak
   - Verify: `GET /realms/{realm}/webhooks` should return 200 (not 404)
   - The app auto-creates the webhook via `POST /api/admin/keycloak/setup`

7. **Webhook auto-configuration:**
   - In the CyberX admin panel, go to Settings → Keycloak
   - Click "Setup Webhook" — this calls the Keycloak API to create a webhook pointing to `{FRONTEND_URL}/api/webhooks/keycloak`
   - The webhook fires on LOGIN, REGISTER, UPDATE_PASSWORD events
   - Used for: auto-assigning PowerDNS-Admin accounts on first SSO login

#### Environment Variables

```bash
KEYCLOAK_URL=https://auth.cyberxredteam.org    # no trailing slash
KEYCLOAK_REALM=cyberx
KEYCLOAK_ADMIN_CLIENT_ID=admin-cli             # client with manage-users role
KEYCLOAK_ADMIN_CLIENT_SECRET=<client-secret>
KEYCLOAK_USER_GROUPS=cyberx-users              # comma-separated group names
KEYCLOAK_WEBHOOK_SECRET=<32+-char-hmac-secret> # for verifying inbound webhooks
KEYCLOAK_WEBHOOK_DEBUG=false                   # log raw webhook payloads
PASSWORD_SYNC_ENABLED=true                     # master toggle for credential sync
PASSWORD_SYNC_INTERVAL_MINUTES=5               # background sync job interval
PASSWORD_SYNC_MAX_RETRIES=5                    # max retries per user before giving up
```

**Notes:**
- Keep `PASSWORD_SYNC_ENABLED=false` until Keycloak is fully configured and reachable
- Only syncs invitee/sponsor users (admins are excluded)
- Connectivity errors don't consume retries — the job succeeds on next interval once Keycloak is up

---

### Discord (Invite Links)

Generates unique, single-use Discord server invite links for confirmed participants.

#### Setup Steps

1. **Create a Discord application:**
   - Go to [discord.com/developers/applications](https://discord.com/developers/applications)
   - Click "New Application" → name it (e.g., "CyberX Invites")

2. **Create a bot:**
   - Application → Bot → Add Bot
   - Copy the bot token → `DISCORD_BOT_TOKEN`
   - No privileged intents needed

3. **Invite the bot to your server:**
   - Application → OAuth2 → URL Generator
   - Scopes: `bot`
   - Bot Permissions: `Create Instant Invite` (permission integer: 1)
   - Copy the generated URL and visit it to invite the bot

4. **Get the channel ID:**
   - In Discord: User Settings → App Settings → Advanced → Developer Mode = ON
   - Right-click the target text channel → "Copy Channel ID"
   - Set this per-event in the CyberX admin panel (Event Settings → Discord Channel ID)

#### How It Works

When a participant confirms their RSVP, the app calls Discord's API to create a unique invite:
- `POST /channels/{channel_id}/invites`
- Parameters: `max_uses=1, unique=true, max_age=0` (single-use, never expires until used)
- The invite link is shown on the participant portal

#### Environment Variables

```bash
DISCORD_BOT_TOKEN=<bot-token>
DISCORD_INVITE_ENABLED=true                    # master toggle
# discord_channel_id is set per-event in the admin UI
```

---

### OpenStack (VM Provisioning)

Provisions virtual machine instances on OpenStack infrastructure for exercise participants.

#### Setup Steps

**Option A: Application Credentials (Recommended)**

1. Log into OpenStack Horizon dashboard
2. Identity → Application Credentials → Create Application Credential
3. Name: e.g., `cyberx-events`
4. Roles: leave default (inherits your project roles)
5. Save the credential ID and secret (secret is shown only once)

**Option B: Password Authentication**

1. Create a Keystone user with project admin role
2. Note the project name and domain names

**Collect resource IDs for defaults:**

```bash
# Find available flavors
openstack flavor list
# Find available images
openstack image list
# Find available networks
openstack network list
# Find available keypairs
openstack keypair list
```

#### Environment Variables

```bash
OS_AUTH_URL=https://openstack.example.com/identity/v3
OS_AUTH_TYPE=v3applicationcredential           # or "password"

# Application credential auth:
OS_APPLICATION_CREDENTIAL_ID=<credential-id>
OS_APPLICATION_CREDENTIAL_SECRET=<credential-secret>

# Password auth (alternative):
OS_USERNAME=cyberx-user
OS_PASSWORD=<password>
OS_PROJECT_NAME=cyberx
OS_USER_DOMAIN_NAME=Default
OS_PROJECT_DOMAIN_NAME=Default

# Service endpoints (auto-discovered from Keystone catalog if not set):
OS_NOVA_URL=                                   # Compute API
OS_NEUTRON_URL=                                # Network API
OS_GLANCE_URL=                                 # Image API

# Instance defaults (overridable per-request):
OS_DEFAULT_FLAVOR_ID=<flavor-uuid>
OS_DEFAULT_IMAGE_ID=<image-uuid>
OS_DEFAULT_NETWORK_ID=<network-uuid>
OS_DEFAULT_KEY_NAME=cyberx-key
```

---

### DigitalOcean (VM Provisioning)

Alternative cloud provider for provisioning droplets.

#### Setup Steps

1. Go to DigitalOcean Control Panel → API → Tokens
2. Generate New Token with Read + Write scopes
3. Copy the token (shown only once) → `DO_API_TOKEN`
4. Optionally add an SSH key:
   - Settings → Security → SSH Keys → Add SSH Key
   - Copy the key ID or fingerprint → `DO_SSH_KEY_ID`

#### Environment Variables

```bash
DO_API_TOKEN=<api-token>
DO_DEFAULT_REGION=nyc1                         # default: New York 1
DO_DEFAULT_SIZE=s-1vcpu-1gb                    # default: 1 vCPU, 1GB RAM
DO_DEFAULT_IMAGE=ubuntu-22-04-x64              # default: Ubuntu 22.04
DO_SSH_KEY_ID=                                 # optional SSH key ID/fingerprint
```

---

### PowerDNS-Admin (DNS Management)

Auto-assigns DNS management accounts when users log into PowerDNS-Admin via Keycloak SSO. Also used for domain validation when issuing TLS certificates.

#### Setup Steps

1. **Deploy PowerDNS-Admin** (separate from this app)

2. **Create an admin account** in PowerDNS-Admin (if not already done)

3. **Create an API key:**
   - PowerDNS-Admin → Admin Panel → API Keys
   - Create key with role: Admin or Operator
   - Copy the key → `POWERDNS_API_KEY`

4. **Create a shared account:**
   - PowerDNS-Admin → Accounts → New Account
   - Name: `cyberx` (or custom → `POWERDNS_ACCOUNT_NAME`)
   - Associate DNS zones with this account

5. **How auto-assignment works:**
   - User logs into PowerDNS-Admin via Keycloak SSO
   - Keycloak fires a LOGIN webhook to the app (requires Keycloak webhook plugin)
   - The app checks if the user has a PowerDNS-Admin account
   - If not, the user is added to the configured account
   - On first account creation, all existing zones are associated with it

#### Environment Variables

```bash
POWERDNS_API_URL=https://dns-admin.example.com/api/v1/pdnsadmin/
POWERDNS_USERNAME=admin                        # Basic Auth for user CRUD
POWERDNS_PASSWORD=<password>
POWERDNS_API_KEY=<api-key>                     # X-API-Key for zone operations
POWERDNS_ACCOUNT_NAME=cyberx                   # account to auto-assign users to
```

---

### Render API (Sidecar Management)

Used to manage the lifecycle of sidecar services (Gotenberg, step-ca) on Render.com — suspend when idle, resume on demand.

#### Setup Steps

1. **Create API key:**
   - Render Dashboard → Account Settings → API Keys → Create API Key
   - Copy → `RENDER_API_KEY`

2. **Get Owner ID:**
   ```bash
   curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
     https://api.render.com/v1/owners | jq '.[0].owner.id'
   ```
   - User format: `usr_xxxxxxxxxxxx`
   - Team format: `tea_xxxxxxxxxxxx`

3. **Get Gotenberg Service ID:**
   - Render Dashboard → Services → cyberx-gotenberg
   - Copy the service ID from the URL or settings → `GOTENBERG_RENDER_SERVICE_ID`

#### Environment Variables

```bash
RENDER_API_KEY=rnd_xxxxxxxxxxxx
RENDER_OWNER_ID=usr_xxxxxxxxxxxx               # or tea_xxxx for teams
RENDER_REPO_URL=https://github.com/org/repo    # for creating new services
GOTENBERG_RENDER_SERVICE_ID=srv_xxxxxxxxxxxx
GOTENBERG_URL=                                 # auto-discovered from Render if empty
```

---

## Roles & Permissions

The system uses a dynamic role-based access control (RBAC) model with 3 system roles and support for custom roles.

### System Roles

#### Admin
- **Base type:** admin
- **Permissions:** All 46 permissions
- **Description:** Full system access. Can manage users, roles, events, email, infrastructure, and all platform features. Cannot be deleted.

#### Sponsor
- **Base type:** sponsor
- **Permissions:** 15 permissions (all invitee permissions + participant management)
- **Description:** Can manage their own sponsored participants — create, edit, invite, and view participant resources. Also has full self-service access (instances, VPN, certificates).

#### Invitee
- **Base type:** invitee
- **Permissions:** 11 permissions (self-service only)
- **Description:** Standard participant access. Can provision instances, request VPN credentials, download certificates, and view their own resources.

### Permission Reference

#### Events (4)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `events.view` | View event list and details | Y | | |
| `events.create` | Create new events | Y | | |
| `events.edit` | Update event details, activate/archive | Y | | |
| `events.delete` | Delete events | Y | | |

#### Participants (6)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `participants.view` | View own/sponsored participants | Y | Y | |
| `participants.view_all` | View all participants system-wide | Y | | |
| `participants.create` | Create new participants | Y | Y | |
| `participants.edit` | Edit participant records | Y | Y | |
| `participants.remove` | Delete/remove participants | Y | | |
| `participants.invite` | Send invitations, trigger reminders | Y | Y | |

#### Instances (6)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `instances.view` | View own instances | Y | Y | Y |
| `instances.view_all` | View all instances across users | Y | | |
| `instances.provision` | Create new instances | Y | Y | Y |
| `instances.delete` | Terminate instances | Y | Y | Y |
| `instances.manage_agent` | Configure and run agent tasks | Y | Y | Y |
| `instances.sync_status` | Sync instance status from cloud | Y | | |

#### VPN (4)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `vpn.view` | View VPN credentials and config | Y | Y | Y |
| `vpn.request` | Request VPN credentials | Y | Y | Y |
| `vpn.download` | Download VPN config files | Y | Y | Y |
| `vpn.manage_pool` | Import/assign/delete VPN credentials | Y | | |

#### Email (6)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `email.view` | View email analytics and queue | Y | | |
| `email.send` | Send individual emails | Y | | |
| `email.send_bulk` | Send bulk emails | Y | | |
| `email.manage_templates` | CRUD email templates | Y | | |
| `email.manage_queue` | Process/cancel queued emails | Y | | |
| `email.manage_workflows` | Configure automated workflows | Y | | |

#### TLS Certificates (3)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `tls.request` | Request TLS certificates | Y | Y | Y |
| `tls.download` | Download TLS certificates | Y | Y | Y |
| `tls.manage` | Manage CA chains, admin cert ops | Y | | |

#### CPE Certificates (2)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `cpe.download` | Download CPE certificates | Y | Y | Y |
| `cpe.manage` | Issue/revoke/regenerate CPE certs | Y | | |

#### Discord (2)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `discord.view` | View Discord invite card | Y | Y | Y |
| `discord.manage` | Configure Discord integration | Y | | |

#### Cloud Infrastructure (3)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `cloud.manage_providers` | Manage cloud provider configs | Y | | |
| `cloud.manage_templates` | CRUD instance templates | Y | | |
| `cloud.manage_images` | Manage cloud-init templates | Y | | |

#### Licenses (2)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `licenses.view` | View license products | Y | | |
| `licenses.manage` | Manage license pool | Y | | |

#### Participant Actions (2)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `actions.view` | View action logs and stats | Y | | |
| `actions.manage` | Create/assign/revoke actions | Y | | |

#### Keycloak (1)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `keycloak.manage` | Manage Keycloak sync | Y | | |

#### Admin / System (5)
| Permission | Description | Admin | Sponsor | Invitee |
|-----------|-------------|:-----:|:-------:|:-------:|
| `admin.manage_users` | Create/edit/delete users | Y | | |
| `admin.manage_roles` | Create/edit/delete roles | Y | | |
| `admin.view_audit_log` | View audit log | Y | | |
| `admin.manage_settings` | Manage system settings | Y | | |
| `scheduler.view` | View scheduler status | Y | | |

### Custom Roles

Admins can create custom roles by cloning a system role and adjusting permissions:

1. Go to **Settings → Roles** in the admin panel
2. Click **New Role** or **Clone** an existing role
3. Choose a **base type** (admin/sponsor/invitee) — controls sidebar and navigation tier
4. Toggle permissions on/off
5. For sponsor-type roles, optionally set **Allowed Role IDs** to restrict which invitee types they can assign

### Per-User Permission Overrides

Individual users can have permissions added or removed on top of their role:

```
Effective Permissions = (Role Permissions + User Adds) - User Removes
```

Overrides are managed via the user edit page in the admin panel or the API:
```
PATCH /api/admin/users/{id}
{ "permission_overrides": { "add": ["events.view"], "remove": ["vpn.download"] } }
```

---

## Related Documentation

- [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) — Complete env var reference with Web/Worker columns
- [SUPABASE_SETUP.md](SUPABASE_SETUP.md) — Supabase database setup guide
- [INSTALL.md](INSTALL.md) — Local development installation
- [CI_CD_SETUP.md](CI_CD_SETUP.md) — GitHub Actions CI/CD pipeline
- [RENDER_SUSPEND_STRATEGY.md](RENDER_SUSPEND_STRATEGY.md) — Cost optimization via service suspend/resume
- [ADMIN_GUIDE.md](ADMIN_GUIDE.md) — Admin user guide
- [EVENT_MANAGEMENT.md](EVENT_MANAGEMENT.md) — Event lifecycle management
- [CLOUD_INIT_TEMPLATE_VARIABLES.md](CLOUD_INIT_TEMPLATE_VARIABLES.md) — Cloud-init template variables
