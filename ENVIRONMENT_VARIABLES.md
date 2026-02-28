# Environment Variables Reference

Complete reference for all environment variables used by the CyberX Event Management System.

## Service Architecture

The system consists of two services:
- **Web Service** - FastAPI web application (handles HTTP requests, admin UI, webhooks)
- **Worker Service** - Background scheduler (sends emails, reminders, Keycloak sync, cleanup tasks)

Both services share the same codebase and config. The **Web** and **Worker** columns below indicate which service uses each variable.

> **Note:** Settings are loaded once at startup via `@lru_cache`. Changes to environment variables require a restart to take effect.

---

## Database

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `DATABASE_URL` | Yes | Yes | Yes | - | PostgreSQL connection string. Supports both `postgresql://` and `postgresql+asyncpg://` prefixes (auto-converted). |

**Notes:**
- Use Supabase **pooler endpoint** (IPv4) for Render.com compatibility
- URL-encode special characters in password (e.g., `@` becomes `%40`, `#` becomes `%23`)
- Set to `sync: false` in render.yaml to prevent blueprint overwriting manual configuration

---

## Application Core

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `ENVIRONMENT` | Recommended | Yes | Yes | `development` | Environment name (`development`, `staging`, `production`). Controls version string format (staging appends git hash) and cookie security. |
| `SECRET_KEY` | Yes (web) | Yes | Yes | `""` | Secret key for session signing, CSRF tokens, and encryption fallback. Generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`. |
| `CSRF_SECRET_KEY` | No | Yes | No | `""` | Separate CSRF token signing key. Falls back to `SECRET_KEY` if empty. |
| `ENCRYPTION_KEY` | No | Yes | Yes | `""` | Fernet key for field-level encryption (e.g., password sync queue). Falls back to `SECRET_KEY` if empty. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `DEBUG` | No | Yes | No | `false` | Enables debug mode. When `false`, session cookies are set with `Secure` flag (HTTPS only). |
| `ALLOWED_HOSTS` | No | Yes | No | `localhost,127.0.0.1` | Comma-separated hostnames the app will respond to. |
| `CORS_ORIGINS` | No | Yes | No | `["http://localhost:3000", "http://localhost:8000"]` | Allowed CORS origins (JSON list). |
| `FRONTEND_URL` | No | Yes | Yes | `http://localhost:8000` | Base URL for links in emails (confirmation URLs, password reset links, etc.). |

---

## Admin User Bootstrapping

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `ADMIN_EMAIL` | No | Yes | No | `""` | If set, creates an admin user on startup (only if no admin users exist in DB). |
| `ADMIN_PASSWORD` | No | Yes | No | `""` | Password for the bootstrapped admin. Required if `ADMIN_EMAIL` is set. |
| `ADMIN_FIRST_NAME` | No | Yes | No | `Admin` | First name for the bootstrapped admin. |
| `ADMIN_LAST_NAME` | No | Yes | No | `User` | Last name for the bootstrapped admin. |

**Notes:**
- Only creates admin if **zero** admin users exist in the database
- Safe to leave configured permanently -- won't overwrite existing admins
- Useful for first deployment to a fresh database

---

## Email (SendGrid)

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `SENDGRID_API_KEY` | Yes | Yes | Yes | `""` | SendGrid API key for sending emails. |
| `SENDGRID_FROM_EMAIL` | Yes | Yes | Yes | `""` | Verified sender email address in SendGrid. |
| `SENDGRID_FROM_NAME` | No | Yes | Yes | `CyberX Red Team` | Display name for outbound emails. |
| `SENDGRID_SANDBOX_MODE` | No | Yes | Yes | `false` | When `true`, emails are validated by SendGrid but not delivered. Useful for staging. |
| `SENDGRID_WEBHOOK_VERIFICATION_KEY` | No | Yes | No | `""` | ECDSA public key for verifying SendGrid Event Webhook signatures. Get from SendGrid Dashboard > Settings > Mail Settings > Event Webhook > Signature Verification. |
| `TEST_EMAIL_OVERRIDE` | No | Yes | Yes | `""` | If set, **all** outbound emails are redirected to this address instead of the actual recipient. Useful for testing with real SendGrid delivery. |

