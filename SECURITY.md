# Security Policy

## Supported Versions

The following versions of the CyberX Event Management System are currently supported with security updates:

| Version | Supported          | Status                  |
| ------- | ------------------ | ----------------------- |
| 0.1.x   | :white_check_mark: | Beta - Active Development |
| < 0.1   | :x:                | Pre-release             |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please follow these guidelines:

### DO NOT

- ❌ Open a public GitHub issue
- ❌ Discuss the vulnerability publicly (forums, social media, etc.)
- ❌ Exploit the vulnerability maliciously

### DO

1. **Report via GitHub Security Advisories**
   - Navigate to: https://github.com/CyberX-Red-Team/cyberx-event-mgmt/security/advisories
   - Click "Report a vulnerability"
   - Provide detailed information (see below)

2. **Alternative: Email the maintainers**
   - If you cannot use GitHub Security Advisories
   - Contact information available in repository settings

### What to Include in Your Report

Please provide as much information as possible:

#### Required Information

- **Vulnerability Type**: (e.g., SQL Injection, XSS, Authentication Bypass, etc.)
- **Affected Component**: Which part of the system is vulnerable
- **Attack Scenario**: How an attacker could exploit this
- **Impact Assessment**: What damage could this cause

#### Helpful Information

- **Steps to Reproduce**: Detailed steps to replicate the issue
- **Proof of Concept**: Code or requests that demonstrate the vulnerability
- **Environment Details**: OS, Python version, database version, etc.
- **Suggested Fix**: If you have ideas for remediation
- **CVE Information**: If a CVE has been assigned

### Example Report Template

```markdown
**Vulnerability Type**: SQL Injection

**Affected Component**: User search endpoint (/api/admin/participants)

**Description**:
The user search functionality does not properly sanitize the 'email' parameter,
allowing SQL injection attacks.

**Steps to Reproduce**:
1. Authenticate as admin user
2. Send GET request to /api/admin/participants?email=' OR '1'='1
3. Observe that all participants are returned

**Impact**:
An authenticated attacker could:
- Extract sensitive user data
- Modify database contents
- Potentially gain administrative access

**Suggested Fix**:
Use parameterized queries or validate input with Pydantic schemas.

**Environment**:
- Version: 0.1.0-beta
- Python: 3.11
- PostgreSQL: 15.2
```

## Response Timeline

We aim to follow this timeline for security issues:

| Stage | Timeline |
|-------|----------|
| **Initial Response** | Within 48 hours |
| **Severity Assessment** | Within 5 business days |
| **Fix Development** | Depends on severity (see below) |
| **Public Disclosure** | After fix is deployed |

### Severity Levels and Response Time

#### Critical (CVSS 9.0-10.0)
- **Examples**: RCE, authentication bypass, mass data breach
- **Response Time**: Fix within 7 days
- **Disclosure**: After patch release

#### High (CVSS 7.0-8.9)
- **Examples**: SQL injection, privilege escalation, significant data exposure
- **Response Time**: Fix within 30 days
- **Disclosure**: After patch release

#### Medium (CVSS 4.0-6.9)
- **Examples**: Limited data exposure, denial of service, authorization issues
- **Response Time**: Fix within 60 days
- **Disclosure**: With next scheduled release

#### Low (CVSS 0.1-3.9)
- **Examples**: Information disclosure, configuration issues
- **Response Time**: Fix in next major release
- **Disclosure**: Normal release notes

## Security Update Process

### For Maintainers

1. **Acknowledge Receipt**: Confirm receipt within 48 hours
2. **Assess Severity**: Evaluate impact and assign CVSS score
3. **Develop Fix**: Create patch in private repository
4. **Test Fix**: Verify fix resolves issue without breaking changes
5. **Prepare Release**: Create security advisory and release notes
6. **Deploy Fix**: Release patch version
7. **Public Disclosure**: Publish security advisory with details

### For Users

1. **Subscribe to Advisories**: Watch repository for security notifications
2. **Update Promptly**: Apply security updates as soon as available
3. **Review Changes**: Check release notes for security fixes
4. **Test Deployment**: Verify fix works in your environment

## Security Features

### Current Security Implementations

#### Authentication & Authorization ✅
- Session-based authentication with secure cookies
- bcrypt password hashing (cost factor 12)
- Role-based access control (Admin, Sponsor, Invitee)
- Session expiry and management

