# Features

## Event Management

- Create and manage annual cybersecurity exercise events
- Configurable event dates, location, max participants, and registration windows
- Event lifecycle controls: active/inactive, registration open/closed, test mode, VPN availability
- Auto-generated event slugs for clean URLs
- Terms of participation with versioning
- Confirmation expiry enforcement (configurable days)

## Participant Management

- Invite-based participant model with roles: admin, sponsor, invitee
- Bulk participant import with email normalization (Gmail alias deduplication)
- Participation lifecycle tracking: invited, confirmed, declined, no response
- Per-event participation history with confirmation/decline timestamps and decline reasons
- Sponsor-to-invitee relationships (sponsors manage their own invitees)
- Chronic non-participant detection (invited 3+ years, never participated) with removal recommendations
- Email status tracking per user: good, bounced, spam reported, unsubscribed
- Filterable/searchable participant lists with pagination
- Bulk actions: create, update, delete, invite

## Authentication & Security

- Session-based authentication with configurable TTL (default 24 hours)
- CSRF protection with token-based middleware
- Rate-limited login (5 attempts per 15 minutes per IP)
- Password change and reset (email-based with time-limited tokens)
- bcrypt password hashing
- Fernet encryption for sensitive queued credentials
- Webhook signature verification (HMAC-SHA256) for SendGrid and Keycloak

## VPN Credential Management

- WireGuard credential storage with full config fields (IPv4/IPv6, keys, endpoint, DNS, MTU)
- Assignment types: user-requestable, instance-auto-assign, reserved
- Key types: cyber, kinetic
- Self-service VPN requests from participant portal (rate-limited: 3 per 5 minutes)
- Admin bulk import, assignment, and deletion
- WireGuard config file generation with optional encryption
- VPN config delivery via email attachment
- Request batch tracking
- Usage statistics dashboard

## Instance Provisioning

- Multi-cloud support: OpenStack and DigitalOcean
- Admin instance creation with provider-specific options (flavor, image, network, region)
- Bulk instance creation with name prefix
- Instance templates: reusable configurations bundling provider settings, cloud-init, and license products
- Participant self-service provisioning from published templates
- Instance status sync from cloud providers (building, active, error, shutoff, deleted)
- Cloud-init template system with variable substitution for VPN injection, license tokens, and SSH keys
- Per-provider resource listing (flavors, images, networks, sizes, regions)
- SSH key pair management per event

## License Management

- License product definitions with encrypted blob storage
- Concurrency-controlled installation queue (max concurrent slots per product)
- VM-facing API with bearer token auth:
  - Single-use token for license blob retrieval (replay-proof)
  - Slot acquisition with wait/grant response model
  - Slot release with result tracking (success, error, expired)
- Configurable slot TTL and token TTL
- Admin dashboard for queue status and usage metrics

## Email System

- SendGrid integration with template management
- Email template CRUD with variable placeholders ({{first_name}}, {{event_name}}, etc.)
- Template import from SendGrid
- Single and bulk email sending with queue persistence
- Email workflow engine: trigger-based automation (user confirmed, VPN assigned, password reset, action assigned, etc.)
- Per-workflow configuration: template, from address, priority, delay, enable/disable
- Queued email processing on configurable interval (default 45 minutes)
- Retry logic with exponential backoff
- SendGrid webhook processing: delivery, open, click, bounce, spam report, unsubscribe tracking
- Sandbox mode for staging (no real emails sent)
- Email analytics: per-template stats, daily stats, full history

## Automated Reminders

- Three-stage invitation reminder system:
  - First reminder: N days after invite (if M+ days until event)
  - Second reminder: N days after invite (if M+ days until event)
  - Final reminder: N days before event
- Per-reminder enable/disable toggle
- Configurable check interval
- Admin endpoint to manually trigger reminder processing

## Participant Actions

- Flexible task assignment system for participants
- Action types: in-person attendance, survey completion, orientation RSVP, document review, custom
- Bulk assignment to specific users or all confirmed participants
- Deadline tracking with automatic expiry
- Participant response interface (confirm/decline with optional notes)
- Batch-based management with statistics rollup
- Email notification integration via action-type-specific workflows

## CPE Certificates

- Continuing Professional Education certificate issuance (configurable hours, default 32)
- Eligibility checking against tracked activity:
  - Nextcloud login during event dates (via Keycloak audit logs)
  - PowerDNS-Admin login during event dates (via Keycloak audit logs)
  - VPN credential assignment
- Single and bulk issuance with eligibility override option
- Randomized hex certificate serial numbers (CX-YYYY-XXXX format)
- PDF generation pipeline: DOCX template (from R2) filled with python-docx, converted via Gotenberg, uploaded to R2
- Eligibility snapshot recorded at issuance for audit trail
- Certificate revocation with reason tracking
- PDF regeneration for existing certificates
- Participant self-service download via signed R2 URLs

## Keycloak Integration

- Queue-based password sync (create user, update password, delete user)
- Encrypted credential storage in sync queue with retry logic (max 5 retries)
- Scoped to invitees and sponsors (admins not synced)
- Inbound webhook listener for Keycloak events (user lifecycle, group membership)
- Auto-assignment of PowerDNS-Admin accounts on first Keycloak login

## Discord Integration

- Per-event Discord invite link generation for confirmed participants
- Unique invite codes per user with one-time-use tracking
- Lazy validation: checks Discord to detect if invite was consumed
- Portal display with join status

## PowerDNS Integration

- Auto-account creation in PowerDNS-Admin on first Keycloak login
- Domain ownership used for CPE eligibility verification
- API-based user-to-account assignment

## Audit Logging

- Comprehensive action logging: logins, password changes, email sends, user CRUD, VPN assignments, instance operations, certificate issuance/revocation, configuration changes
- Structured details (JSON) with IP address and user agent tracking
- Filterable audit log viewer: by user, action type, date range, resource type, status
- Activity statistics by day and action type

## Admin Dashboard

- KPI overview with event statistics
- 14 admin management pages: participants, events, VPN, instances, instance templates, cloud-init, email, workflows, audit, users, license products, participant actions, settings
- System settings UI for live configuration of all integrations without restart

## Participant Portal

- Self-service dashboard with event information
- VPN credential request and config download
- Instance provisioning from templates
- CPE certificate listing and PDF download
- Discord invite display
- Participant action response interface
- SSH key management
- Password change
- Profile and theme preferences (light/dark)

## Sponsor Portal

- Sponsored invitee list with filtering
- Visibility into invitee confirmation status

## Background Jobs

- APScheduler-based task system:
  - Bulk email processing (configurable interval)
  - Session and token cleanup (daily)
  - Invitation reminder processing (daily)
  - Keycloak credential sync (every 5 minutes)
  - Instance status sync from cloud providers
  - License slot expiry reaper (hourly)
  - Scheduler health heartbeat (every 60 seconds)

## Deployment

- Docker Compose production stack: PostgreSQL, Redis, FastAPI, Nginx, Certbot, Gotenberg, Prometheus, Grafana, automated backups
- Render.com blueprint: Python web service + Gotenberg Docker sidecar with Supabase PostgreSQL
- Alembic database migrations
- Environment-based configuration with sensible defaults
