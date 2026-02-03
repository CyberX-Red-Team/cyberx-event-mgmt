# CyberX Event Management - Setup Guide

## ✅ What's Been Built

### Phase 1: Foundation (COMPLETED)

- ✅ Complete project structure
- ✅ Python 3.13 environment with all dependencies
- ✅ PostgreSQL + Redis Docker configuration
- ✅ 6 SQLAlchemy models (User, VPNCredential, Session, AuditLog, EmailEvent, VPNRequest)
- ✅ Alembic migrations configured for async operations
- ✅ CSV import script for SharePoint data
- ✅ Database initialization script
- ✅ Security utilities (password hashing, tokens)
- ✅ Comprehensive documentation

### Phase 2: Authentication & Sessions (COMPLETED)

- ✅ AuthService with session management
- ✅ Session-based authentication (24-hour expiry)
- ✅ Password hashing with bcrypt
- ✅ FastAPI dependencies for route protection
- ✅ Login/logout API endpoints
- ✅ Current user (/me) endpoint
- ✅ Admin and participant role checking
- ✅ Secure cookie-based sessions
- ✅ FastAPI main application setup
- ✅ Authentication flow tested end-to-end

### Phase 3: Admin Portal API (COMPLETED)

- ✅ Participant CRUD endpoints (list, get, create, update, delete)
- ✅ Participant filtering, pagination, and search
- ✅ Participant statistics endpoint
- ✅ Bulk actions (activate/deactivate)
- ✅ Password reset endpoint
- ✅ VPN credentials listing and management
- ✅ VPN assignment and revocation
- ✅ VPN bulk assignment
- ✅ WireGuard config generation and download
- ✅ Self-service VPN config download for participants
- ✅ Combined dashboard statistics endpoint
- ✅ All endpoints tested end-to-end

### Phase 4: Email Service (COMPLETED)

- ✅ SendGrid email service integration
- ✅ 6 email templates (invite, password, reminder, vpn_config, survey, orientation)
- ✅ Single and bulk email sending endpoints
- ✅ VPN config email with attachment
- ✅ Email statistics endpoint
- ✅ Participant email status tracking
- ✅ SendGrid webhook handler for delivery events
- ✅ Discord and Keycloak webhook handlers (stub)
- ✅ Automatic user email status updates (bounce handling)
- ✅ All endpoints tested end-to-end

## 🚀 Quick Start

### 1. Start PostgreSQL

```bash
cd ~/projects/cyberx/website-nextgen/cyberx-event-mgmt

# Start PostgreSQL (Docker must be running)
docker compose up -d postgres

# Verify it's running
docker compose ps
```

### 2. Create Database Tables

```bash
cd backend

# Run Alembic migrations to create tables
alembic upgrade head
```

This will create all 6 tables:
- `users`
- `vpn_credentials`
- `sessions`
- `audit_logs`
- `email_events`
- `vpn_requests`

### 3. Create Admin User (Optional)

```bash
# Run the initialization script
python scripts/init_db.py
```

This will prompt you for:
- Admin email (default: admin@cyberxredteam.org)
- Admin password (default: changeme)

### 4. Import CSV Data

```bash
# Import participants and VPN configurations
python scripts/import_csv.py
```

This will:
- Import 269 participants from `CyberX Master Invite.csv`
- Import 2001 VPN configs from `VPN Configs V2.csv`
- Link VPN credentials to users by username
- Display import statistics

**Expected output:**
```
📥 Importing participants from: /Users/wes/projects/cyberx/website-nextgen/data/CyberX Master Invite.csv
  ✓ Imported 50 participants...
  ✓ Imported 100 participants...
  ...
✅ Imported 269 participants successfully

📥 Importing VPN configurations from: /Users/wes/projects/cyberx/website-nextgen/data/VPN Configs V2.csv
  ✓ Imported 100 VPN configs...
  ✓ Imported 200 VPN configs...
  ...
✅ Imported 2001 VPN configurations successfully

📊 Verifying imported data...
  Users: 269 total, X confirmed, Y with VPN
  VPN Credentials: 2001 total, Z available
    Cyber: A, Kinetic: B
```

### 5. Verify Database

```bash
# Connect to PostgreSQL
docker compose exec postgres psql -U cyberx -d cyberx_events

# Run queries
\dt                                    # List tables
SELECT COUNT(*) FROM users;            # Count users
SELECT COUNT(*) FROM vpn_credentials;  # Count VPN configs
SELECT * FROM users LIMIT 5;           # Sample users
\q                                     # Exit
```

### 6. Create Admin User

```bash
# Create an admin user for testing
python scripts/create_admin.py

# Or specify credentials directly
python scripts/create_admin.py admin@cyberxredteam.org admin123
```

This creates an admin user with:
- Email: admin@cyberxredteam.org
- Password: admin123
- Is Admin: True

### 7. Test Authentication API

