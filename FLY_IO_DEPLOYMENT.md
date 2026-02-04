# Deploy to Fly.io - Scale-to-Zero Architecture

Perfect for **intermittent/sporadic usage** - only pay when app is running!

**Ideal For:** Applications used a few times per year during events
**Cost:** ~$5-10 per event week, ~$20-40/year total
**Cold Start:** 1-2 seconds

---

## Why Fly.io for Sporadic Usage?

✅ **Scale to zero** - App sleeps when not used
✅ **Instant wake** - 1-2 second cold start (acceptable!)
✅ **Pay per second** - Only charged when running
✅ **Free tier** - Covers small databases
✅ **Global edge** - Fast VPN config downloads anywhere
✅ **No manual start/stop** - Automatic!

---

## Cost Breakdown

### Free Tier Includes
```
3 shared-cpu-1x VMs (256MB RAM each)
3GB persistent storage (for PostgreSQL)
160GB outbound bandwidth/month
```

### Your Expected Costs

**During event week (168 hours running):**
```
Web app (1 VM, always awake):     $5-8/week
PostgreSQL (1 VM, always awake):  Included in free tier
Redis (optional):                 $2/week
                                  ──────────
Total per event:                  ~$7-10/week
```

**Between events (app sleeping):**
```
Storage (persistent volumes):     $0.15/GB/month
Database storage (1GB):           ~$0.15/month
Total idle cost:                  ~$0.15/month
```

**Annual cost (4 events):**
```
4 events × $10:                   $40/year
Idle storage × 11 months:         $2/year
                                  ──────────
Total annual cost:                ~$42/year

Compare to always-on Render:     $288/year
SAVINGS:                          $246/year (85% less!)
```

---

## Architecture: Scale-to-Zero

```
User Request
    ↓
Fly.io Proxy (always awake)
    ↓
App VM (sleeping) ──→ Wakes in 1-2 seconds
    ↓
Handles request
    ↓
After 5 minutes idle ──→ Sleeps automatically
```

**Key Features:**
- First request: ~2 second delay (cold start)
- Subsequent requests: Normal speed
- Auto-sleep: After 5 minutes of no traffic
- Auto-wake: On next request
- Database: Can stay awake or sleep too

---

## Quick Deploy

### Install Fly CLI

```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Windows
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"

# Verify
flyctl version
```

### Authenticate

```bash
flyctl auth login
# Opens browser to authenticate
```

### Initialize Fly App

```bash
cd cyberx-event-mgmt

# Launch wizard (auto-detects Python)
flyctl launch

# Answer prompts:
# App name: cyberx-event-mgmt
# Region: Choose closest to users (e.g., sjc for San Francisco)
# PostgreSQL: Yes, create development database
# Redis: Optional (say no to save costs)
# Deploy now: No (we need to configure first)
```

This creates `fly.toml` configuration file.

---

## Configuration

### Edit fly.toml

```toml
app = "cyberx-event-mgmt"
primary_region = "sjc"  # San Francisco (or your preferred region)

[build]
  dockerfile = "backend/Dockerfile"

[env]
  PORT = "8000"
  PYTHON_VERSION = "3.11"
  DEBUG = "false"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true    # Enable scale-to-zero
  auto_start_machines = true   # Auto-wake on request
  min_machines_running = 0     # Can scale to zero
  processes = ["app"]

  [[http_service.checks]]
    grace_period = "10s"
    interval = "30s"
    method = "GET"
    timeout = "5s"
    path = "/health"

[vm]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 256

[[statics]]
  guest_path = "/app/static"
  url_prefix = "/static"
```

### Create PostgreSQL Database

```bash
# Create Postgres cluster (free tier)
flyctl postgres create \
  --name cyberx-postgres \
  --vm-size shared-cpu-1x \
  --volume-size 1 \
  --region sjc

# Attach to app
flyctl postgres attach cyberx-postgres -a cyberx-event-mgmt

# This automatically sets DATABASE_URL environment variable
```

### Set Environment Variables