---

## Email Job & Queue

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `BULK_EMAIL_INTERVAL_MINUTES` | No | Yes | Yes | `45` | How often the background email queue processor runs (in minutes). |

---

## Session

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `SESSION_EXPIRY_HOURS` | No | Yes | No | `24` | How long admin/user sessions remain valid before requiring re-login. |

---

## Invitation Reminders

Multi-stage reminder system for participants who haven't confirmed. The background job runs every `REMINDER_CHECK_INTERVAL_HOURS` and processes each enabled stage.

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `REMINDER_1_ENABLED` | No | Yes | Yes | `false` | Master toggle for Stage 1 reminders. |
| `REMINDER_1_DAYS_AFTER_INVITE` | No | Yes | Yes | `7` | Days after initial invitation to send Stage 1 reminder. Uses a 3-day eligibility window. |
| `REMINDER_1_MIN_DAYS_BEFORE_EVENT` | No | Yes | Yes | `14` | Minimum days before event start for Stage 1 to fire. Prevents sending if event is imminent. |
| `REMINDER_2_ENABLED` | No | Yes | Yes | `false` | Master toggle for Stage 2 reminders. |
| `REMINDER_2_DAYS_AFTER_INVITE` | No | Yes | Yes | `14` | Days after initial invitation to send Stage 2 reminder. |
| `REMINDER_2_MIN_DAYS_BEFORE_EVENT` | No | Yes | Yes | `7` | Minimum days before event start for Stage 2 to fire. |
| `REMINDER_3_ENABLED` | No | Yes | Yes | `false` | Master toggle for Stage 3 (final) reminders. |
| `REMINDER_3_DAYS_BEFORE_EVENT` | No | Yes | Yes | `3` | Days before event start to send the final "last chance to RSVP" reminder. Fires within a 24-hour window. |
| `REMINDER_CHECK_INTERVAL_HOURS` | No | Yes | Yes | `24` | How often the reminder background job runs. |

**Notes:**
- Each stage can be independently enabled/disabled
- Reminders only go to participants with status `INVITED` or `NO_RESPONSE`
- Event test mode restricts reminders to sponsors only
- Use `POST /api/admin/reminders/trigger` to test without waiting for timeframes

---

## VPN (WireGuard)

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `VPN_SERVER_PUBLIC_KEY` | No | Yes | No | `""` | WireGuard server public key. Embedded in generated client configs. |
| `VPN_SERVER_ENDPOINT` | No | Yes | No | `""` | WireGuard server address and port. |
| `VPN_DNS_SERVERS` | No | Yes | No | `10.20.200.1` | DNS servers pushed to VPN clients. |
| `VPN_ALLOWED_IPS` | No | Yes | No | `10.0.0.0/8,fd00:a::/32` | IP ranges routed through the VPN tunnel. |

**Notes:**
- Only needed if generating WireGuard VPN credentials for participants
- Safe to leave empty if not using VPN features

---

## PowerDNS-Admin

Used for auto-assigning users to a DNS management account when they log into PowerDNS-Admin via Keycloak SSO.

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `POWERDNS_API_URL` | No | Yes | No | `""` | PowerDNS-Admin API base URL. Must end with `/api/v1/pdnsadmin/`. |
| `POWERDNS_USERNAME` | No | Yes | No | `""` | PowerDNS-Admin username for Basic Auth (user/account CRUD). |
| `POWERDNS_PASSWORD` | No | Yes | No | `""` | PowerDNS-Admin password for Basic Auth. |
| `POWERDNS_API_KEY` | No | Yes | No | `""` | API key for PowerDNS server zone operations (created in PowerDNS-Admin UI with Admin/Operator role). Used for zone-account association via `X-API-Key` header. |
| `POWERDNS_ACCOUNT_NAME` | No | Yes | No | `cyberx` | Account name to auto-assign users to on first PowerDNS-Admin login. If the account doesn't exist, it's auto-created and all zones are associated with it. |