#### Data Protection ✅
- Field-level encryption for sensitive data (Fernet AES-128)
- CSRF protection with signed tokens
- SQL injection prevention via SQLAlchemy ORM
- Input validation with Pydantic schemas

#### Network Security ✅
- CORS restrictions (limited origins and methods)
- SendGrid webhook signature verification (HMAC-SHA256)
- Rate limiting on authentication endpoints
- Secure headers recommended for production deployment

#### Audit & Monitoring ✅
- Comprehensive audit logging for security events
- Authentication attempt tracking
- Administrative action logging
- Email delivery tracking

### Known Security Limitations

#### Production Deployment Considerations ⚠️

1. **Rate Limiting**: In-memory implementation
   - **Impact**: Not distributed-safe for multi-instance deployments
   - **Mitigation**: Use Redis for production deployments
   - **Timeline**: Phase 3 of roadmap

2. **Session Storage**: In-memory storage
   - **Impact**: Sessions lost on restart, not shared across instances
   - **Mitigation**: Use Redis-based session storage for production
   - **Timeline**: Phase 3 of roadmap

3. **Secrets Management**: Environment variables
   - **Impact**: Secrets stored in plaintext config files
   - **Mitigation**: Use HashiCorp Vault or AWS Secrets Manager for production
   - **Timeline**: Production deployment guide

4. **VPN Credential Storage**: Database-stored private keys
   - **Impact**: Private keys accessible if database is compromised
   - **Mitigation**: Database encryption at rest, restricted access
   - **Status**: Acceptable for current threat model

## Security Best Practices for Deployment

### Production Environment

```bash
# Use strong secrets
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(64))")
CSRF_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(64))")

# Generate Fernet encryption key
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Disable debug mode
DEBUG=False

# Restrict CORS
ALLOWED_HOSTS=your-domain.com,www.your-domain.com

# Enable webhook verification
SENDGRID_WEBHOOK_VERIFICATION_KEY=your-verification-key
```

### Database Security

- Use strong PostgreSQL passwords
- Enable SSL/TLS connections
- Restrict network access to database
- Regular backups with encryption
- Database user with minimal required privileges

### Network Security

- Deploy behind reverse proxy (nginx, Caddy)
- Use TLS/HTTPS for all traffic
- Configure security headers:
  ```
  Strict-Transport-Security: max-age=31536000
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Content-Security-Policy: default-src 'self'
  ```

### Monitoring & Alerting

- Monitor authentication failures
- Alert on suspicious activity patterns
- Track failed VPN assignment attempts
- Monitor email bounce rates
- Log review procedures

## Vulnerability Disclosure Policy

### Coordinated Disclosure

We follow a coordinated disclosure process:

1. **Private Notification**: Reporter notifies us privately
2. **Acknowledgment**: We confirm receipt within 48 hours
3. **Investigation**: We assess and validate the vulnerability
4. **Fix Development**: We develop and test a fix
5. **Advisory Preparation**: We prepare security advisory
6. **Release**: We release patched version
7. **Public Disclosure**: We publish advisory 7 days after release

### Public Recognition

- We credit security researchers in release notes
- With permission, we list researchers in SECURITY.md
- We maintain a security hall of fame (if applicable)

### Scope

#### In Scope ✅
- Authentication and authorization bypasses
- SQL injection vulnerabilities
- Cross-site scripting (XSS)
- Cross-site request forgery (CSRF)
- Server-side request forgery (SSRF)
- Remote code execution
- Privilege escalation
- Data exposure vulnerabilities
- Cryptographic weaknesses

#### Out of Scope ❌
- Social engineering attacks
- Physical attacks
- Denial of service (DoS/DDoS) - unless amplification exists
- Brute force attacks on properly rate-limited endpoints
- Already-known vulnerabilities pending fix
- Vulnerabilities in dependencies (report to upstream)
- Theoretical vulnerabilities without proof of concept

## Security Contacts

- **GitHub Security Advisories**: https://github.com/CyberX-Red-Team/cyberx-event-mgmt/security
- **Public Repository**: https://github.com/CyberX-Red-Team/cyberx-event-mgmt
- **Discussions**: GitHub Discussions for general security questions

## Acknowledgments

We thank the following security researchers for responsible disclosure:

*No vulnerabilities reported yet. Be the first!*

## Security Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- [CVSS Calculator](https://www.first.org/cvss/calculator/3.1)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [SQLAlchemy Security](https://docs.sqlalchemy.org/en/14/faq/security.html)

---

**Last Updated**: 2026-02-05
**Security Policy Version**: 1.0
