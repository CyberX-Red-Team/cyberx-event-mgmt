# Email Testing Safety Guide

This guide explains how to safely test email functionality without accidentally sending emails to real users.

## Problem
When testing invitation workflows or other email features, you might accidentally send emails to real user email addresses in your database.

## Solutions

### Option 1: SendGrid Sandbox Mode (Recommended for Testing Workflow)

**What it does**: Emails are validated by SendGrid but NOT actually delivered to recipients. You can verify the email was processed without any recipients receiving it.

**How to enable**:
```bash
# Add to your .env file
SENDGRID_SANDBOX_MODE=true
```

**When to use**:
- Testing the invitation workflow end-to-end
- Verifying email templates render correctly
- Checking that email queue processing works
- You want to see SendGrid accept the email but not deliver it

**Benefits**:
- ✅ No emails actually sent to real users
- ✅ SendGrid validates the email (catches errors)
- ✅ Email events are logged in your database
- ✅ You can verify the workflow completed successfully

**Drawbacks**:
- ❌ You won't see the actual email in an inbox
- ❌ Can't test email rendering in real email clients

---

### Option 2: Test Email Override (Recommended for Viewing Actual Emails)

**What it does**: All emails are redirected to a single test email address that you control. The subject line will show who the email was originally intended for.

**How to enable**:
```bash
# Add to your .env file
TEST_EMAIL_OVERRIDE=your-test-email@example.com
```

**Example**: If an email would go to `john.doe@company.com`, it will instead go to your test email with subject:
```
[TEST for john.doe@company.com] CyberX 2026 - Confirm Your Participation
```

**When to use**:
- You want to see the actual email rendering
- Testing email content and links
- Verifying confirmation URLs work
- Need to click links in the email

**Benefits**:
- ✅ See real emails in your inbox
- ✅ Test email rendering across email clients
- ✅ Click and test confirmation links
- ✅ No spam to real users

**Drawbacks**:
- ⚠️ Emails ARE actually sent (just to your test address)
- ⚠️ Uses SendGrid quota

---

### Option 3: Combine Both (Maximum Safety)

**How to enable**:
```bash
# Add to your .env file
SENDGRID_SANDBOX_MODE=true
TEST_EMAIL_OVERRIDE=your-test-email@example.com
```

**What happens**: Emails are redirected to your test address AND sandbox mode is enabled, so they're validated but not delivered.

**When to use**: Maximum safety during development

---

## Recommended Testing Workflow

### Phase 1: Initial Testing (Sandbox Mode)
```bash
# .env
SENDGRID_SANDBOX_MODE=true
TEST_EMAIL_OVERRIDE=
```

1. Toggle event test mode ON
2. Wait 30 seconds for scheduled task
3. Check logs - should see "Successfully queued X invitation emails"
4. Run email batch processor (or wait for scheduled job)
5. Verify emails were processed without errors
6. Check email queue - status should be "sent"
7. No actual emails delivered ✅

### Phase 2: Content Testing (Email Override)
```bash
# .env
SENDGRID_SANDBOX_MODE=false
TEST_EMAIL_OVERRIDE=your-test-email@example.com
```

1. Trigger invitation workflow
2. Check your test email inbox
3. Verify email content, styling, links
4. Click confirmation URL and test the flow
5. Verify email renders correctly

### Phase 3: Production (Disable All Safety Features)
```bash
# .env
SENDGRID_SANDBOX_MODE=false
TEST_EMAIL_OVERRIDE=
```

⚠️ **Only use in production when you're ready to send real emails!**

---

## How to Check if Safety Features Are Active

You can verify your current settings:

```bash
# Check your .env file
grep SENDGRID_SANDBOX_MODE .env
grep TEST_EMAIL_OVERRIDE .env
```

Or check via Python:
```python
from app.config import get_settings
settings = get_settings()
print(f"Sandbox mode: {settings.SENDGRID_SANDBOX_MODE}")
print(f"Email override: {settings.TEST_EMAIL_OVERRIDE or 'Not set'}")
```

---

## Testing Checklist

Before testing invitation workflow:
- [ ] Check `.env` has `SENDGRID_SANDBOX_MODE=true` OR `TEST_EMAIL_OVERRIDE=your-email`
- [ ] Restart server to pick up config changes
- [ ] Clear email queue if needed
- [ ] **Enable event test_mode flag** (see note below about test mode)
- [ ] Toggle test mode or activate event
- [ ] Monitor logs for "Successfully queued X invitation emails"
- [ ] Verify no real users receive emails

After successful testing:
- [ ] Remove or comment out test settings from `.env`
- [ ] Restart server
- [ ] Verify settings are back to production values

---

## Test Mode Flag vs Email Testing Features

**Two Different Protection Mechanisms:**

### Event Test Mode Flag (`test_mode=true`)
- **What it protects**: Prevents emails to non-sponsors
- **Scope**: Database/application level
- **How it works**: Emails only go to sponsor users, all non-sponsors are blocked
- **When to use**: Testing with real email delivery to a controlled group (sponsors)
- **Controlled via**: Event settings in admin panel

### Email Testing Features (Sandbox/Override)
- **What they protect**: Prevents actual email delivery or redirects to test address
- **Scope**: SendGrid/email service level
- **How it works**: All emails validated/redirected regardless of recipient
- **When to use**: Development/staging environments
- **Controlled via**: `.env` configuration file

### Combined Protection (Recommended for Testing)

```bash
# Maximum safety for testing
SENDGRID_SANDBOX_MODE=true  # ← No emails actually sent
TEST_EMAIL_OVERRIDE=your-test-email@example.com  # ← Redirects to your email
```

```yaml
Event Settings:
  test_mode: true  # ← Only sponsors receive emails
```

**Result**:
- Only sponsors would receive emails (test mode)
- But even those are redirected to your test email (override)
- And not actually delivered (sandbox mode)
- Triple protection! ✅✅✅

### Important Distinction

**Test Mode Flag** = "Who can receive emails?" (sponsors only)
**Sandbox Mode** = "Should emails actually be delivered?" (no, just validate)
**Email Override** = "Where should emails go?" (your test address)

**Best Practice**: Use all three during development, then remove only the `.env` settings for production while keeping test_mode for controlled sponsor testing.

---

## Emergency: Accidentally Sent Emails?

If you accidentally queued emails without safety features enabled:

1. **Stop the email processor immediately** (if running)
2. **Clear the email queue**:
   ```python
   python -c "
   import asyncio
   from sqlalchemy import delete, select
   from app.database import AsyncSessionLocal
   from app.models.email_queue import EmailQueue

   async def clear():
       async with AsyncSessionLocal() as session:
           # Only delete pending emails
           result = await session.execute(
               delete(EmailQueue).where(EmailQueue.status == 'pending')
           )
           await session.commit()
           print(f'Deleted {result.rowcount} pending emails')

   asyncio.run(clear())
   "
   ```
3. **Re-enable safety features** in `.env`
4. **Restart server**

---

## Current Implementation

The email safety features are implemented in:
- **Config**: `app/config.py` (lines 19-24)
- **Email Service**: `app/services/email_service.py`
  - Template emails: Lines 298-328
  - Custom emails: Lines 393-421

Both `SENDGRID_SANDBOX_MODE` and `TEST_EMAIL_OVERRIDE` are applied to ALL outgoing emails system-wide.