```bash
# Set secrets
flyctl secrets set \
  SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
  CSRF_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
  ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  SENDGRID_API_KEY="SG.your-api-key-here" \
  SENDGRID_FROM_EMAIL="noreply@yourdomain.com" \
  SENDGRID_FROM_NAME="CyberX Red Team" \
  VPN_SERVER_PUBLIC_KEY="your-wireguard-public-key" \
  VPN_SERVER_ENDPOINT="vpn.yourdomain.com:51820" \
  VPN_DNS_SERVERS="10.20.200.1" \
  VPN_ALLOWED_IPS="10.0.0.0/8,fd00:a::/32" \
  FRONTEND_URL="https://cyberx-event-mgmt.fly.dev" \
  ALLOWED_HOSTS="cyberx-event-mgmt.fly.dev" \
  SESSION_EXPIRY_HOURS="24" \
  BULK_EMAIL_INTERVAL_MINUTES="45"
```

---

## Deploy

### Initial Deployment

```bash
# Deploy app
flyctl deploy

# Watch deployment logs
flyctl logs

# Check status
flyctl status

# Open in browser
flyctl open
```

### Run Database Migrations

```bash
# SSH into app
flyctl ssh console

# Run migrations
cd backend
alembic upgrade head

# Create admin user
python scripts/setup_clean_db.py \
  --admin-email admin@yourdomain.com \
  --admin-password your-secure-password \
  --no-prompt

# Exit
exit
```

---

## Scale-to-Zero Configuration

### Configure Auto-Sleep

```bash
# Ensure auto-sleep is enabled
flyctl scale count 0 --max-per-region 1

# This means:
# - Can scale to 0 machines (sleep)
# - Max 1 machine per region when awake
# - Auto-wake on first request
```

### Test Cold Start

```bash
# Stop all machines manually
flyctl machine stop --all

# Wait 30 seconds

# Visit your app URL
curl https://cyberx-event-mgmt.fly.dev/health

# First request: ~2 second delay (waking up)
# Subsequent requests: normal speed
```

### Keep Database Awake (Recommended)

Your PostgreSQL should stay awake to avoid database cold starts:

```bash
# Check Postgres settings
flyctl postgres config show -a cyberx-postgres

# Keep Postgres always-on (recommended)
# Postgres VM is in free tier, no extra cost
```

---

## Managing Events

### Before Event Starts

**Option A: Do Nothing!**
- App auto-wakes on first participant visit
- 2-second delay is acceptable for first load
- Subsequent loads are instant

**Option B: Manually Wake (if you want zero delay)**

```bash
# Wake app 30 minutes before event
flyctl machine start --all

# App will be warm for all participants
```

### During Event

- App stays awake as long as traffic continues
- Auto-scales if traffic increases
- No manual intervention needed

### After Event

**Option A: Let it auto-sleep**
- After 5 minutes of no traffic, auto-sleeps
- Zero effort, zero cost

**Option B: Manually stop (immediate)**

```bash
# Stop all machines immediately
flyctl machine stop --all

# Stops billing instantly
```

---

## Cost Optimization Tips

### 1. **Smaller VM Size**

Default is fine, but you can go smaller:

```toml
[vm]
  memory_mb = 256  # Enough for 100 users
  # Can go as low as 256MB
```

### 2. **Database Storage**

Start small, grow as needed:

```bash
# Create with 1GB (free tier)
flyctl postgres create --volume-size 1

# Expand later if needed
flyctl volumes extend <volume-id> --size 3
```

### 3. **No Redis**

For 100 sporadic users, skip Redis:
- Use PostgreSQL for sessions
- Save ~$2/event
- Minimal performance impact

### 4. **Manual Wake Only During Events**

If events are scheduled:

```bash
# Create shell script: wake_app.sh
#!/bin/bash
flyctl machine start --all -a cyberx-event-mgmt
echo "✅ App is awake!"

# Run this 1 hour before event starts
./wake_app.sh
```

### 5. **Monitor Costs**

```bash
# Check current usage
flyctl dashboard

# View billing
flyctl billing

# Set spending limit
flyctl orgs billing-limits set 10  # $10/month limit
```

---

## Monitoring

### Check App Status

```bash
# Is app running or sleeping?
flyctl status

# View logs (real-time)
flyctl logs

# Check metrics
flyctl dashboard
```

### Health Checks

```bash
# Test endpoint
curl https://cyberx-event-mgmt.fly.dev/health

# View health check status
flyctl checks list
```

### Billing Dashboard

1. Go to https://fly.io/dashboard
2. Click **Billing**
3. See real-time usage and costs

---

## Comparison: Always-On vs Scale-to-Zero

