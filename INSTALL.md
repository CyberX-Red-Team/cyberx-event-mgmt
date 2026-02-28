# CyberX Event Management - Installation Guide

Complete installation instructions for deploying the CyberX Event Management System.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start (Docker)](#quick-start-docker)
- [Manual Installation](#manual-installation)
- [Production Deployment](#production-deployment)
- [External Integrations](#external-integrations)
- [Database Setup](#database-setup)
- [Configuration](#configuration)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

- **Python 3.11+** - Backend runtime
- **PostgreSQL 15+** - Primary database
- **Docker & Docker Compose** - Container orchestration (recommended for dev)
- **Git** - Version control

### System Requirements

**Minimum:**
- 2 CPU cores
- 4GB RAM
- 10GB disk space

**Recommended (Production):**
- 4+ CPU cores
- 8GB+ RAM
- 50GB+ disk space (logs and data growth)

### Required External Services

| Service | Purpose | Required? |
|---------|---------|-----------|
| **SendGrid** | Email delivery | Yes (for any email features) |

### Optional External Services

| Service | Purpose | When Needed |
|---------|---------|-------------|
| **Keycloak** | SSO credential sync, webhook events | Exercise environment with SSO |
| **PowerDNS-Admin** | DNS management account auto-assignment | DNS self-service for participants |
| **Discord** | Single-use invite link generation | Discord-based event communication |
| **OpenStack** | VM instance provisioning | Cloud lab environments |
| **DigitalOcean** | Droplet provisioning | Alternative cloud provider |
| **Cloudflare R2** | Secure file download links | Distributing tools/resources |
| **WireGuard** | VPN credential generation | VPN access to exercise network |

---

## Quick Start (Docker)

Best for development and testing. For production, see [Production Deployment](#production-deployment).

### 1. Clone the Repository

```bash
git clone git@github.com:CyberX-Red-Team/cyberx-event-mgmt.git
cd cyberx-event-mgmt
```

### 2. Start PostgreSQL

```bash
docker compose up -d postgres
docker compose ps  # verify it's running
```

### 3. Set Up Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with minimum required settings:

```env
DATABASE_URL=postgresql+asyncpg://cyberx:changeme@localhost:5432/cyberx_events
SECRET_KEY=dev-secret-key-change-in-production
DEBUG=true
ENABLE_SCHEDULER_IN_WEB=true
SENDGRID_API_KEY=SG.your-sendgrid-api-key
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
SENDGRID_SANDBOX_MODE=true
ADMIN_EMAIL=admin@cyberxredteam.org
ADMIN_PASSWORD=changeme
```

See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for the complete reference of all variables.

**Generate secure keys:**
```bash
# SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(64))"

# ENCRYPTION_KEY (Fernet)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 5. Initialize Database

```bash
alembic upgrade head
```

The admin user is auto-created on first startup if `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set and no admin users exist.

### 6. Start the Application

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Verify

- **Application**: http://localhost:8000
- **API Docs**: http://localhost:8000/api/docs (DEBUG=true only)
- **Health Check**: http://localhost:8000/health

Log in with the admin credentials you configured.

---

## Manual Installation

For environments where Docker is not available.

### 1. Install PostgreSQL

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql-15 postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**macOS (Homebrew):**
```bash
brew install postgresql@15
brew services start postgresql@15
```

### 2. Create Database

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE cyberx_events;
CREATE USER cyberx WITH PASSWORD 'changeme';
GRANT ALL PRIVILEGES ON DATABASE cyberx_events TO cyberx;
\q
```

### 3. Clone and Set Up Application

```bash
git clone git@github.com:CyberX-Red-Team/cyberx-event-mgmt.git
cd cyberx-event-mgmt/backend

python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your settings
```

### 4. Initialize Database and Start

```bash
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Production Deployment

### Architecture

```
Internet -> Nginx (SSL) -> Uvicorn (Web Service) -> PostgreSQL
                        -> Uvicorn (Worker Service) -^
```

The system runs as two services sharing the same codebase and database:
- **Web Service** - Handles HTTP requests (admin UI, API, webhooks)
- **Worker Service** - Runs background jobs (email queue, Keycloak sync, reminders, cleanup)

### Render.com Deployment

The project includes `render.yaml` for Render.com deployment. See [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md) for Render-specific instructions.

Key points:
- Web and Worker services are defined in `render.yaml`
- Secrets (`DATABASE_URL`, `SENDGRID_API_KEY`, etc.) should be set to `sync: false` and managed in the Render dashboard
- `SECRET_KEY`, `CSRF_SECRET_KEY`, `ENCRYPTION_KEY` use `generateValue: true` for auto-generation

### Self-Hosted Deployment

#### 1. Install Nginx

```bash
sudo apt install nginx
```

#### 2. Configure Nginx

Create `/etc/nginx/sites-available/cyberx-event-mgmt`:

```nginx
upstream cyberx_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name events.cyberxredteam.org;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name events.cyberxredteam.org;

    ssl_certificate /etc/letsencrypt/live/events.cyberxredteam.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/events.cyberxredteam.org/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    client_max_body_size 20M;

    location / {
        proxy_pass http://cyberx_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /static/ {
        alias /opt/cyberx-event-mgmt/backend/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

Enable and test:
```bash
sudo ln -s /etc/nginx/sites-available/cyberx-event-mgmt /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 3. SSL Certificate

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d events.cyberxredteam.org
```

#### 4. Create Systemd Services

**Web Service** (`/etc/systemd/system/cyberx-web.service`):

```ini
[Unit]
Description=CyberX Event Management - Web
After=network.target postgresql.service

[Service]
Type=simple
User=cyberx
WorkingDirectory=/opt/cyberx-event-mgmt/backend
Environment="PATH=/opt/cyberx-event-mgmt/backend/venv/bin"
ExecStart=/opt/cyberx-event-mgmt/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Worker Service** (`/etc/systemd/system/cyberx-worker.service`):

```ini
[Unit]
Description=CyberX Event Management - Worker
After=network.target postgresql.service

[Service]
Type=simple
User=cyberx
WorkingDirectory=/opt/cyberx-event-mgmt/backend
Environment="PATH=/opt/cyberx-event-mgmt/backend/venv/bin"
ExecStart=/opt/cyberx-event-mgmt/backend/venv/bin/python -m app.worker
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cyberx-web cyberx-worker
sudo systemctl start cyberx-web cyberx-worker
```

#### 5. Production Environment Variables

```env
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<64-char-random-string>
CSRF_SECRET_KEY=<64-char-random-string>
ENCRYPTION_KEY=<fernet-key>
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/cyberx_events
FRONTEND_URL=https://events.cyberxredteam.org
ALLOWED_HOSTS=events.cyberxredteam.org

ADMIN_EMAIL=admin@cyberxredteam.org
ADMIN_PASSWORD=<secure-password>

SENDGRID_API_KEY=SG.your-key
SENDGRID_FROM_EMAIL=noreply@cyberxredteam.org
SENDGRID_SANDBOX_MODE=false
```

Add optional integrations as needed. See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for all available settings.

---

## External Integrations

Each integration is optional and can be enabled independently.

### SendGrid (Email)

1. Sign up at https://sendgrid.com
2. Create API key: Settings > API Keys > Create API Key (Full Access)
3. Verify sender: Settings > Sender Authentication > Single Sender Verification
4. Set `SENDGRID_API_KEY` and `SENDGRID_FROM_EMAIL`
5. For webhook tracking: Settings > Mail Settings > Event Webhook > enable and point to `https://your-host/api/webhooks/sendgrid`
6. For webhook signature verification: copy the verification key to `SENDGRID_WEBHOOK_VERIFICATION_KEY`

### Keycloak SSO

1. Create a confidential client in Keycloak (e.g., `admin-cli`) with service account enabled
2. Assign the client the `manage-users` realm role (or a custom role with user CRUD)
3. Set `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_ADMIN_CLIENT_ID`, `KEYCLOAK_ADMIN_CLIENT_SECRET`
4. Set `PASSWORD_SYNC_ENABLED=true` when ready
5. Optionally set `KEYCLOAK_USER_GROUPS` to auto-assign users to Keycloak groups

For webhook events (login tracking, PowerDNS auto-assignment):
1. Install the [p2-inc/keycloak-events](https://github.com/p2-inc/keycloak-events) plugin in Keycloak
2. Configure it to POST to `https://your-host/api/webhooks/keycloak`
3. Set `KEYCLOAK_WEBHOOK_SECRET` to the HMAC secret configured in the plugin

### PowerDNS-Admin

1. Set up PowerDNS-Admin with Keycloak OIDC authentication
2. Create a PowerDNS-Admin admin user for API access
3. Create an API key in PowerDNS-Admin UI (Admin/Operator role) for zone operations
4. Set `POWERDNS_API_URL`, `POWERDNS_USERNAME`, `POWERDNS_PASSWORD`, `POWERDNS_API_KEY`
5. Set `POWERDNS_ACCOUNT_NAME` to the account users should be auto-assigned to (default: `cyberx`)
6. When a user logs into PowerDNS-Admin via Keycloak, the webhook auto-assigns them to the account

### Discord

1. Create a bot at https://discord.com/developers/applications
2. Enable the bot and copy its token
3. Invite the bot to your server with `Create Instant Invite` permission
4. Set `DISCORD_BOT_TOKEN` and `DISCORD_INVITE_ENABLED=true`
5. Set the `discord_channel_id` on the event via the admin API

### VPN (WireGuard)

1. Set up a WireGuard server
2. Set `VPN_SERVER_PUBLIC_KEY`, `VPN_SERVER_ENDPOINT`
3. Import VPN credentials via CSV or the admin API
4. Participants download their WireGuard config from the self-service portal

### OpenStack

Supports two authentication methods:

**Application Credentials (recommended):**
```env
OS_AUTH_URL=https://your-openstack/identity/v3
OS_AUTH_TYPE=v3applicationcredential
OS_APPLICATION_CREDENTIAL_ID=your-id
OS_APPLICATION_CREDENTIAL_SECRET=your-secret
```

**Username/Password:**
```env
OS_AUTH_URL=https://your-openstack/identity/v3
OS_AUTH_TYPE=password
OS_USERNAME=your-username
OS_PASSWORD=your-password
OS_PROJECT_NAME=your-project
```

Set default instance configuration (`OS_DEFAULT_FLAVOR_ID`, `OS_DEFAULT_IMAGE_ID`, `OS_DEFAULT_NETWORK_ID`, `OS_DEFAULT_KEY_NAME`) to avoid specifying them on every request.

### DigitalOcean

1. Create an API token at https://cloud.digitalocean.com/account/api/tokens
2. Set `DO_API_TOKEN`
3. Optionally configure `DO_DEFAULT_REGION`, `DO_DEFAULT_SIZE`, `DO_DEFAULT_IMAGE`, `DO_SSH_KEY_ID`

### Download Links (Cloudflare R2)

1. Create an R2 bucket in Cloudflare
2. Generate S3-compatible API credentials
3. Set `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`
4. Optionally set `R2_CUSTOM_DOMAIN` for a custom download URL
5. Set `DOWNLOAD_LINK_MODE=r2`

Alternative: use `DOWNLOAD_LINK_MODE=nginx` with `DOWNLOAD_SECRET` and `DOWNLOAD_BASE_URL` for nginx `secure_link` based downloads.

---

## Database Setup

### Fresh Database

```bash
cd backend
alembic upgrade head
```

The admin user is auto-created on startup if `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set and no admins exist.

### Migrations

```bash
alembic current              # Check current version
alembic history              # List all migrations
alembic upgrade head         # Apply all pending
alembic downgrade -1         # Roll back one
```

### Import Data

```bash
python scripts/import_csv.py /path/to/participants.csv /path/to/vpn-configs.csv
```

### Backups

Create a backup script:

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/cyberx"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
pg_dump -U cyberx cyberx_events | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"
find "$BACKUP_DIR" -name "*.gz" -mtime +30 -delete
```

Schedule with cron: `0 2 * * * /opt/backups/backup-cyberx.sh`

---

## Configuration

All configuration is via environment variables in the `.env` file (or set directly in the environment for production).

See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for the complete reference with descriptions, defaults, and which service uses each variable.

**Key points:**
- Settings are loaded once at startup (`@lru_cache`) -- restart after changes
- `DATABASE_URL` is the only strictly required variable
- All optional integrations (Keycloak, PowerDNS, Discord, etc.) default to disabled/empty
- Use `SENDGRID_SANDBOX_MODE=true` and `TEST_EMAIL_OVERRIDE` for safe testing

---

## Verification

### Health Check

```bash
curl http://localhost:8000/health
```

### Test Authentication

```bash
# Login and save session cookie
curl -c cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin@cyberxredteam.org", "password": "your-password"}'

# Verify session works
curl -b cookies.txt http://localhost:8000/api/auth/me
```

### Check Scheduler

```bash
curl -b cookies.txt http://localhost:8000/api/admin/scheduler/status
```

### Webhook Health

```bash
curl http://localhost:8000/api/webhooks/health
```

---

## Troubleshooting

### Database connection refused

```bash
docker compose ps              # Is postgres running?
docker compose logs postgres   # Check logs
```

For Supabase/remote DB: ensure the connection string uses the pooler endpoint (IPv4) and special characters are URL-encoded.

### Pydantic validation error on startup

Check that `DATABASE_URL` is set. All other variables have defaults and are optional.

### Admin user not created

- Both `ADMIN_EMAIL` and `ADMIN_PASSWORD` must be set
- Only creates if **zero** admin users exist in the database
- Check startup logs for bootstrap messages

### Emails not sending

- Check `SENDGRID_SANDBOX_MODE` (`true` = validated but not delivered)
- Check `TEST_EMAIL_OVERRIDE` (redirects all emails to one address)
- Verify `SENDGRID_FROM_EMAIL` is verified in SendGrid dashboard
- Check email queue: `curl -b cookies.txt http://localhost:8000/api/admin/email-queue/stats`

### Scheduler running twice

- Set `ENABLE_SCHEDULER_IN_WEB=false` in production
- Use a dedicated worker service for background jobs
- Multiple web workers with `ENABLE_SCHEDULER_IN_WEB=true` causes duplicate execution

### Keycloak sync shows disabled

- `PASSWORD_SYNC_ENABLED=true` must be set (check spelling)
- Restart required after changing env vars (settings are cached)

### Webhook signature failures

- For SendGrid: verify `SENDGRID_WEBHOOK_VERIFICATION_KEY` matches the key in SendGrid dashboard
- For Keycloak: verify `KEYCLOAK_WEBHOOK_SECRET` matches the secret in the keycloak-events plugin config
- Set `KEYCLOAK_WEBHOOK_DEBUG=true` to log raw payloads for debugging

---

## Related Documentation

- [SETUP.md](SETUP.md) - Quick start for local development
- [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) - Complete env var reference
- [ADMIN_GUIDE.md](ADMIN_GUIDE.md) - Admin UI and API usage
- [EVENT_MANAGEMENT.md](EVENT_MANAGEMENT.md) - Event lifecycle management
- [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md) - Render.com deployment
- [TESTING_EMAIL_GUIDE.md](TESTING_EMAIL_GUIDE.md) - Email testing guide
- [SECURITY.md](SECURITY.md) - Security considerations
- [backend/docs/keycloak-password-sync-design.md](backend/docs/keycloak-password-sync-design.md) - Keycloak sync design
