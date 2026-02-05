# CyberX Event Management System

**Status**: 🌐 Open Source - Pre-Production Beta Testing

A comprehensive event management system designed for CyberX Red Team cybersecurity events, handling participant invitations, VPN credential management, email workflows, and event lifecycle coordination.

---

## 🎯 Overview

The CyberX Event Management System provides a complete solution for managing cybersecurity training events, including:

- **Participant Management**: Invite, track, and manage participants with sponsor relationships
- **Event Lifecycle**: Create and manage events from planning through execution to archive
- **VPN Credentials**: Automated WireGuard VPN credential assignment and configuration
- **Email Automation**: Queue-based email system with templates and workflows
- **Role-Based Access**: Three-tier permission system (Admin, Sponsor, Invitee)
- **Audit Trail**: Comprehensive logging of all security-relevant actions

---

## 🏗️ Architecture

### Backend (FastAPI)
- **Framework**: FastAPI 0.104+ with async/await
- **Database**: PostgreSQL with SQLAlchemy 2.0 (async)
- **Authentication**: Session-based with bcrypt password hashing
- **Email**: SendGrid integration with queue-based delivery
- **Background Jobs**: APScheduler for automated tasks
- **API Documentation**: OpenAPI/Swagger (available in debug mode)

### Frontend
- Placeholder structure ready for React/Next.js implementation
- Jinja2 templates for initial prototyping

### Infrastructure
- Docker Compose for local development
- Alembic for database migrations
- Environment-based configuration

---

## 📋 Features

### Core Functionality

#### User Management
- Create and manage users with role-based permissions
- Sponsor-invitee relationship tracking
- Participation history and analytics
- Password management and security

#### Event Management
- Event lifecycle: Planning → Active → Archived
- Registration periods and participant limits
- Test mode for safe email testing
- Event-specific terms and conditions
- Automated invitation workflows

#### VPN Management
- WireGuard credential generation and assignment
- Bulk VPN operations
- CSV import support
- Configuration file generation
- Usage tracking and analytics

#### Email System
- Queue-based delivery with retry logic
- SendGrid dynamic templates
- Workflow automation (invitations, reminders, notifications)
- Batch processing with rate limiting
- SendGrid webhook integration for delivery tracking

#### Administration
- Dashboard with key metrics
- Audit log viewer
- Email queue management
- Participant analytics and filtering
- Bulk operations support

### API Endpoints

**131 Total Endpoints** organized into:

- **Auth** (6): Login, logout, password management, session handling
- **Admin** (40+): Participant management, dashboard, audit logs, settings
- **Events** (10): CRUD operations, participation management
- **VPN** (15+): Assignment, import, configuration generation
- **Email** (20+): Templates, workflows, queue management, analytics
- **Sponsor** (8): Manage sponsored invitees, view statistics
- **Public** (4): Confirmation, terms acceptance, public resources
- **Webhooks** (2+): SendGrid events, Discord integration

---

## 🚀 Setup Instructions

### Prerequisites

- Python 3.11+
- PostgreSQL 13+
- SendGrid account (for email)
- Git

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/CyberX-Red-Team/cyberx-event-mgmt.git
   cd cyberx-event-mgmt
   ```

2. **Set up the backend**
   ```bash
   cd backend
   
   # Create virtual environment
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   ```bash
   # Copy example environment file
   cp .env.example .env
   
   # Edit .env with your credentials
   # Required: DATABASE_URL, SECRET_KEY, SENDGRID_API_KEY
   nano .env
   ```

4. **Initialize the database**
   ```bash
   # Run migrations
   alembic upgrade head
   
   # Create initial admin user
   python scripts/create_admin.py
   ```

5. **Start the development server**
   ```bash
   # From backend directory
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Access the API**
   - API: http://localhost:8000
   - Docs: http://localhost:8000/api/docs (debug mode only)
   - Health: http://localhost:8000/health

### Docker Setup (Alternative)

```bash
# From project root
docker-compose up -d

