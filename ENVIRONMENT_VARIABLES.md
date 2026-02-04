# Environment Variables Reference

Complete reference for all environment variables required by the CyberX Event Management System.

## Service Architecture

The system consists of two services:
- **Web Service** - FastAPI web application (handles HTTP requests)
- **Worker Service** - Background scheduler (sends emails, reminders, cleanup tasks)

---

## Required Environment Variables

### Database

| Variable | Required | Web | Worker | Description | Example |
|----------|----------|-----|--------|-------------|---------|
| `DATABASE_URL` | ✅ Yes | ✅ | ✅ | PostgreSQL connection string with asyncpg driver | `postgresql+asyncpg://user:pass@host:5432/db` |

**Important Notes:**
- Use Supabase **pooler endpoint** (IPv4) for Render.com compatibility
- URL-encode special characters in password (e.g., `@` becomes `%40`)
- Ensure connection string uses `postgresql+asyncpg://` for async support
- Set to `sync: false` in render.yaml to prevent blueprint overwriting manual configuration

---

### Application Settings

| Variable | Required | Web | Worker | Description | Default | Example |
|----------|----------|-----|--------|-------------|---------|---------|
| `ENVIRONMENT` | Recommended | ✅ | ✅ | Environment name for logging | `development` | `staging`, `production` |
| `SECRET_KEY` | ✅ Yes | ✅ | ✅ | Secret key for session signing and encryption | - | (generate 32+ char random string) |
| `CSRF_SECRET_KEY` | Optional | ✅ | ❌ | CSRF token signing key (uses SECRET_KEY if not set) | `` | (generate random string) |
| `ENCRYPTION_KEY` | Optional | ✅ | ❌ | Fernet key for field-level encryption (uses SECRET_KEY if not set) | `` | (32 URL-safe base64 bytes) |
| `DEBUG` | Optional | ✅ | ❌ | Enable debug mode (disables in production) | `false` | `true`, `false` |
| `ALLOWED_HOSTS` | Optional | ✅ | ❌ | Comma-separated list of allowed hostnames | `localhost,127.0.0.1` | `events.cyberxredteam.org` |
| `FRONTEND_URL` | Optional | ✅ | ✅ | Base URL for frontend links in emails | `http://localhost:8000` | `https://events.cyberxredteam.org` |

---

### Admin User Bootstrapping

| Variable | Required | Web | Worker | Description | Default | Example |
|----------|----------|-----|--------|-------------|---------|---------|
| `ADMIN_EMAIL` | Optional | ✅ | ❌ | Email for initial admin user (only created if no admins exist) | `` | `admin@cyberxredteam.org` |
| `ADMIN_PASSWORD` | Optional | ✅ | ❌ | Password for initial admin user | `` | `SecurePassword123!` |
| `ADMIN_FIRST_NAME` | Optional | ✅ | ❌ | First name for initial admin user | `Admin` | `Admin` |
| `ADMIN_LAST_NAME` | Optional | ✅ | ❌ | Last name for initial admin user | `User` | `User` |

**Important Notes:**
- Only creates admin user if **NO** admin users exist in the database
- Safe to leave configured - won't reset passwords on existing admins
- Automatically creates admin on first deployment to fresh database
- Set `sync: false` in render.yaml to manage manually in Render dashboard

---

### Email (SendGrid)

| Variable | Required | Web | Worker | Description | Default | Example |
|----------|----------|-----|--------|-------------|---------|---------|
| `SENDGRID_API_KEY` | ✅ Yes | ✅ | ✅ | SendGrid API key for sending emails | - | `SG.xxxxx` |
| `SENDGRID_FROM_EMAIL` | ✅ Yes | ✅ | ✅ | Sender email address (must be verified in SendGrid) | - | `noreply@cyberxredteam.org` |
| `SENDGRID_FROM_NAME` | Optional | ✅ | ✅ | Sender display name | `CyberX Red Team` | `CyberX Red Team` |
| `SENDGRID_SANDBOX_MODE` | Optional | ✅ | ✅ | Enable sandbox mode (validates emails without sending) | `false` | `true` (staging), `false` (production) |
| `TEST_EMAIL_OVERRIDE` | Optional | ✅ | ✅ | If set, all emails go to this address instead | `` | `test@example.com` |

---

### VPN Configuration (Optional)

