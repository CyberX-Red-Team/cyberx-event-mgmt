# CSRF Protection Guide

This guide explains the CSRF (Cross-Site Request Forgery) protection implementation and how to use it with the frontend.

## Overview

CSRF protection prevents attackers from tricking authenticated users into performing unwanted actions on the application.

**Implemented**: starlette-csrf middleware  
**Status**: ✅ Enabled in production and development  
**Cookie**: `csrf_token`  
**Header**: `X-CSRF-Token`

---

## Installation

### Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

This installs `starlette-csrf==1.4.4` along with other dependencies.

### Verify Installation

```bash
python -c "from starlette_csrf import CSRFMiddleware; print('✓ CSRF middleware installed')"
```

---

## How It Works

### 1. Server Sets CSRF Token

When a user makes their first request, the server sets a `csrf_token` cookie:

```http
Set-Cookie: csrf_token=abc123xyz...; Path=/; SameSite=lax; Secure
```

### 2. Client Reads Token

The client (frontend JavaScript) reads the cookie:

```javascript
function getCsrfToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrf_token') {
            return value;
        }
    }
    return null;
}
```

### 3. Client Includes Token in Requests

**For AJAX/Fetch Requests** (Recommended):
```javascript
const csrfToken = getCsrfToken();

fetch('/api/auth/login', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken  // Include token in header
    },
    credentials: 'include',  // Include cookies
    body: JSON.stringify({
        username: 'user@example.com',
        password: 'password123'
    })
});
```

**For HTML Forms**:
```html
<form method="POST" action="/api/some-endpoint">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <input type="text" name="username">
    <input type="password" name="password">
    <button type="submit">Submit</button>
</form>
```

### 4. Server Validates Token

The middleware automatically validates that the token in the request matches the cookie.

- ✅ **Valid**: Request proceeds normally
- ❌ **Invalid**: Returns `403 Forbidden`

---

## Frontend Integration Examples

### React/Next.js

**Create a utility hook:**

```javascript
// hooks/useCsrfToken.js
import { useEffect, useState } from 'react';

export function useCsrfToken() {
    const [token, setToken] = useState(null);

    useEffect(() => {
        const getCookie = (name) => {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                const [cookieName, value] = cookie.trim().split('=');
                if (cookieName === name) {
                    return value;
                }
            }
            return null;
        };

        setToken(getCookie('csrf_token'));
    }, []);

    return token;
}
```

**Use in components:**

```javascript
import { useCsrfToken } from '../hooks/useCsrfToken';

function LoginForm() {
    const csrfToken = useCsrfToken();

    const handleSubmit = async (e) => {
        e.preventDefault();

        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken  // Include CSRF token
            },
            credentials: 'include',
            body: JSON.stringify({
                username: email,
                password: password
            })
        });

        // Handle response...
    };

    return (
        <form onSubmit={handleSubmit}>
            {/* Form fields */}
        </form>
    );
}
```

### Vanilla JavaScript

**Create a reusable API client:**

```javascript
// api.js
class APIClient {
    constructor(baseURL) {
        this.baseURL = baseURL;
    }

    getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrf_token') {
                return value;
            }
        }
        return null;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const csrfToken = this.getCsrfToken();

        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };

        // Add CSRF token for state-changing requests
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(options.method?.toUpperCase())) {
            headers['X-CSRF-Token'] = csrfToken;
        }

        const response = await fetch(url, {
            ...options,
            headers,
            credentials: 'include'  // Include cookies
        });

        if (!response.ok) {
            if (response.status === 403) {
                throw new Error('CSRF validation failed. Please refresh the page.');
            }
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        return response.json();
    }

    // Convenience methods
    async get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    }

    async post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
}

// Usage
const api = new APIClient('http://localhost:8000');

// Login
await api.post('/api/auth/login', {
    username: 'user@example.com',
    password: 'password123'
});

// Create participant
await api.post('/api/admin/participants', {
    email: 'newuser@example.com',
    first_name: 'John',
    last_name: 'Doe'
});
```

### Axios

```javascript
import axios from 'axios';

// Create axios instance with CSRF interceptor
const api = axios.create({
    baseURL: 'http://localhost:8000',
    withCredentials: true  // Include cookies
});

// Add CSRF token to all requests
api.interceptors.request.use((config) => {
    // Get CSRF token from cookie
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrf_token') {
            config.headers['X-CSRF-Token'] = value;
            break;
        }
    }
    return config;
});

// Usage
await api.post('/api/auth/login', {
    username: 'user@example.com',
    password: 'password123'
});
```

---

## Exempt Endpoints

These endpoints do NOT require CSRF tokens (they accept external POSTs):

| Endpoint | Purpose | Why Exempt |
|----------|---------|------------|
| `/api/webhooks/sendgrid` | SendGrid event webhook | External service |
| `/api/webhooks/discord` | Discord OAuth callback | External service |
| `/api/public/confirm` | Participant confirmation | Public action from email |
| `/api/public/decline` | Participant decline | Public action from email |
| `/health` | Health check | Monitoring endpoint |

All other POST/PUT/DELETE endpoints require CSRF tokens.

---

## Testing CSRF Protection

### Test 1: Valid Request with CSRF Token