# Access at http://localhost:8000
```

---

## 🔐 Security

### Current Status

This codebase is in **pre-production beta** and requires security hardening before public deployment.

#### Implemented Security Features ✅

- ✅ Session-based authentication with secure cookies
- ✅ bcrypt password hashing
- ✅ Role-based access control (RBAC)
- ✅ SQL injection prevention (SQLAlchemy ORM)
- ✅ Input validation (Pydantic schemas)
- ✅ Comprehensive audit logging
- ✅ Rate limiting on VPN endpoints and login
- ✅ Secrets excluded from version control
- ✅ **CSRF Protection**: Custom middleware with signed tokens (backend + frontend)
- ✅ **Password Reset**: Email workflow with WorkflowService integration
- ✅ **Field Encryption**: Sensitive fields encrypted at rest (Fernet AES-128)
- ✅ **CORS**: Restricted to specific methods and origins

#### Known Security Gaps ⚠️

- ⚠️ **Rate Limiting**: In-memory implementation (single-instance only, needs Redis for production)
- ⚠️ **Secrets Management**: Environment variables (consider HashiCorp Vault for production)
- ⚠️ **Session Storage**: In-memory (consider Redis for production)

**Production Deployment**: Suitable for beta testing. Multi-instance deployment requires Redis.

---

## 📊 Database Schema

### Core Models

- **User**: Participant/admin accounts with roles and sponsor relationships
- **Event**: Event definitions with lifecycle management
- **EventParticipation**: Historical participation tracking
- **Session**: Authentication sessions
- **VPNCredential**: WireGuard VPN configurations
- **EmailQueue**: Queued emails with retry logic
- **EmailTemplate**: SendGrid template configurations
- **EmailWorkflow**: Automated email workflows
- **AuditLog**: Security event logging

### Migrations

Managed with Alembic. Current migrations: 21 files

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

---

## 🧪 Testing

### Current Status

⚠️ **Testing infrastructure in development**

Currently available:
- 5 manual test scripts in `backend/scripts/`
- No automated test suite (pytest not configured)

**Planned**:
- pytest framework setup
- Unit tests for services
- Integration tests for endpoints
- CI/CD pipeline integration

---

## 🔧 Development

### Project Structure

```
cyberx-event-mgmt/
├── backend/
│   ├── app/
│   │   ├── api/              # Route handlers and API utilities
│   │   │   ├── routes/       # Endpoint definitions
│   │   │   └── utils/        # Request handling, validation, pagination
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── services/         # Business logic layer
│   │   ├── tasks/            # Background jobs
│   │   └── utils/            # Shared utilities
│   ├── migrations/           # Alembic migrations
│   └── scripts/              # Utility scripts
├── frontend/                 # Frontend (placeholder)
├── docker-compose.yml        # Docker configuration
└── README.md                 # This file
```

### Code Style

- **Python**: Follow PEP 8, use type hints
- **API Routes**: Use dependency injection
- **Services**: Keep business logic in service layer
- **Error Handling**: Use standardized exceptions from `app.api.exceptions`

### Recent Refactoring

The codebase has undergone significant consolidation:
- Centralized request metadata extraction
- Standardized HTTP exceptions
- Unified response builders
- Shared service dependencies
- Common pagination utilities

See: Code consolidation completed on 2026-02-03

---

## 📝 API Usage Examples

### Authentication

```bash
# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin@example.com", "password": "yourpassword"}'

# Get current user
curl http://localhost:8000/api/auth/me \
  -H "Cookie: session_token=YOUR_SESSION_TOKEN"
```

### Participant Management (Admin)

```bash
# List participants
curl http://localhost:8000/api/admin/participants?page=1&page_size=50 \
  -H "Cookie: session_token=YOUR_SESSION_TOKEN"

# Create participant
curl -X POST http://localhost:8000/api/admin/participants \
  -H "Content-Type: application/json" \
  -H "Cookie: session_token=YOUR_SESSION_TOKEN" \
  -d '{
    "email": "participant@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "country": "USA"
  }'
```

### VPN Management

```bash
# Get available VPN credentials
curl http://localhost:8000/api/vpn/available \
  -H "Cookie: session_token=YOUR_SESSION_TOKEN"