**How it works:**
1. User logs into PowerDNS-Admin via Keycloak SSO
2. Keycloak fires a LOGIN webhook with `client_id=powerdns-admin`
3. The webhook handler queries PowerDNS-Admin to check if the user has accounts
4. If not, the user is added to the configured account (created if needed)
5. On first account creation, all existing zones are associated with the account

---

## Keycloak SSO Integration

Used for syncing participant credentials to Keycloak for SSO access to exercise infrastructure (PowerDNS-Admin, Guacamole, etc.).

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `KEYCLOAK_URL` | No | Yes | Yes | `""` | Keycloak base URL (no trailing slash). |
| `KEYCLOAK_REALM` | No | Yes | Yes | `cyberx` | Keycloak realm name. |
| `KEYCLOAK_ADMIN_CLIENT_ID` | No | Yes | Yes | `admin-cli` | Service account client ID with `manage-users` realm role. |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | No | Yes | Yes | `""` | Client secret for the service account. |
| `KEYCLOAK_USER_GROUPS` | No | Yes | Yes | `""` | Comma-separated Keycloak group names to assign synced users to (e.g., `cyberx-users,participants`). |
| `KEYCLOAK_WEBHOOK_SECRET` | No | Yes | No | `""` | HMAC-SHA256 secret for verifying inbound Keycloak event webhooks (from p2-inc/keycloak-events plugin). |
| `KEYCLOAK_WEBHOOK_DEBUG` | No | Yes | No | `false` | Log raw webhook payloads for debugging signature/payload issues. |

**Setup steps:**
1. Create a confidential client in Keycloak (e.g., `admin-cli`) with service account enabled
2. Assign the client the `manage-users` realm role
3. Set `KEYCLOAK_URL`, `KEYCLOAK_ADMIN_CLIENT_SECRET`
4. Set `PASSWORD_SYNC_ENABLED=true` when ready to start syncing

---

## Password Sync (Keycloak)

Controls the background job that syncs participant credentials to Keycloak.

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `PASSWORD_SYNC_ENABLED` | No | Yes | Yes | `false` | Master toggle. Keep `false` until Keycloak is fully stood up and reachable. |
| `PASSWORD_SYNC_INTERVAL_MINUTES` | No | Yes | Yes | `5` | How often the background sync job runs. |
| `PASSWORD_SYNC_MAX_RETRIES` | No | Yes | Yes | `5` | Max API-error retries per user before giving up. Connectivity errors (Keycloak unreachable) do **not** consume retries. |

**Notes:**
- Only syncs users with role `invitee` or `sponsor` (admins are excluded)
- Sync is queued on: participant confirmation, password change, password reset, admin manual trigger
- The job gracefully handles Keycloak being unreachable -- it will succeed on the next interval once Keycloak is up

---

## Discord Integration

Generates unique, single-use Discord invite links for confirmed participants.

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `DISCORD_BOT_TOKEN` | No | Yes | No | `""` | Bot token from Discord Developer Portal. Bot needs `Create Instant Invite` permission. |
| `DISCORD_INVITE_ENABLED` | No | Yes | No | `false` | Master toggle. Also requires `discord_channel_id` to be set on the event. |

**Setup steps:**
1. Create a Discord bot at https://discord.com/developers/applications
2. Invite the bot to your server with `Create Instant Invite` permission
3. Set the `discord_channel_id` on the event via the admin API
4. Set `DISCORD_INVITE_ENABLED=true`

---

## OpenStack Integration