| Variable | Required | Web | Worker | Description | Default | Example |
|----------|----------|-----|--------|-------------|---------|---------|
| `VPN_SERVER_PUBLIC_KEY` | Optional | ✅ | ❌ | WireGuard server public key | `` | `base64-encoded-key` |
| `VPN_SERVER_ENDPOINT` | Optional | ✅ | ❌ | WireGuard server endpoint | `` | `vpn.example.com:51820` |
| `VPN_DNS_SERVERS` | Optional | ✅ | ❌ | DNS servers for VPN clients | `10.20.200.1` | `10.20.200.1` |
| `VPN_ALLOWED_IPS` | Optional | ✅ | ❌ | Allowed IPs for VPN routing | `10.0.0.0/8,fd00:a::/32` | `10.0.0.0/8,fd00:a::/32` |

**Note:** Only needed if using VPN credential generation features. Safe to leave empty if not using VPN features.

---

### PowerDNS Configuration (Optional)

| Variable | Required | Web | Worker | Description | Default | Example |
|----------|----------|-----|--------|-------------|---------|---------|
| `POWERDNS_API_URL` | Optional | ✅ | ❌ | PowerDNS API endpoint | `` | `https://dns.example.com/api/v1` |
| `POWERDNS_USERNAME` | Optional | ✅ | ❌ | PowerDNS API username | `` | `admin` |
| `POWERDNS_PASSWORD` | Optional | ✅ | ❌ | PowerDNS API password | `` | `password` |

**Note:** Only needed if using PowerDNS integration for DNS management. Safe to leave empty if not using PowerDNS.

---

### Session & Job Configuration

| Variable | Required | Web | Worker | Description | Default | Example |
|----------|----------|-----|--------|-------------|---------|---------|
| `SESSION_EXPIRY_HOURS` | Optional | ✅ | ❌ | Session expiration time in hours | `24` | `24` |
| `BULK_EMAIL_INTERVAL_MINUTES` | Optional | ✅ | ✅ | Interval between bulk email job runs | `45` | `45` |

---

### Reminder Configuration

| Variable | Required | Web | Worker | Description | Default | Example |
|----------|----------|-----|--------|-------------|---------|---------|
| `REMINDER_1_DAYS_AFTER_INVITE` | Optional | ✅ | ✅ | Days after invite to send first reminder | `7` | `7` |
| `REMINDER_1_MIN_DAYS_BEFORE_EVENT` | Optional | ✅ | ✅ | Min days before event for first reminder | `14` | `14` |
| `REMINDER_2_DAYS_AFTER_INVITE` | Optional | ✅ | ✅ | Days after invite to send second reminder | `14` | `14` |
| `REMINDER_2_MIN_DAYS_BEFORE_EVENT` | Optional | ✅ | ✅ | Min days before event for second reminder | `7` | `7` |
| `REMINDER_3_DAYS_BEFORE_EVENT` | Optional | ✅ | ✅ | Days before event to send final reminder | `3` | `3` |
| `REMINDER_CHECK_INTERVAL_HOURS` | Optional | ✅ | ✅ | How often to check for reminders to send | `24` | `24` |

---

### Background Scheduler Control

| Variable | Required | Web | Worker | Description | Default | Example |
|----------|----------|-----|--------|-------------|---------|---------|
| `ENABLE_SCHEDULER_IN_WEB` | Optional | ✅ | ❌ | Enable scheduler in web service (for local dev only) | `false` | `false` (production), `true` (local dev) |

**Important Notes:**
- Set to `false` in production (use dedicated worker service)
- Set to `true` for local development on single machine
- Running with `--workers 2+` and `ENABLE_SCHEDULER_IN_WEB=true` causes duplicate jobs

---

## Render.com Configuration Guide

### Web Service Environment Variables

Configure in Render Dashboard → Web Service → Environment:

**Always Required:**
```bash
DATABASE_URL=postgresql+asyncpg://...  # Set manually, sync: false in render.yaml
SECRET_KEY=<auto-generated>             # Auto-generated by Render
SENDGRID_API_KEY=<your-key>            # Set manually, sync: false
SENDGRID_FROM_EMAIL=<your-email>       # Set manually, sync: false
```

**Recommended for Production:**
```bash
ENVIRONMENT=production
ADMIN_EMAIL=admin@cyberxredteam.org    # Set manually, sync: false
ADMIN_PASSWORD=<secure-password>        # Set manually, sync: false
```

**Auto-configured from render.yaml:**
```bash
CSRF_SECRET_KEY=<auto-generated>
ENCRYPTION_KEY=<auto-generated>
DEBUG=false
FRONTEND_URL=https://events.cyberxredteam.org
ALLOWED_HOSTS=events.cyberxredteam.org
SENDGRID_FROM_NAME=CyberX Red Team
SENDGRID_SANDBOX_MODE=false
SESSION_EXPIRY_HOURS=24
BULK_EMAIL_INTERVAL_MINUTES=45
# ... reminder configuration ...
# ... VPN configuration (if needed) ...
# ... PowerDNS configuration (if needed) ...
```

