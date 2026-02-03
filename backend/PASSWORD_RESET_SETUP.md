# Password Reset Email Workflow Setup

This guide explains how to configure and test the password reset email workflow.

## Overview

The password reset workflow is now fully implemented. When a user requests a password reset:

1. A secure reset token is generated and stored in the database (expires in 1 hour)
2. An audit log entry is created
3. **NEW**: An email workflow is triggered automatically
4. The email is queued and sent via SendGrid

## Prerequisites

✅ Already implemented:
- Token generation and storage
- Audit logging
- Workflow trigger code
- Email queue system

⚠️ **Requires configuration:**
- Email template for PASSWORD_RESET event
- Email workflow configuration
- SendGrid template (optional, can use HTML in database)

---

## Setup Instructions

### Step 1: Create Email Template

You need to create an email template for password reset emails.

#### Option A: Using SendGrid Dynamic Templates (Recommended)

1. **Create template in SendGrid:**
   - Log in to SendGrid dashboard
   - Go to Email API → Dynamic Templates
   - Create new template: "Password Reset"
   - Add dynamic variables: `{{reset_url}}`, `{{first_name}}`, `{{last_name}}`

2. **Get template ID:**
   - Copy the template ID (e.g., `d-1234567890abcdef`)

3. **Add to database via API:**
   ```bash
   curl -X POST http://localhost:8000/api/admin/email-templates \
     -H "Content-Type: application/json" \
     -H "Cookie: session_token=YOUR_SESSION" \
     -d '{
       "name": "password_reset",
       "subject": "Reset Your Password - CyberX Red Team",
       "sendgrid_template_id": "d-1234567890abcdef",
       "description": "Password reset email with secure link"
     }'
   ```

#### Option B: Using HTML in Database

If you don't want to use SendGrid templates:

```bash
curl -X POST http://localhost:8000/api/admin/email-templates \
  -H "Content-Type: application/json" \
  -H "Cookie: session_token=YOUR_SESSION" \
  -d '{
    "name": "password_reset",
    "subject": "Reset Your Password - CyberX Red Team",
    "html_content": "<!DOCTYPE html><html><body><h1>Password Reset Request</h1><p>Hi {{first_name}},</p><p>We received a request to reset your password. Click the link below to create a new password:</p><p><a href=\"{{reset_url}}\">Reset Password</a></p><p>This link will expire in 1 hour.</p><p>If you didn'\''t request this, please ignore this email.</p><p>Best regards,<br>CyberX Red Team</p></body></html>",
    "description": "Password reset email with secure link"
  }'
```

---

### Step 2: Create Email Workflow

Create a workflow that triggers on PASSWORD_RESET event:

```bash
curl -X POST http://localhost:8000/api/admin/email-workflows \
  -H "Content-Type: application/json" \
  -H "Cookie: session_token=YOUR_SESSION" \
  -d '{
    "name": "Password Reset Workflow",
    "description": "Sends password reset email when user requests password reset",
    "trigger_event": "password_reset",
    "template_name": "password_reset",
    "is_enabled": true,
    "priority": 1,
    "delay_minutes": 0
  }'
```

**Important fields:**
- `trigger_event`: Must be `"password_reset"` (matches `WorkflowTriggerEvent.PASSWORD_RESET`)
- `template_name`: Must match the name of your email template
- `is_enabled`: Set to `true` to activate
- `priority`: Lower number = higher priority
- `delay_minutes`: Set to 0 for immediate send

---

### Step 3: Configure Frontend URL

Ensure your `.env` file has the correct frontend URL:

```bash
# For production
FRONTEND_URL=https://portal.cyberxredteam.org

# For local development
FRONTEND_URL=http://localhost:8000

# For staging
FRONTEND_URL=https://staging.cyberxredteam.org
```

The password reset link will be: `{FRONTEND_URL}/reset-password?token={reset_token}`

---

### Step 4: Create Frontend Reset Password Page

Your frontend needs a page at `/reset-password` that:

1. Extracts the token from the URL query parameter
2. Shows a form to enter new password
3. Calls the API endpoint: `POST /api/auth/password/reset/complete`

**Example API call:**
```javascript
const token = new URLSearchParams(window.location.search).get('token');

const response = await fetch('/api/auth/password/reset/complete', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    token: token,
    new_password: 'newSecurePassword123'
  })
});
```

---

## Testing the Workflow

### Test 1: Request Password Reset

```bash
# Request password reset
curl -X POST http://localhost:8000/api/auth/password/reset/request \
  -H "Content-Type: application/json" \
  -d '{"email": "testuser@example.com"}'
```

**Expected response:**
```json
{
  "message": "If an account with that email exists, a password reset link has been sent",
  "success": true
}
```

**Note**: This response is returned even if the email doesn't exist (prevents email enumeration).

### Test 2: Check Email Queue

```bash
# Check email queue
curl http://localhost:8000/api/admin/email-queue \
  -H "Cookie: session_token=YOUR_SESSION"
```

