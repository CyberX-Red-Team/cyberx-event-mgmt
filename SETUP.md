# CyberX Event Management - Quick Start

Get the application running locally for development.

## Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose** (for PostgreSQL)
- **SendGrid account** (for email features -- can use sandbox mode for testing)

## 1. Start PostgreSQL

```bash
cd cyberx-event-mgmt
docker compose up -d postgres
docker compose ps  # verify it's running
```

## 2. Set Up Python Environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with the minimum required settings:

```env
DATABASE_URL=postgresql+asyncpg://cyberx:changeme@localhost:5432/cyberx_events
SECRET_KEY=dev-secret-key-change-in-production
DEBUG=true
ENABLE_SCHEDULER_IN_WEB=true

# SendGrid (use sandbox mode for local dev)
SENDGRID_API_KEY=SG.your-key
SENDGRID_FROM_EMAIL=noreply@example.com
SENDGRID_SANDBOX_MODE=true

# Optional: redirect all emails to yourself during testing
# TEST_EMAIL_OVERRIDE=your-email@example.com

# Optional: auto-create admin user on first startup
ADMIN_EMAIL=admin@cyberxredteam.org
ADMIN_PASSWORD=changeme
```

See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for the complete variable reference.

## 4. Initialize Database

```bash
# Run all migrations
alembic upgrade head
```

If you set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`, the admin user is created automatically on first startup. Otherwise, create one manually:

```bash
python scripts/create_admin.py admin@cyberxredteam.org your-password
```

## 5. Start the Application

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open your browser:
- **Application**: http://localhost:8000
- **API Docs** (DEBUG=true only): http://localhost:8000/api/docs
- **Health Check**: http://localhost:8000/health

Log in with the admin credentials you configured.

## 6. Import Data (Optional)

```bash
# Import participants and VPN configurations from CSV
python scripts/import_csv.py /path/to/participants.csv /path/to/vpn-configs.csv
```

**Participants CSV** columns: `email`, `first_name`, `last_name`, `country` (required), plus optional `pandas_username`, `sponsor_email`, `discord_username`.

**VPN Configs CSV** columns: `interface_ip`, `ipv4_address`, `private_key` (required), plus optional `ipv6_local`, `ipv6_global`, `preshared_key`.

---

## Optional Integrations

These are not needed for basic operation. Configure them when ready.

### Keycloak SSO

Syncs participant credentials to Keycloak for SSO access to exercise tools.

```env
KEYCLOAK_URL=https://auth.cyberxredteam.org
KEYCLOAK_REALM=cyberx
KEYCLOAK_ADMIN_CLIENT_ID=admin-cli
KEYCLOAK_ADMIN_CLIENT_SECRET=your-client-secret
PASSWORD_SYNC_ENABLED=true
```

The background job syncs every 5 minutes. See [Keycloak Password Sync Design](backend/docs/keycloak-password-sync-design.md) for details.

### Keycloak Webhooks

Receives Keycloak login/register events via the p2-inc/keycloak-events plugin. Used for audit logging and PowerDNS-Admin auto-account assignment.

```env
KEYCLOAK_WEBHOOK_SECRET=your-hmac-secret
# KEYCLOAK_WEBHOOK_DEBUG=true  # uncomment to log raw payloads
```

### PowerDNS-Admin

Auto-assigns users to a DNS management account on first login via Keycloak SSO.

```env
POWERDNS_API_URL=https://dns.cyberxredteam.org/api/v1/pdnsadmin/
POWERDNS_USERNAME=admin
POWERDNS_PASSWORD=your-password
POWERDNS_API_KEY=your-api-key
POWERDNS_ACCOUNT_NAME=cyberx
```

### Discord Invites

Generates single-use Discord invite links for confirmed participants.

```env
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_INVITE_ENABLED=true
```

Also requires setting `discord_channel_id` on the event via the admin API.

### VPN (WireGuard)

```env
VPN_SERVER_PUBLIC_KEY=base64-encoded-key
VPN_SERVER_ENDPOINT=vpn.example.com:51820
VPN_DNS_SERVERS=10.20.200.1
VPN_ALLOWED_IPS=10.0.0.0/8,fd00:a::/32
```

### OpenStack Instance Provisioning

```env
OS_AUTH_URL=https://your-openstack/identity/v3
OS_AUTH_TYPE=v3applicationcredential
OS_APPLICATION_CREDENTIAL_ID=your-credential-id
OS_APPLICATION_CREDENTIAL_SECRET=your-credential-secret
```

### DigitalOcean Instance Provisioning

```env
DO_API_TOKEN=your-api-token
DO_DEFAULT_REGION=nyc1
DO_DEFAULT_SIZE=s-1vcpu-1gb
```

### Download Links (Cloudflare R2)

```env
R2_ACCOUNT_ID=your-account-id
R2_ACCESS_KEY_ID=your-access-key
R2_SECRET_ACCESS_KEY=your-secret-key
R2_BUCKET=your-bucket
DOWNLOAD_LINK_MODE=r2
```

---

## Database

### Run Migrations

```bash
alembic upgrade head        # Apply all pending migrations
alembic current             # Check current migration version
alembic history             # List migration history
alembic downgrade -1        # Roll back one migration
```

### Create a New Migration

```bash
alembic revision --autogenerate -m "description of change"
```

### Reset Database (Development Only)

```bash
docker compose down -v
docker compose up -d postgres
alembic upgrade head
```

---

## Background Jobs

In production, background jobs run in a separate worker service. For local development, set `ENABLE_SCHEDULER_IN_WEB=true` to run them in the web process.

Jobs include:
- **Email queue processor** -- sends queued emails (every `BULK_EMAIL_INTERVAL_MINUTES`, default 45 min)
- **Keycloak password sync** -- syncs credentials to Keycloak (every `PASSWORD_SYNC_INTERVAL_MINUTES`, default 5 min)
- **Invitation reminders** -- sends reminder emails (every `REMINDER_CHECK_INTERVAL_HOURS`, default 24 hr)
- **Session cleanup** -- removes expired sessions (hourly)
- **Scheduler heartbeat** -- writes health status to DB (every 60 seconds)

---

## Testing

```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/test_auth.py -v
```

### Testing Reminders

Use the admin API to trigger reminders without waiting for the configured timeframes:

```bash
# Dry run -- see who would get reminders
curl -b cookies.txt -X POST "http://localhost:8000/api/admin/reminders/trigger?dry_run=true"