### Worker Service Environment Variables

Configure in Render Dashboard → Worker Service → Environment:

**Shared from Web Service (via fromService in render.yaml):**
- `DATABASE_URL`
- `SECRET_KEY`
- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`
- `SENDGRID_FROM_NAME`
- All reminder configuration variables

**Note:** Worker service automatically inherits most variables from web service via `fromService` configuration in render.yaml.

---

## Staging vs Production Differences

### Staging Environment (`render.yaml`)
```bash
ENVIRONMENT=staging
SENDGRID_SANDBOX_MODE=true              # Don't send real emails
FRONTEND_URL=https://staging.events.cyberxredteam.org
ALLOWED_HOSTS=staging.events.cyberxredteam.org
```

### Production Environment
```bash
ENVIRONMENT=production
SENDGRID_SANDBOX_MODE=false             # Send real emails
FRONTEND_URL=https://events.cyberxredteam.org
ALLOWED_HOSTS=events.cyberxredteam.org
```

---

## Security Best Practices

### Secrets Management

**Set to `sync: false` in render.yaml:**
- `DATABASE_URL` - Contains password
- `SENDGRID_API_KEY` - API credential
- `SENDGRID_FROM_EMAIL` - May change
- `ADMIN_EMAIL` - Sensitive
- `ADMIN_PASSWORD` - Sensitive
- `VPN_SERVER_PUBLIC_KEY` - Sensitive
- `VPN_SERVER_ENDPOINT` - May change
- `POWERDNS_API_URL` - May change
- `POWERDNS_USERNAME` - Sensitive
- `POWERDNS_PASSWORD` - Sensitive

**Auto-generated by Render:**
- `SECRET_KEY` - Use `generateValue: true`
- `CSRF_SECRET_KEY` - Use `generateValue: true`
- `ENCRYPTION_KEY` - Use `generateValue: true`

### Password Guidelines

**DATABASE_URL:**
- URL-encode special characters
- Example: `@` → `%40`, `#` → `%23`, `$` → `%24`
- Use Supabase pooler endpoint for IPv4 compatibility

**ADMIN_PASSWORD:**
- Minimum 12 characters
- Include uppercase, lowercase, numbers, special characters
- Change default password after first login

---

## Troubleshooting

### Common Issues

**"Pydantic validation error" on startup:**
- Check that all required variables are set
- Optional variables (VPN, PowerDNS) can be empty strings

**"Database connection failed":**
- Verify DATABASE_URL is correct
- Check special characters are URL-encoded
- Use pooler endpoint, not direct connection (IPv6 incompatible)

**"Admin user not created":**
- Check ADMIN_EMAIL and ADMIN_PASSWORD are both set
- Admin only created if NO admin users exist
- Check startup logs for bootstrap messages

**"Emails not sending":**
- Verify SENDGRID_API_KEY is valid
- Check SENDGRID_FROM_EMAIL is verified in SendGrid
- Check SENDGRID_SANDBOX_MODE setting (true = no emails sent)

**"Scheduler running twice / duplicate emails":**
- Ensure ENABLE_SCHEDULER_IN_WEB=false in production
- Use dedicated worker service for background jobs

---

## Quick Reference

### Minimal Configuration (Development)
```bash
DATABASE_URL=postgresql+asyncpg://...
SECRET_KEY=<random-string>
SENDGRID_API_KEY=<your-key>
SENDGRID_FROM_EMAIL=<your-email>
ENVIRONMENT=development
DEBUG=true
ENABLE_SCHEDULER_IN_WEB=true
```

### Minimal Configuration (Production)
```bash
DATABASE_URL=postgresql+asyncpg://...
SECRET_KEY=<auto-generated>
SENDGRID_API_KEY=<your-key>
SENDGRID_FROM_EMAIL=<your-email>
ENVIRONMENT=production
DEBUG=false
ADMIN_EMAIL=admin@cyberxredteam.org
ADMIN_PASSWORD=<secure-password>
```

---

## Related Documentation

- [Render Deployment Guide](RENDER_DEPLOYMENT.md)
- [Supabase Setup Guide](SUPABASE_SETUP.md)
- [GitHub Actions Setup](CI_CD_SETUP.md)
- [Testing Email Guide](TESTING_EMAIL_GUIDE.md)