```bash
# Terminal 1: Start the API server
uvicorn app.main:app --reload

# Terminal 2: Run authentication tests
python scripts/test_auth.py
```

The server will start on [http://localhost:8000](http://localhost:8000)

**API Documentation** (when DEBUG=True):
- Swagger UI: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)
- ReDoc: [http://localhost:8000/api/redoc](http://localhost:8000/api/redoc)

**Available endpoints:**
- `POST /api/auth/login` - Login with email/username and password
- `POST /api/auth/logout` - Logout and invalidate session
- `GET /api/auth/me` - Get current user info (requires authentication)

## 📁 Data Files Location

The import script expects CSV files at:
```
/Users/wes/projects/cyberx/website-nextgen/data/
├── CyberX Master Invite.csv
└── VPN Configs V2.csv
```

To use different paths, run:
```bash
python scripts/import_csv.py /path/to/participants.csv /path/to/vpn-configs.csv
```

## 🔧 Troubleshooting

### Docker not found
Make sure Docker Desktop is installed and running. Verify with:
```bash
which docker
docker --version
```

### Database connection refused
Check if PostgreSQL is running:
```bash
docker compose ps
docker compose logs postgres
```

### Import fails with "File not found"
Verify the CSV files exist:
```bash
ls -lh ~/projects/cyberx/website-nextgen/data/
```

### Python module errors
Reinstall dependencies:
```bash
cd backend
pip install -r requirements.txt
```

## 📊 Database Schema

### users table
- 269 participants (from CSV)
- Fields: email, first_name, last_name, country, confirmed, email_status
- Credentials: pandas_username, pandas_password, password_phonetic, password_hash
- Discord: discord_username, snowflake_id, discord_invite_code
- Timestamps for all email communications

### vpn_credentials table
- 2001 VPN configurations (from CSV)
- Fields: interface_ip, ipv4_address, ipv6_local, ipv6_global
- WireGuard keys: private_key, preshared_key, endpoint
- Assignment: assigned_to_username, assigned_to_user_id, is_available
- Types: cyber, kinetic

### Other tables
- **sessions**: User authentication sessions (24-hour expiry)
- **audit_logs**: System activity tracking with JSONB details
- **email_events**: SendGrid webhook events
- **vpn_requests**: VPN allocation request tracking

## 🎯 Next Steps

Completed phases:

1. **~~Build Authentication Service~~** ✅ COMPLETED
   - ✅ Session creation and validation
   - ✅ Password hashing and verification
   - ✅ Login/logout endpoints

2. **~~Create Admin & Participant API Routes~~** ✅ COMPLETED
   - ✅ Auth endpoints (/api/auth/login, /logout, /me)
   - ✅ Admin endpoints (/api/admin/participants, /vpn, /dashboard)
   - ✅ VPN endpoints (/api/vpn/assign, /revoke, /config)

3. **~~Implement VPN Service~~** ✅ COMPLETED
   - ✅ VPN allocation logic
   - ✅ WireGuard config generation
   - ✅ On-demand file creation

4. **~~Build Email Service~~** ✅ COMPLETED
   - ✅ SendGrid integration
   - ✅ Template rendering (6 templates)
   - ✅ Webhook processing
   - ✅ Email endpoints (/api/email/send, /bulk, /stats)

5. **~~Create Frontend Templates~~** ✅ COMPLETED
   - ✅ Jinja2 templating integration with FastAPI
   - ✅ Layout templates (base.html, dashboard.html, auth.html)
   - ✅ Login page with session handling
   - ✅ Admin dashboard with statistics
   - ✅ Participants list with filtering and pagination
   - ✅ Participant portal for self-service

6. **~~Add Background Jobs~~** ✅ COMPLETED
   - ✅ APScheduler integration with AsyncIOScheduler
   - ✅ Bulk password email job (every 45 minutes)
   - ✅ Session cleanup job (hourly)
   - ✅ Scheduler status endpoint (/api/admin/scheduler/jobs)
   - ✅ Proper startup/shutdown lifecycle management

## 📖 Documentation

- [README.md](README.md) - Complete project documentation
- [/Users/wes/.claude/plans/starry-sparking-hoare.md](/Users/wes/.claude/plans/starry-sparking-hoare.md) - Detailed implementation plan

## 🔐 Security Notes

- Default admin password should be changed immediately
- `.env` file contains sensitive credentials - never commit to git
- Session tokens are 32-byte cryptographically secure random strings
- Passwords are hashed with bcrypt
- VPN private keys are base64 encoded in database

## 💡 Tips

- Use `alembic revision --autogenerate -m "message"` to create new migrations
- Check logs with `docker compose logs -f postgres`
- Reset database: `docker compose down -v && docker compose up -d`
- Run tests: `pytest` (when tests are implemented)

---

**Status**: Phase 6 (Background Jobs) ✅ COMPLETE

All core phases completed. The application is now ready for:
- Integration testing
- Production deployment
- Optional enhancements (additional frontend pages, extended email templates)