# Trigger stage 1 for all eligible users
curl -b cookies.txt -X POST "http://localhost:8000/api/admin/reminders/trigger?stage=1"

# Force re-send even if already sent
curl -b cookies.txt -X POST "http://localhost:8000/api/admin/reminders/trigger?stage=1&force=true"
```

### Testing Emails

See [TESTING_EMAIL_GUIDE.md](TESTING_EMAIL_GUIDE.md) for detailed email testing instructions.

Useful settings for testing:
- `SENDGRID_SANDBOX_MODE=true` -- validates without sending
- `TEST_EMAIL_OVERRIDE=your@email.com` -- redirects all emails to you

---

## Troubleshooting

**Database connection refused:**
```bash
docker compose ps              # Check if postgres is running
docker compose logs postgres   # Check postgres logs
```

**Pydantic validation error on startup:**
- `DATABASE_URL` is the only strictly required variable. Check it's set.

**Emails not sending:**
- Check `SENDGRID_SANDBOX_MODE` (true = no delivery)
- Check `TEST_EMAIL_OVERRIDE` (redirects all emails)
- Check `SENDGRID_API_KEY` and `SENDGRID_FROM_EMAIL`

**"Keycloak sync disabled" in admin UI:**
- Set `PASSWORD_SYNC_ENABLED=true` in `.env` and restart (settings are cached at startup)

**Scheduler running twice:**
- Set `ENABLE_SCHEDULER_IN_WEB=false` and use a separate worker process

---

## Related Documentation

- [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) -- Complete env var reference
- [INSTALL.md](INSTALL.md) -- Production installation guide
- [ADMIN_GUIDE.md](ADMIN_GUIDE.md) -- Admin UI and API usage
- [EVENT_MANAGEMENT.md](EVENT_MANAGEMENT.md) -- Event lifecycle
- [TESTING_EMAIL_GUIDE.md](TESTING_EMAIL_GUIDE.md) -- Email testing
- [backend/docs/keycloak-password-sync-design.md](backend/docs/keycloak-password-sync-design.md) -- Keycloak sync design
