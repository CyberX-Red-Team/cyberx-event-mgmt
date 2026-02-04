# Future Features & Enhancements

This document tracks potential features and enhancements to be considered for future development.

---

## 🔐 API Token Authentication

**Status:** Proposed
**Effort:** Medium (1.5-2 days)
**Priority:** To Be Determined

### Overview

Add support for API token (Bearer token) authentication alongside the existing cookie-based session authentication. This would enable programmatic access to the API for CI/CD pipelines, integrations, mobile apps, and other automated systems.

### Current State

**Authentication Methods:**
- ✅ Cookie-based session authentication (for web browsers)
- ✅ CSRF protection for state-changing operations
- ✅ Session management in PostgreSQL
- ✅ Rate limiting on login attempts

**Limitations:**
- No support for programmatic API access
- Cookie-based auth not ideal for headless clients
- No API token management

### Proposed Solution

**Dual Authentication Support:**
1. **Session Cookies** - For web/browser clients (existing)
2. **Bearer Tokens** - For API/programmatic clients (new)

**Key Features:**
- Personal Access Tokens (PAT) for users
- Token creation and management UI
- Token hashing (SHA256) - never store plaintext
- Optional expiration dates
- Revocation support
- Audit logging (creation, usage, revocation)
- Reuse existing authorization system (roles, permissions)

### Implementation Components

#### 1. Database Model
```sql
CREATE TABLE api_tokens (
    id SERIAL PRIMARY KEY,
    token_hash VARCHAR(255) UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    scopes VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_api_tokens_token_hash ON api_tokens(token_hash);
CREATE INDEX idx_api_tokens_user_id ON api_tokens(user_id);
```

**Alembic Migration:** Required

#### 2. Token Service
- `backend/app/services/api_token_service.py`
- Token generation (cryptographically secure)
- Token validation and user lookup
- Expiration checking
- Last used timestamp tracking

#### 3. Authentication Dependencies Update
- Modify `backend/app/dependencies.py`
- Update `get_current_user()` to accept both:
  - `Cookie: session_token=<token>` (existing)
  - `Authorization: Bearer <token>` (new)
- Automatic fallback between auth methods

**Benefits:** All existing protected endpoints automatically support both auth methods!

#### 4. API Endpoints
**New routes in `backend/app/api/routes/api_tokens.py`:**
- `POST /api/tokens` - Create new API token
- `GET /api/tokens` - List user's tokens (without plaintext)
- `DELETE /api/tokens/{id}` - Revoke token

#### 5. CSRF Exemption
- Bearer token requests bypass CSRF (stateless auth)
- Update middleware to skip CSRF for `Authorization: Bearer` requests

### Security Considerations

**Best Practices:**
- ✅ Store SHA256 hash, never plaintext
- ✅ Show plaintext token only once at creation
- ✅ Unique constraint on token_hash
- ✅ Track last_used_at for auditing
- ✅ Support revocation via is_active flag
- ✅ Cascade delete when user deleted
- ✅ Optional expiration dates

**Additional Recommendations:**
- Rate limiting for token-based requests
- Audit log for all token operations
- Optional: IP address restrictions per token
- Optional: Scope system (`read:users`, `write:events`)
- Token prefix for easy identification (`cyberx_...`)

### Usage Example

```bash
# 1. Login to web portal to create token
curl -c cookies.txt -X POST /api/auth/login \
  -d '{"username": "admin@example.com", "password": "pass"}'

# 2. Create API token
curl -b cookies.txt -X POST /api/tokens \
  -d '{"name": "CI/CD Pipeline", "expires_days": 90}'

# Response (token shown only once):
{
  "token": "cyberx_abc123def456...",
  "name": "CI/CD Pipeline",
  "created_at": "2026-02-04T...",
  "expires_at": "2026-05-05T..."
}

# 3. Use token for API access
curl -H "Authorization: Bearer cyberx_abc123def456..." \
  https://api.events.cyberxredteam.org/api/admin/users

# 4. Revoke token when no longer needed
curl -b cookies.txt -X DELETE /api/tokens/123
```

### Implementation Effort

| Component | Difficulty | Estimated Time |
|-----------|-----------|----------------|
| Database model & migration | Easy | 30 minutes |
| Token service | Medium | 2-3 hours |
| Update dependencies | Medium | 2 hours |
| Management endpoints | Medium | 3-4 hours |
| CSRF exemption | Easy | 15 minutes |
| Documentation | Easy | 1 hour |
| Tests | Medium | 2-3 hours |
| **Total** | **Medium** | **11-14 hours** |

### Alternative: Quick Implementation

**If immediate need exists:**
- Reuse Session table with `is_api_token` flag
- Generate long-lived sessions (1 year expiry)
- Return token as response instead of cookie
- **Effort:** 30 minutes
- **Tradeoff:** Less clean, harder to manage, but gets you unblocked

### Benefits

**For Developers:**
- Programmatic API access for scripts/tools
- CI/CD pipeline integration
- Mobile app authentication
- Third-party integrations

**For Security:**
- Separate tokens per use case
- Easy revocation without changing passwords
- Audit trail of API usage
- Scoped permissions (future)

**For Operations:**
- No need to share passwords
- Rotate tokens independently
- Monitor API usage per token
- Automated testing without credentials

### Related Documentation

- [Environment Variables](ENVIRONMENT_VARIABLES.md) - No new env vars needed
- [Authentication Guide](authentication_guide.md) - To be created when implemented
- Current auth: [backend/app/api/routes/auth.py](backend/app/api/routes/auth.py)

### Questions to Resolve Before Implementation

1. **Scope system needed?** Or just user-level auth (all user permissions)?
2. **Default expiration?** Never, 90 days, 1 year?
3. **Token naming convention?** Prefix like `cyberx_`, `cxem_`, or no prefix?
4. **Admin token management?** Can admins view/revoke other users' tokens?
5. **Rate limiting strategy?** Same as session auth or different limits?
6. **Token rotation?** Support automatic rotation for enhanced security?

### Decision

**Status:** Future consideration - not currently scheduled for implementation

**Next Steps When Ready:**
1. Review and validate approach with stakeholders
2. Answer outstanding questions
3. Create detailed technical specification
4. Implement in feature branch
5. Write comprehensive tests
6. Update documentation
7. Deploy to staging for testing
8. Roll out to production

---

*Last Updated: 2026-02-04*