### Always-On (Render)

```
Cost: $32/month × 12 = $384/year

Pros:
✅ Zero cold starts
✅ Always instant response

Cons:
❌ Pay for 11 months of idle time
❌ Wasteful for sporadic usage
```

### Scale-to-Zero (Fly.io)

```
Cost: ~$10/event × 4 = $40/year

Pros:
✅ 90% cost savings
✅ Pay only when used
✅ Automatic wake/sleep
✅ Good for intermittent use

Cons:
⚠️ 2-second cold start (first request only)
⚠️ Need to plan for wake time
```

---

## Alternative: Manual Start/Stop on Render

If you prefer Render's simplicity, you can manually control it:

### Suspend Render Service

```bash
# Via Render Dashboard:
1. Go to your web service
2. Click "Suspend"
3. Service stops, billing pauses

# Cannot be automated (manual only)
```

### Resume Render Service

```bash
# Via Dashboard:
1. Click "Resume"
2. Wait ~2-3 minutes for startup
3. Service active again

# Plan ahead: Start before event begins
```

**Render Cost with Manual Control:**
```
Active 1 month per year:
Web: $7 × 1 = $7/year
Database: $7 × 12 = $84/year (can't stop)
Redis: $10 × 12 = $120/year (can't stop)
                 ───────
Total:           $211/year

Issue: Can only suspend web app, not database/Redis
Still pay for database year-round
```

**Verdict:** Fly.io scale-to-zero is much better for sporadic use!

---

## Alternative: Supabase Pause (Free Tier Only)

Supabase **Free** tier can pause:

```bash
# Supabase Free auto-pauses after 1 week idle
# Wakes automatically on first connection
# Cold start: ~5-10 seconds

Cost: $0/year for database!
```

But Supabase **Pro** cannot pause (always-on).

**Best combo for intermittent use:**
```
Fly.io App (scale-to-zero):    $40/year
Supabase Free (auto-pause):    $0/year
                               ─────────
Total:                         $40/year

vs Render + Supabase always-on: $384/year
SAVINGS:                        $344/year (90%!)
```

---

## Decision Matrix

| Usage Pattern | Best Option | Annual Cost |
|---------------|-------------|-------------|
| **Always-on** | Render + Supabase Pro | $384/year |
| **4 events/year** | **Fly.io + Supabase Free** | **$40/year** |
| **Monthly usage** | Render + Supabase Pro | $384/year |
| **Weekly usage** | Render + Supabase Pro | $384/year |

---

## Recommended Architecture for Your Use Case

**You mentioned:** 100 users, very sporadic during events

**Perfect setup:**
```
Application:    Fly.io (scale-to-zero)
Database:       Supabase Free (auto-pause)
Redis:          Skip it (not needed)
                ───────────────────────
Total:          ~$40/year

During event:   App auto-wakes in 2 seconds
Between events: Everything sleeps, near-zero cost
```

---

## Cold Start Acceptable?

For your use case, 2-second cold start is fine because:

✅ **First participant** waits 2 seconds (acceptable)
✅ **All other participants** get instant response
✅ **VPN config downloads** are fast after first load
✅ **Saves 90%** on hosting costs
✅ **No manual management** needed

**Not acceptable if:**
- Need instant 24/7 uptime
- Can't tolerate any delay
- Have continuous monitoring/alerts

---

## Next Steps

### For Intermittent Usage (Recommended)

1. Deploy to Fly.io (follow guide above)
2. Use Supabase Free for database
3. Enable scale-to-zero
4. Test cold start time
5. Enjoy ~90% cost savings!

### For Always-On (If Needed)

1. Deploy to Render (existing guide)
2. Use Supabase Pro for best backups
3. Keep running 24/7
4. Better for continuous usage

---

## Example: 4 Events Per Year

```
Event schedule:
- March: 1 week
- June: 1 week
- September: 1 week
- December: 1 week

Fly.io costs:
- 4 weeks active: 4 × $10 = $40
- 48 weeks idle: 48 × $0.15 = $7
                           ─────
Total:                     $47/year

Render (always-on):        $384/year

SAVINGS:                   $337/year (88% less!)
```

---

**Recommendation:** Since you only need the app during events, **use Fly.io with scale-to-zero** for massive cost savings!

Let me know if you want help setting up Fly.io deployment.