You should see a queued email with:
- Status: `PENDING` or `PROCESSING`
- Template: `password_reset`
- Custom vars containing `reset_url` and `reset_token`

### Test 3: Check SendGrid Activity

1. Log in to SendGrid dashboard
2. Go to Activity Feed
3. Look for email sent to the user
4. Verify it contains the reset link

### Test 4: Complete Password Reset

1. Get the reset token from the email or database
2. Call the complete endpoint:

```bash
curl -X POST http://localhost:8000/api/auth/password/reset/complete \
  -H "Content-Type: application/json" \
  -d '{
    "token": "THE_RESET_TOKEN_FROM_EMAIL",
    "new_password": "NewSecurePassword123"
  }'
```

**Expected response:**
```json
{
  "message": "Password successfully reset",
  "success": true
}
```

### Test 5: Verify New Password Works

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser@example.com",
    "password": "NewSecurePassword123"
  }'
```

Should return successful login with session token.

---

## Email Template Variables

The password reset workflow provides these variables to templates:

| Variable | Example | Description |
|----------|---------|-------------|
| `reset_url` | `https://portal.../reset-password?token=abc123` | Full URL to reset password page |
| `reset_token` | `abc123xyz...` | The reset token (if you want to show it separately) |
| `first_name` | `John` | User's first name |
| `last_name` | `Doe` | User's last name |
| `email` | `john@example.com` | User's email address |

### Example SendGrid Template

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Password Reset</title>
</head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h1 style="color: #333;">Password Reset Request</h1>
    
    <p>Hi {{first_name}},</p>
    
    <p>We received a request to reset the password for your CyberX Red Team account ({{email}}).</p>
    
    <p>Click the button below to create a new password:</p>
    
    <p style="text-align: center; margin: 30px 0;">
        <a href="{{reset_url}}" 
           style="background-color: #dc3545; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">
            Reset Password
        </a>
    </p>
    
    <p>Or copy and paste this link into your browser:</p>
    <p style="background-color: #f5f5f5; padding: 10px; word-wrap: break-word;">{{reset_url}}</p>
    
    <p><strong>This link will expire in 1 hour.</strong></p>
    
    <p>If you didn't request a password reset, please ignore this email. Your password will remain unchanged.</p>
    
    <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;">
    
    <p style="color: #666; font-size: 12px;">
        Best regards,<br>
        CyberX Red Team<br>
        <a href="https://cyberxredteam.org">cyberxredteam.org</a>
    </p>
</body>
</html>
```

---

## Troubleshooting

### Email not received

**Check 1: Is workflow enabled?**
```sql
SELECT * FROM email_workflows WHERE trigger_event = 'password_reset';
-- Verify is_enabled = true
```

**Check 2: Is email in queue?**
```sql
SELECT * FROM email_queue 
WHERE user_id = (SELECT id FROM users WHERE email = 'testuser@example.com')
ORDER BY created_at DESC LIMIT 5;
```

**Check 3: Check email queue status**
- `PENDING`: Waiting to be processed
- `PROCESSING`: Currently being sent
- `SENT`: Successfully sent
- `FAILED`: Check error_message field

**Check 4: SendGrid sandbox mode**
```bash
# Check if SendGrid is in sandbox mode
grep SENDGRID_SANDBOX_MODE .env
# Should be: SENDGRID_SANDBOX_MODE=false
```

**Check 5: Test mode restrictions**
```sql
SELECT test_mode FROM events WHERE is_active = true;
-- If true, only sponsors receive emails
```

### Token expired

Tokens expire after 1 hour. Request a new password reset.

### Invalid token error

Check that:
- Token hasn't been used already (tokens are single-use)
- Token hasn't expired
- Token is copied correctly (no extra spaces)

### Frontend page not found

Ensure your frontend has a page at `/reset-password` that handles the token.

---

## Security Notes

✅ **Implemented:**
- Secure token generation (`secrets.token_urlsafe(32)`)
- 1-hour token expiration
- Single-use tokens (cleared after use)
- No email enumeration (same response for existing/non-existing emails)
- Audit logging of all password reset requests
- HTTPS-only in production

⚠️ **Additional recommendations:**
- Rate limit password reset requests (prevent abuse)
- Monitor audit logs for suspicious activity
- Consider 2FA for admin accounts
- Log successful password resets

---

## Configuration Checklist

Before going live:

- [ ] Email template created in SendGrid or database
- [ ] Email workflow created and enabled
- [ ] FRONTEND_URL set correctly in .env
- [ ] Frontend /reset-password page implemented
- [ ] Test mode disabled (if applicable)
- [ ] SendGrid sandbox mode disabled
- [ ] Tested full flow end-to-end
- [ ] Audit logs verified
- [ ] Email delivery confirmed

---

**Last Updated:** 2026-02-03  
**Status:** ✅ Implemented and ready for configuration  
**Related Commit:** cb3623a