```bash
# 1. Get CSRF token from cookies
CSRF_TOKEN=$(curl -s -c cookies.txt http://localhost:8000/health | \
    grep csrf_token cookies.txt | awk '{print $7}')

# 2. Make authenticated request with CSRF token
curl -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: $CSRF_TOKEN" \
    -b cookies.txt \
    -d '{"username": "admin@example.com", "password": "password123"}'
```

**Expected**: `200 OK` with login response

### Test 2: Request WITHOUT CSRF Token (Should Fail)

```bash
curl -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username": "admin@example.com", "password": "password123"}'
```

**Expected**: `403 Forbidden` with CSRF error

### Test 3: Exempt Endpoint (No Token Required)

```bash
curl -X POST http://localhost:8000/api/webhooks/sendgrid \
    -H "Content-Type: application/json" \
    -d '{"event": "delivered", "email": "test@example.com"}'
```

**Expected**: `200 OK` (no CSRF token needed)

### Test 4: Using Browser DevTools

1. Open browser DevTools (F12)
2. Go to Application → Cookies
3. Verify `csrf_token` cookie exists
4. Go to Console and run:

```javascript
// Get CSRF token
const csrfToken = document.cookie.split(';')
    .find(c => c.trim().startsWith('csrf_token='))
    ?.split('=')[1];
console.log('CSRF Token:', csrfToken);

// Test protected endpoint
fetch('/api/admin/participants', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken
    },
    credentials: 'include',
    body: JSON.stringify({
        email: 'test@example.com',
        first_name: 'Test',
        last_name: 'User'
    })
}).then(r => r.json()).then(console.log);
```

---

## Common Issues & Troubleshooting

### Issue: 403 Forbidden on Every Request

**Cause**: CSRF token not being sent or cookie not set

**Solutions:**
1. Check cookie exists: `document.cookie` in browser console
2. Verify `credentials: 'include'` in fetch/axios config
3. Check CORS allows credentials: `allow_credentials=True`
4. Ensure cookie is not HttpOnly (it's set to `False` for JavaScript access)

### Issue: CSRF Token Cookie Not Set

**Cause**: Browser blocking third-party cookies or SameSite issues

**Solutions:**
1. Ensure frontend and backend are on same domain (or use subdomain)
2. Check SameSite cookie policy (`lax` should work for most cases)
3. In development, use `localhost` for both frontend and backend

### Issue: Token Changes Between Requests

**Cause**: Multiple instances or server restarts

**Solution**: Token rotates on certain actions (this is normal). Just read the latest cookie value before each request.

### Issue: Exempt Endpoint Still Requires Token

**Cause**: URL not matching exempt list exactly

**Solution**: Check exact URL path in `main.py` exempt_urls list

---

## Security Best Practices

### ✅ Do:

- Always include CSRF token in state-changing requests (POST/PUT/DELETE)
- Use HTTPS in production (enforced by `cookie_secure=True`)
- Keep csrf_token cookie with SameSite=lax
- Read token from cookie on each request (don't cache long-term)
- Log CSRF failures for security monitoring

### ❌ Don't:

- Don't disable CSRF protection for convenience
- Don't send CSRF token in URL parameters (use headers)
- Don't make CSRF cookie HttpOnly (JavaScript needs to read it)
- Don't exempt endpoints unless they truly need external POSTs
- Don't store CSRF token in localStorage (XSS vulnerability)

---

## Configuration Reference

### Environment Variables

```bash
# .env file
SECRET_KEY=your-secret-key-here
CSRF_SECRET_KEY=different-csrf-secret  # Optional, defaults to SECRET_KEY
DEBUG=False  # Set to True for development
```

### Middleware Configuration

```python
# main.py
app.add_middleware(
    CSRFMiddleware,
    secret=settings.CSRF_SECRET_KEY or settings.SECRET_KEY,
    exempt_urls=[...],           # Endpoints that don't need CSRF
    cookie_name="csrf_token",    # Cookie name
    cookie_secure=True,          # HTTPS only in production
    cookie_samesite="lax",       # SameSite policy
    cookie_httponly=False,       # JavaScript needs access
    header_name="X-CSRF-Token",  # Header name for token
)
```

---

## Monitoring CSRF

### Audit Logs

CSRF failures are not currently logged, but you can add custom logging:

```python
# Add to global exception handler in main.py
if response.status_code == 403:
    logger.warning(
        f"CSRF validation failed: {request.client.host} -> {request.url.path}"
    )
```

### Metrics to Track

- Number of CSRF failures (indicates attacks or integration issues)
- CSRF failures by IP address (detect attack sources)
- CSRF failures by endpoint (identify problematic endpoints)
- CSRF failures over time (spot attack campaigns)

---

## Migration Checklist

Before deploying CSRF protection:

- [ ] Install starlette-csrf: `pip install starlette-csrf`
- [ ] Update frontend to include X-CSRF-Token header
- [ ] Test all forms and AJAX requests
- [ ] Verify exempt endpoints work without token
- [ ] Test with real browsers (Chrome, Firefox, Safari)
- [ ] Check mobile app integration if applicable
- [ ] Update API documentation with CSRF requirements
- [ ] Train team on CSRF token usage
- [ ] Set up monitoring for CSRF failures
- [ ] Have rollback plan ready

---

**Last Updated:** 2026-02-03  
**Status:** ✅ Implemented and ready for use  
**Related Commit:** 1b1bab8
