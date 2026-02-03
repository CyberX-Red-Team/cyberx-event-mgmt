# Event Management & Testing Guide

This guide explains how to safely manage CyberX events, prevent accidental mass emails, and test features before general availability.

## Table of Contents
- [Event Lifecycle Overview](#event-lifecycle-overview)
- [Safe Event Setup Workflow](#safe-event-setup-workflow)
- [Safeguards & Protection](#safeguards--protection)
- [Testing with Sponsors](#testing-with-sponsors)
- [Common Scenarios](#common-scenarios)
- [Troubleshooting](#troubleshooting)

---

## Event Lifecycle Overview

### Event Status Flags

Events have four key status flags that control different aspects of functionality:

| Flag | Purpose | Controls |
|------|---------|----------|
| `is_active` | Event is the current active event | System determines which event is "current" |
| `registration_open` | Users can be invited/register | **Mass email operations** and bulk invitations |
| `test_mode` | Sponsor testing enabled | Allows sponsors to test VPN/Keycloak before general availability |
| `vpn_available` | VPN access is open to all | All participants can request VPN credentials |

### Flag Hierarchy

**Important: test_mode ALWAYS RESTRICTS to sponsors only, regardless of registration_open**

```
is_active (Required for everything)
├── test_mode = true (ALWAYS restricts to sponsors only)
│   ├── registration_open = false → Sponsors only: VPN testing, limited emails
│   └── registration_open = true → Still sponsors only (registration_open ignored!)
└── test_mode = false (Normal operation)
    ├── registration_open = false → No VPN access, no mass emails
    ├── registration_open = true, vpn_available = false → Mass emails allowed, no VPN
    └── registration_open = true, vpn_available = true → Full access for all
```

**Key Rule:** Test mode is the master safety switch - when ON, only sponsors receive emails.

---

## Safe Event Setup Workflow

Follow this sequence to safely set up an event without accidentally emailing your entire user base.

### Step 1: Create Event
```
Status: is_active=false, registration_open=false, test_mode=false, vpn_available=false
Result: Event exists but is dormant. No operations possible.
```

**Actions:**
1. Go to Admin → Events
2. Click "Create New Event"
3. Fill in year, name, dates, etc.
4. Leave all toggles OFF
5. Save

**✓ Protection:** No emails can be sent, no VPN access.

---

### Step 2: Enable Test Mode (BEFORE Activation - Safest!)
```
Status: is_active=false, registration_open=false, test_mode=true, vpn_available=false
Result: Test mode enabled but event still inactive. No workflow triggers.
```

**Actions:**
1. Find your event in the events table
2. Click the Test Mode toggle (⚡ icon)
3. Confirm test mode

**✓ Protection:**
- Test mode enabled but event not active yet
- No automated workflows can trigger
- Safe to configure and prepare

**💡 Why This Order?** Enabling test mode while inactive prevents any workflow triggers. When you activate next, the system will automatically send invites to sponsors only!

---

### Step 3: Activate Event (With Test Mode Already Enabled)
```
Status: is_active=true, registration_open=false, test_mode=true, vpn_available=false
Result: Event becomes active and automatically invites sponsors only.
```

**Actions:**
1. Click the "Activate" button
2. Confirm activation

**✅ What Happens:**
- Event becomes active
- Automated invitation workflow triggers
- **Only sponsors** receive invitation emails (30 seconds after activation)
- Invitees are excluded (test mode protection)

**✓ Protection:**
- Sponsors get invited automatically for testing
- Invitees protected from accidental emails
- VPN access available to sponsors only

**Alternative (Less Safe):**
If you activate BEFORE enabling test mode:
- First activation may trigger invites to everyone (if registration_open=true)
- Safer to enable test mode first while inactive

---

### Step 4: Test with Sponsors
```
Status: is_active=true, registration_open=false, test_mode=true, vpn_available=false
Result: Sponsors have been automatically invited and can test VPN access.
```

**Testing Activities:**
- Sponsors receive invitation emails automatically
- Sponsors can request VPN credentials
- Verify Keycloak sync works
- Test email workflows with sponsor group
- Validate portal functionality

---

### Step 5: Open Registration (When Ready!)
```
Status: is_active=true, registration_open=true, test_mode=false, vpn_available=false
Result: Mass invitations can go out. VPN still protected.
```

**Actions:**
1. **FIRST: Disable test mode** (click ⚡ icon to turn off)
   - While test_mode=true, only sponsors receive emails even if registration is open
2. Go to Events table
3. Find the "Registration" column
4. Click to toggle "Open" (turns green)

**⚠️ IMPORTANT:** You must disable test_mode first, or emails will still be restricted to sponsors!

**✓ What This Enables (after disabling test mode):**
- Bulk email operations to all users
- Mass invitation workflows
- User self-registration (if enabled)
- Confirmation email sending

**✓ Still Protected:**
- VPN requests still blocked (unless vpn_available=true)
- Can control VPN access separately from invitations

**⚠️ Common Mistake:** Opening registration while test_mode=true won't send emails to invitees - test mode always restricts to sponsors only!

---

### Step 6: Enable VPN Access (Later)
```
Status: is_active=true, registration_open=true, test_mode=false, vpn_available=true
Result: Full access for all participants.
```

**Actions:**
1. Find the "VPN" column in events table
2. Click the VPN toggle (shield icon)
3. Turns green when enabled

**✓ What This Enables:**
- All confirmed participants can request VPNs
- Participants see VPN request form on portal
- VPN credentials can be downloaded

**💡 Tip:** Enable this 1-2 weeks before event start, not immediately with registration.

---

## Safeguards & Protection

### 1. Bulk Email Protection (10+ User Threshold)

When attempting to send emails to **10 or more users**, the system enforces:

```python
# Automatic check
if len(recipients) >= 10:
    # TEST MODE ALWAYS RESTRICTS: If test mode is enabled, only sponsors allowed
    if test_mode:
        if not all_sponsors:
            raise Exception("Test mode restricts all emails to sponsors only")
    # NOT IN TEST MODE: Require registration to be open
    elif not registration_open:
        raise Exception("Cannot send bulk emails - registration not open")
```

**Error Messages You'll See:**

*In Test Mode:*
```
Cannot send bulk emails to non-sponsors while CyberX 2025 is in test mode.
Test mode restricts all emails to sponsors only.
Disable test mode or send only to sponsor users.
```

*Registration Closed (not in test mode):*
```
Cannot send bulk emails to 25 users.
Registration is not open for CyberX 2025.
Enable 'Registration Open' in event settings to send bulk emails.
```

### 2. VPN Request Protection

VPN requests check the active event status:

```python
# For regular participants
if not vpn_available:
    raise Exception("VPN not available yet")

# For sponsors in test mode
if test_mode and is_sponsor:
    allow_vpn_request()  # Works even if vpn_available=false
```

### 3. Manual Override (Small Groups)

Sending to **fewer than 10 users** bypasses bulk protections:
- Allows testing with small groups
- Manual targeted communications
- Individual follow-ups

---

## Testing with Sponsors

### Recommended Testing Flow

**Week 1: Event Setup & Sponsor Testing**
```bash
# Day 1: Create and activate event
is_active = true
registration_open = false  # ← Protection ON
test_mode = false
vpn_available = false

# Day 2: Enable test mode, invite 5-10 sponsors manually
test_mode = true  # ← Sponsors can now test

# Days 3-7: Sponsor testing
- Sponsors request VPNs
- Verify Keycloak sync
- Test email workflows
- Validate portal features
```

**Week 2: General Registration**
```bash
# Day 8: Open registration to all
registration_open = true  # ← NOW mass emails can go

# Day 9-14: Send invitations
- Bulk invite all participants
- Confirmation emails go out
- Track responses
```

**Week 3: VPN Access**
```bash
# Day 15: Enable VPN (closer to event)
vpn_available = true  # ← Everyone can request VPNs
```

### Testing Checklist

#### Sponsor Test Mode
- [ ] Event is active (`is_active = true`)
- [ ] Test mode enabled (`test_mode = true`)
- [ ] Registration still closed (`registration_open = false`)
- [ ] Manually invite 5-10 sponsors
- [ ] Sponsors can log in to portal
- [ ] Sponsors see "Test Mode" badge
- [ ] Sponsors can request VPN credentials
- [ ] VPN configs download successfully
- [ ] Keycloak sync creates accounts
- [ ] Email workflows trigger correctly

#### Pre-Launch Validation
- [ ] Disable test mode (`test_mode = false`)
- [ ] Verify sponsors can no longer request VPNs
- [ ] Prepare bulk invite list
- [ ] Test email templates with preview
- [ ] Verify email content is correct

#### Launch Day
- [ ] Open registration (`registration_open = true`)
- [ ] Send mass invitation emails
- [ ] Monitor email delivery/open rates
- [ ] Track confirmation responses

#### VPN Availability
- [ ] Enable VPN (`vpn_available = true`)
- [ ] Verify all confirmed users can request
- [ ] Monitor VPN pool availability
- [ ] Test VPN connections

---

## Common Scenarios

### Scenario 1: Testing Before General Availability (Safest Approach)
**Goal:** Test VPN and email workflows with sponsors only, avoiding any accidental emails.

```
1. Create event → is_active=false, test_mode=false, registration_open=false
2. Enable test mode FIRST → test_mode=true (while is_active=false)
   → No workflow triggers (event not active)
3. Activate event → is_active=true (test_mode already enabled)
   → Workflow triggers automatically
   → Sponsors receive invitation emails only
4. Sponsors test VPN access and workflows
5. When ready, open registration → registration_open=true
   → Workflow triggers
   → All invitees + sponsors receive invitations
```

**✓ Result:** Sponsors automatically invited and tested everything, no accidental mass emails.
**✓ Benefit:** No manual sponsor invitations needed - automated workflow handles it safely.

---

### Scenario 2: Activating Event Without Inviting Anyone Yet
**Goal:** Activate event for system but delay invitations.

```
1. Create event → All flags false
2. Activate event → is_active=true, registration_open=false
3. Configure email templates and workflows
4. Test with small sponsor group (optional)
5. When ready, open registration → registration_open=true
6. Send invitations
```

**✓ Result:** Event is active for system processes but invitations are manual.

---

### Scenario 3: Separate VPN Availability from Invitations
**Goal:** Invite everyone early, enable VPN later.

```
1. Activate event → is_active=true
2. Open registration → registration_open=true
3. Send mass invitations
4. Users confirm participation
5. 2 weeks before event, enable VPN → vpn_available=true
6. Users request VPN credentials
```

**✓ Result:** Invitations go out early, VPN access controlled separately.

---

### Scenario 4: Emergency: I Accidentally Enabled Something!

**If you accidentally opened registration:**
```
1. Go to Events table
2. Click Registration toggle to close it (turns gray)
3. System will block bulk operations immediately
4. Manually send corrective emails if needed (to <10 users at a time)
```

**If you accidentally enabled VPN:**
```
1. Go to Events table
2. Click VPN toggle to disable it (turns gray)
3. Users will see "VPN not available yet" message
4. No VPNs can be requested until re-enabled
```

**If test emails were sent:**
```
- Test mode emails only go to sponsors
- Check Email Center → History to see who received emails
- Send follow-up clarification if needed
```

---

## Troubleshooting

### "Cannot send bulk emails" Error

**Error:**
```
Cannot send bulk emails to 25 users.
Registration is not open for CyberX 2025.
```

**Solution:**
1. Go to Events table
2. Check the "Registration" column
3. Click to toggle "Open" (green)
4. Retry bulk email operation

**OR** if testing with sponsors:
1. Ensure `test_mode = true`
2. Verify all recipients are sponsors
3. Retry operation

---

### "VPN access not yet available" Message

**Symptom:** Users see warning on portal, cannot request VPNs.

**Solution:**
1. Go to Events table
2. Check "VPN" column
3. Click shield icon to enable (turns green)

**OR** for sponsor testing:
1. Enable test mode (⚡ icon)
2. Verify user has sponsor role
3. Refresh portal page

---

### Test Mode Not Working

**Symptom:** Sponsors cannot request VPNs in test mode.

**Checklist:**
- [ ] Event is active (`is_active = true`)
- [ ] Test mode is enabled (⚡ icon is yellow)
- [ ] User has sponsor role (check in Users table)
- [ ] User is registered for the event
- [ ] Browser cache cleared / hard refresh

---

### Email Workflows Not Triggering

**Symptom:** Expected emails not sending.

**Checklist:**
- [ ] Event is active
- [ ] Email template is active
- [ ] Workflow is enabled
- [ ] If bulk send: registration_open=true OR (test_mode=true AND sponsors only)
- [ ] Check Email Center → History for sent status

---

## Best Practices

### ✅ Do's
- **Always test with sponsors first** before general availability
- **Enable test mode BEFORE activating** the event (safest order)
- **Verify email templates** with preview before bulk sending
- **Gradually enable features** (test mode → activate → register → VPN)
- **Monitor email analytics** after bulk sends
- **Document your timeline** for each event phase
- **Use TESTING_EMAIL_GUIDE.md** for sandbox mode and email override during development

### ❌ Don'ts
- **Don't activate and open registration simultaneously** on first event
- **Don't enable all flags at once** without testing
- **Don't send bulk emails without verifying content**
- **Don't enable VPN too early** (risk of pool exhaustion)
- **Don't skip sponsor testing phase**

---

## Quick Reference

### Status Flag Combinations

| Scenario | is_active | registration_open | test_mode | vpn_available | Who Has Access |
|----------|-----------|-------------------|-----------|---------------|----------------|
| Just created | ❌ | ❌ | ❌ | ❌ | Nobody |
| Activated, preparing | ✅ | ❌ | ❌ | ❌ | Nobody |
| Sponsor testing | ✅ | ❌ | ✅ | ❌ | Sponsors only |
| Invitations sent | ✅ | ✅ | ❌ | ❌ | Nobody (VPN) |
| Event ready | ✅ | ✅ | ❌ | ✅ | All confirmed users |

### Email Protection Matrix

**Priority: Test Mode ALWAYS Restricts (Regardless of Registration Open)**

| Recipients | test_mode | all_sponsors | registration_open | Can Send? | Reason |
|------------|-----------|--------------|-------------------|-----------|---------|
| < 10 users | Any | Any | Any | ✅ Yes | Small groups bypass bulk protection |
| ≥ 10 users | ✅ | ✅ | Any | ✅ Yes | Test mode allows sponsors only |
| ≥ 10 users | ✅ | ❌ | Any* | ❌ **No** | **Test mode blocks non-sponsors (registration_open ignored)** |
| ≥ 10 users | ❌ | Any | ✅ | ✅ Yes | Not in test mode, registration open |
| ≥ 10 users | ❌ | Any | ❌ | ❌ No | Not in test mode, registration closed |

*Key Change: When test_mode=True, registration_open is **ignored** - only sponsors can receive emails.*

---

### Test Mode Always Restricts - Examples

**Important: Test mode is your safety switch. When enabled, it ALWAYS restricts emails to sponsors only, regardless of other settings.**

#### Example 1: Test Mode + Registration Open
```yaml
Event Status:
  test_mode: true
  registration_open: true  ← Ignored in test mode

Attempt: Send bulk email to 50 users (40 invitees + 10 sponsors)
Result: ❌ BLOCKED
Reason: "Test mode restricts all emails to sponsors only"
Solution: Either disable test_mode OR send only to the 10 sponsors
```

#### Example 2: Test Mode + Registration Closed
```yaml
Event Status:
  test_mode: true
  registration_open: false

Attempt: Send bulk email to 10 sponsors
Result: ✅ ALLOWED
Reason: All recipients are sponsors, test mode permits this
```

#### Example 3: Test Mode Off + Registration Open
```yaml
Event Status:
  test_mode: false
  registration_open: true

Attempt: Send bulk email to 100 users (any mix)
Result: ✅ ALLOWED
Reason: Not in test mode, registration is open
```

#### Example 4: Automatic Workflows in Test Mode
```yaml
Event Status:
  test_mode: true

Trigger: User confirms participation
User Role: Regular invitee (not a sponsor)
Result: ❌ Workflow SKIPPED for this user
        📝 Logged: "Skipping workflow trigger - test mode enabled and user not sponsor"

User Role: Sponsor
Result: ✅ Workflow triggers normally
        ✉️  Confirmation email sent
```

**Key Takeaway:** Test mode acts as a master switch - when ON, only sponsors can receive emails through ANY method (bulk sends, single sends, automated workflows). This prevents accidental emails during testing.

---

## Automated Invitation Workflow

### Overview

The system automatically triggers invitation emails when certain event status changes occur. This ensures invitations go out at the right time without manual intervention.

### Trigger Conditions

The invitation workflow triggers **automatically** when any of these conditions are met:

| Trigger | Condition | Requires Active Event? | Who Gets Invited |
|---------|-----------|----------------------|------------------|
| **Event Activation** | `is_active` changes False → True | No (becomes active) | Invitees + Sponsors (if `registration_open=True`) |
| **Test Mode Enabled** | `test_mode` changes False → True | **Yes** | Sponsors only |
| **Test Mode Disabled** | `test_mode` changes True → False | **Yes** (and `registration_open=True`) | Invitees + Sponsors |
| **Registration Opened** | `registration_open` changes False → True | **Yes** | Invitees + Sponsors |

### Enforcement Rules

**When the workflow runs**, it checks:

1. **Test Mode ALWAYS RESTRICTS** (`test_mode=True`):
   - Workflows **only trigger for sponsors** (regardless of `registration_open`)
   - Non-sponsors are **completely skipped** - workflow doesn't queue emails for them
   - Logged: "Skipping workflow trigger for user X - test mode is enabled and user is not a sponsor"
   - This prevents accidental automated emails during testing

2. **Production Mode** (`test_mode=False`):
   - If `registration_open=False` → **Skip sending** (logs message)
   - If `registration_open=True` → Send to all invitees + sponsors with `confirmed=UNKNOWN`

### Example Scenarios

#### Scenario A: Event Becomes Active
```yaml
Action: Create event with is_active=True, registration_open=True
Result: ✅ Invitation workflow triggers immediately
        ✅ Sends to all invitees + sponsors with confirmed=UNKNOWN
        ⏱️  Emails queued 30 seconds after activation
```

#### Scenario B: Event Active, Registration Closed
```yaml
Action: Create event with is_active=True, registration_open=False
Result: ✅ Invitation workflow triggers
        ❌ No emails sent (registration closed)
        📝 Logs: "Registration is closed - skipping invitation emails"
```

#### Scenario C: Registration Opens Later
```yaml
Step 1: Event created with is_active=True, registration_open=False
        → No invites sent

Step 2: Update event to registration_open=True
        → ✅ Invitation workflow triggers
        → ✅ Sends to all invitees + sponsors
        → ⏱️  Emails queued 30 seconds later
```

#### Scenario D: Test Mode Enabled
```yaml
Action: Update event to test_mode=True (while is_active=True)
Result: ✅ Invitation workflow triggers
        ✅ Sends to sponsors only (regardless of registration_open)
        ❌ Invitees excluded
```

#### Scenario E: Toggling Flags While Inactive
```yaml
Step 1: Event with is_active=False, registration_open=False
Step 2: Update to registration_open=True
        → ❌ No workflow trigger (event not active)

Step 3: Update to is_active=True
        → ✅ Invitation workflow triggers
        → ✅ Sends to invitees + sponsors (registration is open)
```

#### Scenario F: Test Mode + Registration Closed
```yaml
Status: is_active=True, registration_open=False, test_mode=True
Action: Toggle test_mode False → True
Result: ✅ Invitation workflow triggers
        ✅ Sends to sponsors only (test mode bypasses registration check)
        📝 Sponsors can test even when registration closed
```

#### Scenario G: Safe Setup - Test Mode Before Activation (Recommended!)
```yaml
Step 1: Event created with is_active=False, test_mode=False
        → No triggers possible

Step 2: Enable test_mode=True (while is_active=False)
        → entered_test_mode=True BUT event.is_active=False
        → Trigger check: (False or (True and False) or False) = False
        → ❌ NO WORKFLOW TRIGGER (event not active yet)
        → ✅ SAFE - Nothing sent

Step 3: Activate event (is_active=True, test_mode already True)
        → became_active=True
        → Trigger check: (True or ...) = True
        → ✅ Triggers with test_mode=True
        → ✅ Sends to SPONSORS ONLY
        → ❌ Invitees protected

Step 4: When ready, open registration (registration_open=True)
        → registration_opened=True AND event.is_active=True
        → ✅ Triggers workflow
        → ✅ Sends to ALL invitees + sponsors
```

**Why This is Safest:**
- Test mode enabled while inactive = no triggers
- Activating with test mode already on = sponsors only
- Prevents accidental invites to everyone
- Recommended for first-time event setup

#### Scenario H: Test Mode Disabled
```yaml
Status: is_active=True, test_mode=True, registration_open=True
Action: Toggle test_mode True → False (disable test mode)
Result: ✅ Invitation workflow triggers
        ✅ Sends to ALL invitees + sponsors with confirmed=UNKNOWN
        📝 Only users who have NOT been sent invitations before

Timeline:
  T+0s:  test_mode toggled False
  T+0s:  exited_test_mode=True detected
  T+0s:  Scheduled invitation job for 30 seconds
  T+30s: Job executes and queues invitations for eligible invitees

Important Notes:
  - Duplicate protection: Users with confirmation_sent_at NOT NULL are excluded
  - This ensures invitees who already received invitations in test mode won't get duplicates
  - Sponsors who already received test invitations also won't get duplicates
```

### Workflow Timeline

```
Event Status Change
        ↓
Trigger Detected (became_active OR entered_test_mode OR exited_test_mode OR registration_opened)
        ↓
Check: Event is_active? (except for became_active which sets it)
        ↓
Check: registration_open? (only for exited_test_mode)
        ↓
Schedule job for 30 seconds later
        ↓
Job executes:
  ├─ Load event from database
  ├─ Check registration_open (unless test_mode)
  ├─ Query users with confirmed=UNKNOWN AND confirmation_sent_at IS NULL
  ├─ Generate confirmation codes
  ├─ Queue invitation emails
  └─ Process email queue (separate background job)
```

### Preventing Accidental Emails

To prevent the workflow from triggering during event setup:

**✅ Safest Setup Sequence (Enable Test Mode FIRST):**
```yaml
1. Create event with ALL flags = False
   → is_active=False (no triggers possible)

2. Configure event details, templates, etc.
   → Still inactive (safe)

3. Enable test mode BEFORE activating:
   → Set test_mode=True (while is_active=False)
   → ❌ NO TRIGGER (event not active)
   → ✅ SAFE - Ready for activation

4. Activate event:
   → Set is_active=True (test_mode already True)
   → ✅ Triggers workflow, sends to SPONSORS ONLY
   → Invitees protected

5. When ready for general registration:
   → Set registration_open=True
   → Triggers workflow, sends to all invitees + sponsors
```

**Why Enable Test Mode First?**
- Toggling test mode while inactive doesn't trigger workflows
- Activating with test mode already enabled = sponsors only
- Prevents any chance of accidental mass emails
- Safest approach for first-time event setup

**❌ What NOT to Do:**
```yaml
# Bad: Create event with is_active=True, registration_open=True
→ Immediately triggers invitations to everyone!
→ No chance to review or test first
```

### Checking Workflow Status

**View Scheduled Jobs:**
```bash
GET /api/admin/scheduler/jobs
```

**View Email Queue:**
```bash
GET /api/admin/email-queue?status=pending
```

**Check Logs:**
```
Look for: "Triggering invitation email workflow for event..."
And: "Successfully queued X invitation emails"
```

### Manual Override

If you need to prevent automated invitations:

1. **Before Event Activation:**
   - Create event with `is_active=False`
   - Set up everything first
   - Activate when ready

2. **After Event Active:**
   - Keep `registration_open=False`
   - Manually invite users (< 10 at a time bypasses bulk protection)
   - Open registration when ready for mass invitations

3. **Emergency Stop:**
   - If workflow triggered accidentally, clear email queue:
   ```sql
   DELETE FROM email_queue WHERE status = 'pending';
   ```

### Testing Safeguards

Use [TESTING_EMAIL_GUIDE.md](TESTING_EMAIL_GUIDE.md) for safe email testing:

- **Sandbox Mode**: Emails validated but not delivered
- **Email Override**: All emails redirected to test address

These work with the automated workflow to prevent accidental sends during testing.

---

## Support

For issues or questions:
- Check the [main README](README.md) for setup instructions
- Review [SETUP.md](SETUP.md) for installation steps
- Check [TESTING_EMAIL_GUIDE.md](TESTING_EMAIL_GUIDE.md) for safe email testing
- Check Email Center → History for sent email status
- Check Audit Logs for detailed operation history

---

**Last Updated:** 2026-02-01