Used for provisioning virtual machine instances on OpenStack infrastructure.

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `OS_AUTH_URL` | No | Yes | No | `""` | Keystone authentication endpoint. |
| `OS_AUTH_TYPE` | No | Yes | No | `v3applicationcredential` | Auth method: `v3applicationcredential` or `password`. |
| `OS_APPLICATION_CREDENTIAL_ID` | No | Yes | No | `""` | Application credential ID (for `v3applicationcredential` auth). |
| `OS_APPLICATION_CREDENTIAL_SECRET` | No | Yes | No | `""` | Application credential secret. |
| `OS_USERNAME` | No | Yes | No | `""` | OpenStack username (for `password` auth). |
| `OS_PASSWORD` | No | Yes | No | `""` | OpenStack password (for `password` auth). |
| `OS_PROJECT_NAME` | No | Yes | No | `""` | OpenStack project/tenant name (for `password` auth). |
| `OS_USER_DOMAIN_NAME` | No | Yes | No | `Default` | User domain name. |
| `OS_PROJECT_DOMAIN_NAME` | No | Yes | No | `Default` | Project domain name. |
| `OS_NOVA_URL` | No | Yes | No | `""` | Nova (compute) API URL. Auto-discovered from Keystone catalog if empty. |
| `OS_NEUTRON_URL` | No | Yes | No | `""` | Neutron (networking) API URL. Auto-discovered if empty. |
| `OS_GLANCE_URL` | No | Yes | No | `""` | Glance (image) API URL. Auto-discovered if empty. |

### Default Instance Configuration

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `OS_DEFAULT_FLAVOR_ID` | No | Yes | No | `""` | Default compute flavor. Can be overridden per-request. |
| `OS_DEFAULT_IMAGE_ID` | No | Yes | No | `""` | Default OS image. Can be overridden per-request. |
| `OS_DEFAULT_NETWORK_ID` | No | Yes | No | `""` | Default network. Can be overridden per-request. |
| `OS_DEFAULT_KEY_NAME` | No | Yes | No | `""` | Default SSH keypair name. Can be overridden per-request. |

---

## DigitalOcean Integration

Used for provisioning droplets on DigitalOcean as an alternative to OpenStack.

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `DO_API_TOKEN` | No | Yes | No | `""` | DigitalOcean API token. |
| `DO_DEFAULT_REGION` | No | Yes | No | `nyc1` | Default droplet region. |
| `DO_DEFAULT_SIZE` | No | Yes | No | `s-1vcpu-1gb` | Default droplet size slug. |
| `DO_DEFAULT_IMAGE` | No | Yes | No | `ubuntu-22-04-x64` | Default droplet image. |
| `DO_SSH_KEY_ID` | No | Yes | No | `""` | SSH key ID or fingerprint to inject into droplets. |

---

## Download Links (Cloudflare R2 / nginx)

Used for generating time-limited, secure download links for participant resources (e.g., VPN configs, tools).

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `DOWNLOAD_LINK_MODE` | No | Yes | No | `r2` | Download link backend: `r2` (Cloudflare R2 presigned URLs) or `nginx` (nginx `secure_link` module). |
| `DOWNLOAD_LINK_EXPIRY` | No | Yes | No | `3600` | Link expiry time in seconds (default 1 hour). |

### Cloudflare R2 Mode (`DOWNLOAD_LINK_MODE=r2`)

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `R2_ACCOUNT_ID` | No | Yes | No | `""` | Cloudflare account ID. |
| `R2_ACCESS_KEY_ID` | No | Yes | No | `""` | R2 S3-compatible access key. |
| `R2_SECRET_ACCESS_KEY` | No | Yes | No | `""` | R2 S3-compatible secret key. |
| `R2_BUCKET` | No | Yes | No | `""` | R2 bucket name. |
| `R2_CUSTOM_DOMAIN` | No | Yes | No | `""` | Custom domain for R2 bucket (optional, uses R2 default URL if empty). |

### nginx Mode (`DOWNLOAD_LINK_MODE=nginx`)

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `DOWNLOAD_SECRET` | No | Yes | No | `""` | Shared secret for nginx `secure_link` MD5 hash generation. |
| `DOWNLOAD_BASE_URL` | No | Yes | No | `""` | Base URL for nginx-served download files. |

---

## Render API

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `RENDER_API_KEY` | No | Yes | No | `""` | Render.com API key for deployment automation features. |

---

## Background Scheduler Control