# Assign VPN to user
curl -X POST http://localhost:8000/api/vpn/assign \
  -H "Content-Type: application/json" \
  -H "Cookie: session_token=YOUR_SESSION_TOKEN" \
  -d '{"user_id": 123, "vpn_credential_id": 456}'
```

---

## 🚦 Current Status & Roadmap

### Beta Readiness: NEEDS ATTENTION

**Ready for Beta** (under controlled conditions):
- ✅ Core features complete (131 endpoints)
- ✅ Database schema stable
- ✅ Email system functional
- ✅ Audit logging comprehensive
- ✅ Version control established

**Remaining for Production**:
- ⚠️ **Automated Tests**: pytest framework needed (70% coverage target)
- ⚠️ **Redis Integration**: For distributed rate limiting and session storage
- ⚠️ **Security Audit**: Professional review recommended

### Roadmap

**Phase 1: Security Hardening** ✅ COMPLETED (Feb 2026)
- [x] Implement CSRF middleware (custom solution, backend + frontend)
- [x] Complete password reset email workflow (WorkflowService integration)
- [x] Remove plaintext password storage (Fernet encryption implemented)
- [x] Tighten CORS configuration (method and origin restrictions)
- [x] Add login rate limiting (5 attempts per 15 minutes)
- [x] Fix VPN race condition (SELECT FOR UPDATE with skip_locked)

**Phase 2: Testing Infrastructure** (2 weeks)
- [ ] Set up pytest framework
- [ ] Create unit test suite (70% coverage target)
- [ ] Add integration tests
- [ ] Set up CI/CD pipeline

**Phase 3: Production Prep** (ongoing)
- [ ] Implement Redis-based rate limiting
- [ ] Add Prometheus metrics
- [ ] Complete Discord/Keycloak integration
- [ ] Load testing and optimization
- [ ] Security audit

---

## 🤝 Contributing

Contributions are welcome! This project is open source under the Apache 2.0 license.

**How to Contribute**:
1. Fork the repository
2. Create a feature branch from `staging`
3. Make your changes with clear commit messages
4. Add or update tests as needed
5. Submit a pull request
6. Address any review feedback

**Commit Message Format**:
```
Add feature: brief description

- Detailed change 1
- Detailed change 2
- Related documentation updates

Co-Authored-By: Name <email>
```

**Guidelines**:
- Follow existing code style and patterns
- Add tests for new features
- Update documentation as needed
- Keep pull requests focused and atomic
- Be respectful in discussions

---

## 📚 Documentation

Additional documentation available:

- [SETUP.md](SETUP.md) - Detailed setup instructions
- [EVENT_MANAGEMENT.md](EVENT_MANAGEMENT.md) - Event lifecycle guide
- [TESTING_EMAIL_GUIDE.md](TESTING_EMAIL_GUIDE.md) - Email testing procedures
- [GIT_SETUP.md](GIT_SETUP.md) - Git repository guidelines
- [backend/docs/](backend/docs/) - Technical design documents

---

## 🐛 Known Issues

**Medium Priority**:
- In-memory rate limiting (not distributed-safe for multi-instance deployments)
- Discord integration incomplete (webhooks.py TODOs)
- Keycloak sync not implemented (participant_service.py:494)
- Large seed file in repo (19MB seed_hacker_invite_template.py)

**Low Priority**:
- Event template config hardcoded (email_service.py:267)
- Inbound email processing placeholder (webhooks.py:87)

---

## 📧 Support & Contact

For questions or issues:
- **Issues**: Open an issue on GitHub
- **Discussions**: Use GitHub Discussions for questions
- **Security Issues**: Report privately via GitHub Security Advisories
- **Pull Requests**: Welcome for bug fixes and features

---

## 📄 License

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Copyright © 2026 CyberX Red Team

See [LICENSE](LICENSE) for the full license text.

---

## 🙏 Acknowledgments

Built with:
- FastAPI - Modern Python web framework
- SQLAlchemy - Python SQL toolkit
- SendGrid - Email delivery platform
- PostgreSQL - Relational database
- Alembic - Database migration tool
- APScheduler - Background job scheduling

Development assisted by Claude Code (Anthropic).

---

**Last Updated**: 2026-02-03  
**Version**: 0.1.0-beta (Pre-Production)
