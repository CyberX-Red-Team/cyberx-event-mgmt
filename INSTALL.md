# CyberX Event Management - Installation Guide

Complete installation instructions for setting up the CyberX Event Management System from scratch.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation Methods](#installation-methods)
  - [Quick Start (Docker)](#quick-start-docker)
  - [Manual Installation](#manual-installation)
  - [Production Deployment](#production-deployment)
- [Database Setup](#database-setup)
- [Configuration](#configuration)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

- **Python 3.11+** - Backend runtime
- **PostgreSQL 15+** - Primary database
- **Docker & Docker Compose** - Container orchestration (recommended)
- **Git** - Version control
- **SendGrid Account** - Email delivery (for email features)

### System Requirements

**Minimum:**
- 2 CPU cores
- 4GB RAM
- 10GB disk space

**Recommended (Production):**
- 4+ CPU cores
- 8GB+ RAM
- 50GB+ disk space (for logs and data growth)

### External Services

1. **SendGrid** (required for email features)
   - Sign up at https://sendgrid.com
   - Get API key from Settings → API Keys
   - Set up domain authentication

2. **PowerDNS** (optional, for DNS management)
   - Configure API access
   - Obtain credentials

---

## Installation Methods

### Quick Start (Docker)

Best for development and testing.

#### 1. Clone the Repository

```bash
git clone git@github.com:your-org/cyberx-event-mgmt.git
cd cyberx-event-mgmt
```

#### 2. Start Services

```bash
# Start PostgreSQL and Redis
docker-compose up -d

# Verify services are running
docker-compose ps
```

#### 3. Set Up Backend Environment

```bash
cd backend

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit with your configuration
nano .env  # or use your preferred editor
```

**Required settings to update:**
```env
DATABASE_URL=postgresql+asyncpg://cyberx:changeme@localhost:5432/cyberx_events
SECRET_KEY=<generate-random-key>
SENDGRID_API_KEY=<your-sendgrid-api-key>
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
```

**Generate a secure secret key:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### 5. Initialize Database

```bash
# Run migrations to create tables
alembic upgrade head

# Create initial admin user
python scripts/create_admin.py
```

When prompted, enter admin credentials (or press Enter for defaults).

#### 6. Start the Application

```bash
# Start the development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 7. Verify Installation

Open your browser:
- **Application**: http://localhost:8000
- **API Docs**: http://localhost:8000/api/docs (if DEBUG=True)
- **Health Check**: http://localhost:8000/health

**Default admin credentials:**
- Email: `admin@cyberxredteam.org`
- Password: (whatever you set during setup)

---

### Manual Installation

For production or when Docker is not available.

#### 1. Install PostgreSQL

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

**RHEL/CentOS:**
```bash
sudo dnf install postgresql15-server postgresql15-contrib
sudo postgresql-15-setup initdb
sudo systemctl start postgresql-15
sudo systemctl enable postgresql-15
```

#### 2. Create Database and User

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE cyberx_events;
CREATE USER cyberx WITH PASSWORD 'changeme';
GRANT ALL PRIVILEGES ON DATABASE cyberx_events TO cyberx;
\q
```

#### 3. Install Redis (Optional but Recommended)

**Ubuntu/Debian:**
```bash
sudo apt install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

**macOS (Homebrew):**
```bash
brew install redis
brew services start redis
```

#### 4. Clone and Set Up Application

```bash
git clone git@github.com:your-org/cyberx-event-mgmt.git
cd cyberx-event-mgmt/backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Update DATABASE_URL and other settings
```

#### 5. Initialize Database

```bash
# Run migrations
alembic upgrade head

# Create admin user
python scripts/create_admin.py

# Optional: Import seed data
python scripts/import_csv.py /path/to/participants.csv /path/to/vpn-configs.csv
```

#### 6. Configure System Service (Production)

Create systemd service file `/etc/systemd/system/cyberx-event-mgmt.service`:

```ini
[Unit]
Description=CyberX Event Management System
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

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cyberx-event-mgmt
sudo systemctl start cyberx-event-mgmt
sudo systemctl status cyberx-event-mgmt
```

---

### Production Deployment

#### Architecture Overview

```
Internet → Nginx (SSL/TLS) → Gunicorn/Uvicorn → FastAPI Application → PostgreSQL
                                                                      → Redis
```

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

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name events.cyberxredteam.org;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/events.cyberxredteam.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/events.cyberxredteam.org/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Client body size
    client_max_body_size 20M;

    # Proxy settings
    location / {
        proxy_pass http://cyberx_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Static files (if needed)
    location /static/ {
        alias /opt/cyberx-event-mgmt/backend/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

Enable site:
```bash
sudo ln -s /etc/nginx/sites-available/cyberx-event-mgmt /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 3. Install SSL Certificate

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d events.cyberxredteam.org
```

#### 4. Configure PostgreSQL for Production

Edit `/etc/postgresql/15/main/postgresql.conf`:

```conf
# Performance tuning (adjust based on your hardware)
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
max_connections = 100

# Enable connection pooling
listen_addresses = 'localhost'
```

Restart PostgreSQL:
```bash
sudo systemctl restart postgresql
```

#### 5. Set Up Monitoring (Optional)

Install monitoring tools:
```bash
# Prometheus node exporter
wget https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz
tar xvfz node_exporter-1.7.0.linux-amd64.tar.gz
sudo cp node_exporter-1.7.0.linux-amd64/node_exporter /usr/local/bin/
sudo useradd -rs /bin/false node_exporter
```

Create systemd service for monitoring.

#### 6. Configure Backups

Create backup script `/opt/backups/backup-cyberx.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/cyberx"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Backup database
docker exec cyberx_postgres pg_dump -U cyberx cyberx_events | gzip > "$BACKUP_DIR/db_backup_$DATE.sql.gz"

# Backup .env file
cp /opt/cyberx-event-mgmt/backend/.env "$BACKUP_DIR/env_backup_$DATE"

# Delete backups older than 30 days
find "$BACKUP_DIR" -name "*.gz" -mtime +30 -delete

echo "Backup completed: $DATE"
```

Make executable and schedule:
```bash
chmod +x /opt/backups/backup-cyberx.sh
sudo crontab -e
# Add: 0 2 * * * /opt/backups/backup-cyberx.sh
```

---

## Database Setup

### Clean Database Initialization

For a fresh database with no existing data:

```bash
cd backend

# Run all migrations
alembic upgrade head

# Create admin user
python scripts/create_admin.py admin@example.com secure_password

# Optional: Load seed data
python scripts/seed_database.py
```

### Database Migration

When updating from a previous version:

```bash
cd backend

# Check current migration version
alembic current

# See pending migrations
alembic history

# Apply pending migrations
alembic upgrade head

# Rollback if needed
alembic downgrade -1
```

### Import Existing Data

If you have CSV data from a previous system:

```bash
cd backend

# Import participants and VPN configurations
python scripts/import_csv.py \
    /path/to/participants.csv \
    /path/to/vpn-configs.csv
```

Expected CSV formats:

**Participants CSV:**
- Required columns: `email`, `first_name`, `last_name`, `country`
- Optional columns: `pandas_username`, `sponsor_email`, `discord_username`

**VPN Configs CSV:**
- Required columns: `interface_ip`, `ipv4_address`, `private_key`
- Optional columns: `ipv6_local`, `ipv6_global`, `preshared_key`

---

## Configuration

### Environment Variables

All configuration is managed through the `.env` file in the `backend/` directory.

#### Core Settings

```env
# Application
DEBUG=False                    # Set to False in production
SECRET_KEY=<64-char-random>    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(64))"
ALLOWED_HOSTS=yourdomain.com   # Comma-separated list

# Database
DATABASE_URL=postgresql+asyncpg://username:password@host:port/database

# Session
SESSION_EXPIRY_HOURS=24
```

#### Email Settings

```env
SENDGRID_API_KEY=SG.xxxx
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
SENDGRID_FROM_NAME=CyberX Red Team
SENDGRID_SANDBOX_MODE=false

# Email job frequency
BULK_EMAIL_INTERVAL_MINUTES=45
```

#### Security Settings

```env
# Optional separate CSRF key (defaults to SECRET_KEY)
CSRF_SECRET_KEY=<64-char-random>

# Optional field encryption key (defaults to SECRET_KEY)
ENCRYPTION_KEY=<44-char-base64>  # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

#### VPN Configuration

```env
VPN_SERVER_PUBLIC_KEY=<wireguard-public-key>
VPN_SERVER_ENDPOINT=vpn.yourdomain.com:51820
VPN_DNS_SERVERS=10.20.200.1
VPN_ALLOWED_IPS=10.0.0.0/8,fd00:a::/32
```

#### External Services

```env
# PowerDNS (optional)
POWERDNS_API_URL=https://dns.yourdomain.com/api/v1/pdnsadmin/
POWERDNS_USERNAME=admin
POWERDNS_PASSWORD=<password>

# Frontend URL (for email links)
FRONTEND_URL=https://events.yourdomain.com
```

#### Reminder Configuration

```env
REMINDER_1_DAYS_AFTER_INVITE=7
REMINDER_1_MIN_DAYS_BEFORE_EVENT=14
REMINDER_2_DAYS_AFTER_INVITE=14
REMINDER_2_MIN_DAYS_BEFORE_EVENT=7
REMINDER_3_DAYS_BEFORE_EVENT=3
REMINDER_CHECK_INTERVAL_HOURS=24
```

### Generating Secure Keys

```bash
# SECRET_KEY (64 characters)
python -c "import secrets; print(secrets.token_urlsafe(64))"

# ENCRYPTION_KEY (Fernet key)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# WireGuard keys
wg genkey | tee privatekey | wg pubkey > publickey
```

---

## Verification

### 1. Check Services Status

```bash
# PostgreSQL
docker-compose ps postgres
# or
sudo systemctl status postgresql

# Redis
docker-compose ps redis
# or
sudo systemctl status redis

# Application
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2026-02-03T12:00:00Z"
}
```

### 2. Test Database Connection

```bash
cd backend

# Verify database
python -c "
from app.database import engine
import asyncio

async def check():
    async with engine.connect() as conn:
        print('✅ Database connected successfully')

asyncio.run(check())
"
```

### 3. Test Authentication

```bash
cd backend

# Test login endpoint
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin@example.com", "password": "your_password"}'
```

Expected response:
```json
{
  "user": {
    "id": 1,
    "email": "admin@example.com",
    "role": "ADMIN"
  },
  "session_token": "..."
}
```

### 4. Run Test Scripts

```bash
cd backend

# Test authentication flow
python scripts/test_auth.py

# Test email functionality (if SendGrid configured)
python scripts/test_email.py
```

### 5. Check Database Contents

```bash
# Connect to database
docker-compose exec postgres psql -U cyberx -d cyberx_events

# Run verification queries
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM vpn_credentials;
SELECT * FROM alembic_version;
\dt  -- List all tables
\q   -- Exit
```

---

## Troubleshooting

### Database Connection Issues

**Problem:** `connection refused` error

**Solutions:**
```bash
# Check PostgreSQL is running
docker-compose ps postgres
sudo systemctl status postgresql

# Check port is accessible
netstat -tulpn | grep 5432

# Verify DATABASE_URL in .env
cat backend/.env | grep DATABASE_URL

# Test direct connection
psql postgresql://cyberx:changeme@localhost:5432/cyberx_events
```

### Migration Errors

**Problem:** `alembic upgrade` fails

**Solutions:**
```bash
# Check current state
alembic current
alembic history

# Reset to clean state (CAUTION: destroys data)
docker-compose down -v
docker-compose up -d
alembic upgrade head

# Or manual table creation
psql -U cyberx -d cyberx_events -f schema.sql
```

### Import Failures

**Problem:** CSV import fails

**Solutions:**
```bash
# Check file exists and is readable
ls -lh /path/to/file.csv

# Verify CSV format
head -n 5 /path/to/file.csv

# Check for encoding issues
file /path/to/file.csv
iconv -f ISO-8859-1 -t UTF-8 input.csv > output.csv

# Run import with verbose logging
python scripts/import_csv.py --verbose
```

### Application Won't Start

**Problem:** `uvicorn` fails to start

**Solutions:**
```bash
# Check Python version
python --version  # Should be 3.11+

# Reinstall dependencies
pip install --force-reinstall -r requirements.txt

# Check for syntax errors
python -m py_compile app/main.py

# Run with verbose output
uvicorn app.main:app --log-level debug

# Check port availability
lsof -i :8000
```

### SendGrid Email Issues

**Problem:** Emails not sending

**Solutions:**
```bash
# Verify API key
curl -X POST https://api.sendgrid.com/v3/mail/send \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"personalizations":[{"to":[{"email":"test@example.com"}]}],"from":{"email":"from@yourdomain.com"},"subject":"Test","content":[{"type":"text/plain","value":"Test"}]}'

# Check email queue
curl http://localhost:8000/api/admin/email/queue \
  -H "Cookie: session_token=YOUR_TOKEN"

# Enable sandbox mode for testing
# Set in .env: SENDGRID_SANDBOX_MODE=true
```

### Permission Errors

**Problem:** File permission denied

**Solutions:**
```bash
# Fix ownership
sudo chown -R $USER:$USER /opt/cyberx-event-mgmt

# Fix permissions
chmod +x scripts/*.py
chmod 600 backend/.env

# Run as correct user
sudo -u cyberx uvicorn app.main:app
```

### Docker Issues

**Problem:** Container won't start

**Solutions:**
```bash
# Check logs
docker-compose logs -f postgres

# Remove volumes and restart
docker-compose down -v
docker-compose up -d

# Check Docker daemon
sudo systemctl status docker

# Rebuild images
docker-compose build --no-cache
```

### Performance Issues

**Problem:** Application is slow

**Solutions:**
```bash
# Check database connections
SELECT count(*) FROM pg_stat_activity WHERE datname = 'cyberx_events';

# Optimize database
VACUUM ANALYZE;

# Check indexes
SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public';

# Increase worker processes
# In systemd service: --workers 4

# Monitor resource usage
htop
docker stats
```

---

## Next Steps

After successful installation:

1. **Configure Email Templates**
   - Log in as admin
   - Go to Email → Templates
   - Set up SendGrid dynamic templates

2. **Create Your First Event**
   - Navigate to Events → Create New
   - Set dates and registration period
   - Configure participant limits

3. **Import Participants**
   - Use CSV import or manual entry
   - Assign sponsors
   - Generate invitation emails

4. **Set Up VPN Credentials**
   - Import VPN configurations
   - Assign to participants
   - Test configuration downloads

5. **Review Documentation**
   - [README.md](README.md) - Feature overview
   - [EVENT_MANAGEMENT.md](EVENT_MANAGEMENT.md) - Event lifecycle
   - [TESTING_EMAIL_GUIDE.md](TESTING_EMAIL_GUIDE.md) - Email testing

---

## Support

For issues or questions:
- Check [Troubleshooting](#troubleshooting) section
- Review logs: `docker-compose logs -f` or `/var/log/cyberx-event-mgmt/`
- Contact: support@cyberxredteam.org

---

**Installation Guide Version**: 1.0.0
**Last Updated**: 2026-02-03
**Application Version**: 0.1.0-beta