| Variable | Required | Web | Worker | Default | Description |
|----------|----------|-----|--------|---------|-------------|
| `ENABLE_SCHEDULER_IN_WEB` | No | Yes | No | `false` | Run the background scheduler inside the web process. **Only for local development** -- use a dedicated worker service in production. |

**Warning:** Running with `--workers 2+` and `ENABLE_SCHEDULER_IN_WEB=true` causes duplicate job execution.

---

## Staging vs Production

| Variable | Staging | Production |
|----------|---------|------------|
| `ENVIRONMENT` | `staging` | `production` |
| `DEBUG` | `true` or `false` | `false` |
| `SENDGRID_SANDBOX_MODE` | `true` (no real emails) | `false` |
| `FRONTEND_URL` | `https://staging.events.cyberxredteam.org` | `https://events.cyberxredteam.org` |
| `ALLOWED_HOSTS` | `staging.events.cyberxredteam.org` | `events.cyberxredteam.org` |
| `TEST_EMAIL_OVERRIDE` | your test email address | `""` (empty) |

---

## Quick Reference

### Minimal (Local Development)

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/cyberx_events
SECRET_KEY=dev-secret-key-change-in-production
SENDGRID_API_KEY=SG.your-key
SENDGRID_FROM_EMAIL=noreply@example.com
DEBUG=true
ENABLE_SCHEDULER_IN_WEB=true
```

### Minimal (Production)

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/cyberx_events
SECRET_KEY=<64-char-random-string>
SENDGRID_API_KEY=SG.your-key
SENDGRID_FROM_EMAIL=noreply@cyberxredteam.org
ENVIRONMENT=production
ADMIN_EMAIL=admin@cyberxredteam.org
ADMIN_PASSWORD=<secure-password>
FRONTEND_URL=https://events.cyberxredteam.org
ALLOWED_HOSTS=events.cyberxredteam.org
```

---

## Security Notes

**Auto-generated by Render (use `generateValue: true`):**
- `SECRET_KEY`, `CSRF_SECRET_KEY`, `ENCRYPTION_KEY`

**Set to `sync: false` in render.yaml (manage manually in dashboard):**
- `DATABASE_URL`, `SENDGRID_API_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`
- `KEYCLOAK_ADMIN_CLIENT_SECRET`, `KEYCLOAK_WEBHOOK_SECRET`
- `POWERDNS_PASSWORD`, `POWERDNS_API_KEY`
- `DISCORD_BOT_TOKEN`, `DO_API_TOKEN`, `RENDER_API_KEY`
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`

**Password encoding in DATABASE_URL:**
- `@` -> `%40`, `#` -> `%23`, `$` -> `%24`, `:` -> `%3A`

---

## Troubleshooting

**"Pydantic validation error" on startup:**
- `DATABASE_URL` is the only strictly required variable. All others have defaults.
- `SECRET_KEY` is required for the web service but not for standalone scripts.

**"Emails not sending":**
- Check `SENDGRID_SANDBOX_MODE` (true = validated but not delivered)
- Check `TEST_EMAIL_OVERRIDE` (redirects all emails to one address)
- Verify `SENDGRID_FROM_EMAIL` is verified in SendGrid dashboard

**"Keycloak sync disabled" in admin UI:**
- `PASSWORD_SYNC_ENABLED` must be `true` (check spelling)
- Settings are cached at startup -- restart after changing env vars

**"Scheduler running twice / duplicate emails":**
- Set `ENABLE_SCHEDULER_IN_WEB=false` in production
- Use dedicated worker service for background jobs

**"Admin user not created on startup":**
- Only creates if **zero** admin users exist in the database
- Check both `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set

---

## Related Documentation

- [Setup Guide](SETUP.md)
- [Admin Guide](ADMIN_GUIDE.md)
- [Supabase Setup](SUPABASE_SETUP.md)
- [Testing Email Guide](TESTING_EMAIL_GUIDE.md)
- [Keycloak Password Sync Design](backend/docs/keycloak-password-sync-design.md)
