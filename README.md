# CyberX Event Management Platform

A comprehensive web application to manage CyberX events, replacing SharePoint + Power Automate workflows with a modern Python FastAPI backend and PostgreSQL database.

## Features

- **Admin Portal**: Manage participants, VPN assignments, credentials, and communications
- **Participant Portal**: Self-service VPN key requests and account management
- **Backend API**: FastAPI + PostgreSQL replacing all Power Automate functionality
- **Email Integration**: SendGrid for templated emails with event tracking
- **VPN Management**: On-demand WireGuard config generation from database
- **Webhook Support**: SendGrid, Discord, Keycloak integrations
- **Background Jobs**: Automated bulk email tasks (every 45 minutes)

## Tech Stack

- **Backend**: Python 3.13+, FastAPI, SQLAlchemy (async), Alembic
- **Database**: PostgreSQL 15+
- **Authentication**: Session-based custom auth with bcrypt
- **Email**: SendGrid API with dynamic templates
- **Frontend**: Jinja2 templates (converted from SB Admin Pro)
- **Deployment**: Docker, Docker Compose

## Project Structure

```
cyberx-event-mgmt/
├── backend/
│   ├── app/
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── api/routes/      # API endpoints
│   │   ├── services/        # Business logic
│   │   ├── tasks/           # Background jobs
│   │   └── utils/           # Utilities
│   ├── migrations/          # Alembic migrations
│   ├── scripts/             # Helper scripts
│   └── tests/               # Test suite
├── frontend/
│   ├── static/              # CSS, JS, assets
│   └── templates/           # Jinja2 templates
└── docker-compose.yml       # PostgreSQL + Redis
```

## Quick Start

### Prerequisites

- Python 3.13 or newer
- Docker Desktop (for PostgreSQL)
- SendGrid API key
- PowerDNS credentials (optional)

### 1. Clone and Setup

```bash
cd ~/projects/cyberx/website-nextgen/cyberx-event-mgmt
```

### 2. Install Backend Dependencies

```bash
cd backend
pyenv local 3.13.2  # or your Python 3.13+ version
pip install -r requirements.txt
```

### 3. Start PostgreSQL

```bash
# From project root
docker compose up -d postgres

# Verify it's running
docker compose ps
```

### 4. Configure Environment

```bash
cd backend
cp .env.example .env
# Edit .env with your configuration
```

**Required environment variables:**
- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: Random secret key for sessions
- `SENDGRID_API_KEY`: Your SendGrid API key
- `VPN_SERVER_PUBLIC_KEY`: VPN server public key

### 5. Run Database Migrations

```bash
cd backend
alembic upgrade head
```

### 6. Import CSV Data

```bash
cd backend
python scripts/import_csv.py
```

###7. Start the Application

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Access the application at [http://localhost:8000](http://localhost:8000)

## Database Schema

### Core Tables

- **users**: Participants and admins (269 participants from CSV)
- **vpn_credentials**: VPN configs (2001 from CSV)
- **sessions**: User authentication sessions
- **audit_logs**: System activity tracking
- **email_events**: SendGrid webhook events
- **vpn_requests**: VPN allocation requests

## API Endpoints

### Authentication
- `POST /api/auth/login` - Login
- `POST /api/auth/logout` - Logout
- `GET /api/auth/me` - Current user info

### Admin
- `GET /api/admin/dashboard` - Dashboard stats
- `GET /api/admin/participants` - List participants
- `POST /api/admin/participants` - Add participant
- `PUT /api/admin/participants/{id}` - Update participant
- `POST /api/admin/participants/{id}/reset-password` - Reset password
- `POST /api/admin/vpn/assign` - Assign VPN key

### Participant
- `GET /api/participant/dashboard` - User dashboard
- `POST /api/participant/vpn-request` - Request VPN
- `GET /api/participant/vpn-download` - Download WireGuard config

### Webhooks
- `POST /api/webhooks/sendgrid` - SendGrid events
- `POST /api/webhooks/discord-username` - Discord updates
- `POST /api/webhooks/keycloak` - Keycloak SSO events

## Development

### Running Tests

```bash
cd backend
pytest
```

### Creating New Migrations

```bash
cd backend
alembic revision --autogenerate -m "Description of changes"
alembic upgrade head
```

### Code Style

```bash
# Format code
black app/

# Type checking
mypy app/
```

## Deployment

### Production Setup

1. Update `.env` with production values
2. Set `DEBUG=False`
3. Use strong `SECRET_KEY`
4. Configure HTTPS reverse proxy (nginx)
5. Set up database backups
6. Configure monitoring and logging

### Docker Production

```bash
docker compose -f docker-compose.prod.yml up -d
```

## Power Automate Workflows Replaced

| Workflow | Replacement |
|----------|-------------|
| Discord VPN Request | `POST /api/webhooks/discord-vpn-request` |
| Bulk Password Email | APScheduler job (every 45 min) |
| SendGrid Event Webhook | `POST /api/webhooks/sendgrid` |
| DNS/PowerDNS Integration | `POST /api/webhooks/keycloak` |
| Discord Username Update | `POST /api/webhooks/discord-username` |

## Data Migration

The application includes a CSV import script to migrate data from SharePoint:

- **Participants**: `/Users/wes/projects/cyberx/website-nextgen/data/CyberX Master Invite.csv`
- **VPN Configs**: `/Users/wes/projects/cyberx/website-nextgen/data/VPN Configs V2.csv`

Run the import script after setting up the database:

```bash
cd backend
python scripts/import_csv.py
```

## Security

- **Password Storage**: Bcrypt hashing for web portal passwords
- **Session Management**: 32-byte secure random tokens, 24-hour expiration
- **HTTPS Only**: Enforce HTTPS in production
- **Input Validation**: Pydantic schemas for all API inputs
- **Rate Limiting**: Auth endpoints limited to 10 requests/minute
- **VPN Key Protection**: Admins can view keys, participants only get generated configs

## Support

For issues or questions, contact the CyberX Red Team at [hello@cyberxredteam.org](mailto:hello@cyberxredteam.org).

## License

Proprietary - CyberX Red Team © 2025
