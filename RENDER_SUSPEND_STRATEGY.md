# Render + Supabase Pro - Suspend Strategy Guide

Cost-optimized deployment using Render's manual suspend feature to reduce costs between events.

**Your Setup:**
- **Render Web Service** - Suspend between events ($7/month only when active)
- **Supabase Pro Database** - Always-on for data persistence ($25/month)
- **No Redis** - Not needed for single instance

**Annual Cost:** ~$307-314/year (vs $384/year always-on)
**Savings:** ~$70-77/year with minimal management

---

## 💰 Cost Breakdown

### Per Event (1 week)
```
Supabase Pro:              $25/month (prorated ~$6/week)
Render Web:                $7/month (prorated ~$2/week)
                           ──────────────────────────────
Total per event week:      ~$8/week
```

### Annual (4 events, 1 week each)
```
Supabase Pro (12 months):  $25 × 12 = $300/year
Render Web (1-2 months):   $7 × 1.5 = $11/year
                           ──────────────────────────────
Total annual:              ~$311/year

Compare to always-on:      $384/year (Redis + always-on web)
Savings:                   ~$73/year (19% less)
```

**Why not more savings?**
- Supabase Pro can't pause ($300/year regardless)
- BUT: You get PITR backups (worth it!)
- Render Web is only $7-14/year (when active)

---

## 🎯 Why This Setup Works

### Supabase Pro (Always-On) - $300/year
**Cannot pause, but that's OK because:**
- ✅ **Data persists** - Database always accessible
- ✅ **PITR backups** - Restore to any second (last 7 days)
- ✅ **No cold starts** - Database always warm
- ✅ **8GB storage** - Plenty of room to grow
- ✅ **Professional-grade** - Best backup solution

### Render Web (Suspend Between Events) - $11/year
**Can suspend manually:**
- ✅ **Pay only when running** - Billing pauses when suspended
- ✅ **Quick resume** - 2-3 minutes to wake up
- ✅ **Same instance** - No data migration needed
- ✅ **Simple management** - Just click suspend/resume
- ⚠️ **Manual process** - Need to remember to suspend/resume

### No Redis - $0/year
**Not needed because:**
- ✅ **Sessions in PostgreSQL** - Already implemented in your app
- ✅ **Single instance** - No distributed rate limiting needed
- ✅ **In-memory caching** - Sufficient for 100 users
- ✅ **Save $120/year** - Redis not worth the cost

---

## 🚀 Initial Setup

### Step 1: Create Supabase Pro Project

1. **Sign up at [supabase.com](https://supabase.com)**

2. **Create new project**
   - **Name:** `cyberx-events`
   - **Password:** Generate strong password (save it!)
   - **Region:** `us-west-1` (or closest to you)
   - **Pricing Plan:** **Pro - $25/month**
   - Click **Create Project**

3. **Get connection string**
   - Go to **Project Settings** → **Database**
   - Copy **Connection string** (URI)
   - Should look like:
     ```
     postgresql://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
     ```

4. **Convert for FastAPI (asyncpg)**
   ```
   Original: postgresql://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
   For app:  postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres

   Just add "+asyncpg" after "postgresql"!
   ```

### Step 2: Initialize Database

Run migrations on Supabase:

```bash
cd backend

# Set DATABASE_URL
export DATABASE_URL="postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres"

# Run migrations
alembic upgrade head

# Create admin user
python scripts/setup_clean_db.py \
    --admin-email admin@yourdomain.com \
    --admin-password your-secure-password \
    --no-prompt \
    --seed-data
```

### Step 3: Deploy to Render

#### Option A: Using render-supabase.yaml

1. **Push config to repo:**
   ```bash
   git add render-supabase.yaml
   git commit -m "Add Render + Supabase config"
   git push origin main
   ```

2. **Create web service on Render:**
   - Go to [render.com](https://render.com)
   - Click **New** → **Web Service**
   - Connect your GitHub repo
   - Render will detect `render-supabase.yaml`

3. **Add required environment variables:**
   ```
   DATABASE_URL=postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
   SENDGRID_API_KEY=SG.your-api-key
   SENDGRID_FROM_EMAIL=noreply@yourdomain.com
   VPN_SERVER_PUBLIC_KEY=your-key
   VPN_SERVER_ENDPOINT=vpn.yourdomain.com:51820
   ```

4. **Deploy:**
   - Click **Create Web Service**
   - Wait 5-10 minutes for first deploy

#### Option B: Manual Setup

Follow [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) but:
- **Skip** PostgreSQL creation
- **Skip** Redis creation
- **Add** Supabase DATABASE_URL manually

---

## 📅 Event Management Workflow

### Before Event (24-48 hours ahead)

#### 1. Resume Render Service

**Via Render Dashboard:**
1. Go to https://dashboard.render.com
2. Select `cyberx-event-mgmt` service
3. Click **Resume** button
4. Wait 2-3 minutes for service to start
5. Check health: Visit `https://cyberx-event-mgmt.onrender.com/health`

**What happens:**
- Billing resumes immediately
- Service starts up in 2-3 minutes
- Connects to Supabase (already awake)
- All data intact (nothing lost)

#### 2. Verify Everything Works

```bash
# Test health endpoint
curl https://cyberx-event-mgmt.onrender.com/health

# Test admin login
curl -X POST https://cyberx-event-mgmt.onrender.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin@yourdomain.com", "password": "your-password"}'

# Test API docs
open https://cyberx-event-mgmt.onrender.com/api/docs
```

#### 3. Prepare for Event

- Import any new participants
- Update VPN configs if needed
- Test email sending
- Verify VPN config downloads work

### During Event (1 week)

**No action needed!**
- Service runs continuously
- Billing: ~$7 for the month
- Monitor via Render dashboard
- Check logs if needed

### After Event (within 24 hours)

#### 1. Verify Event Complete

- Confirm all participants have VPN configs
- Check audit logs for any issues
- Export any reports needed

#### 2. Suspend Render Service

**Via Render Dashboard:**
1. Go to https://dashboard.render.com
2. Select `cyberx-event-mgmt` service
3. Click **Suspend** button (in Settings or top-right)
4. Confirm suspension

**What happens:**
- Service stops immediately
- Billing pauses instantly
- Data remains in Supabase (safe!)
- Can resume anytime

#### 3. Confirm Suspension

Check billing dashboard:
- Web service shows "Suspended"
- No charges while suspended
- Only Supabase Pro charges continue ($25/month)

---

## 🔄 Resume/Suspend Checklist

### Pre-Event Checklist (Resume)

```
□ 48 hours before event:
  □ Resume Render service
  □ Wait 3 minutes for startup
  □ Test health endpoint
  □ Test admin login
  □ Verify database connection

□ 24 hours before event:
  □ Import participants
  □ Test email sending
  □ Test VPN config downloads
  □ Send welcome emails

□ 1 hour before event:
  □ Final health check
  □ Monitor logs
  □ Have admin credentials ready
```

### Post-Event Checklist (Suspend)

```
□ Event ends:
  □ Wait 24 hours (for late downloads)
  □ Export final reports
  □ Check audit logs

□ 24 hours after event:
  □ Verify no pending operations
  □ Suspend Render service
  □ Confirm suspension in dashboard
  □ Check billing paused

□ Optional:
  □ Backup database (extra safety)
  □ Document any issues
  □ Update participant records
```

---

## 📊 Cost Tracking

### Monthly Billing Expectations

**Months with events (1-2 per year):**
```
Supabase Pro:              $25
Render Web:                $7
                           ───
Total:                     $32/month
```

**Months without events (10-11 per year):**
```
Supabase Pro:              $25
Render Web (suspended):    $0
                           ───
Total:                     $25/month
```

### Annual Billing

```
Supabase Pro (12 months):  $25 × 12 = $300
Render Web (1.5 months):   $7 × 1.5 = $11
                           ──────────────
Total:                     $311/year
```

**Compared to:**
```
Always-on (no Redis):      $25 × 12 + $7 × 12 = $384/year
Savings:                   $73/year (19% less)

Always-on (with Redis):    $25 × 12 + $7 × 12 + $10 × 12 = $504/year
Savings:                   $193/year (38% less)
```

---

## ⚠️ Important Notes

### About Supabase Pro

**Cannot pause, but you get:**
- ✅ Point-in-Time Recovery (any second in last 7 days)
- ✅ 8GB storage (vs 500MB free tier)
- ✅ Better performance
- ✅ Professional backups
- ✅ Download backups directly

**This is worth the $300/year for:**
- Event management with real participants
- VPN credential security
- Compliance requirements
- Peace of mind

### About Render Suspension

**What persists:**
- ✅ All code and configuration
- ✅ Environment variables
- ✅ Custom domain settings
- ✅ SSL certificates

**What doesn't persist:**
- ❌ Running processes (obviously)
- ❌ In-memory data (lost on suspend)
- ⚠️ Logs older than 7 days (Render limitation)

**Resume time:**
- 2-3 minutes typical
- Same as cold start
- No data migration needed

---

## 🔍 Monitoring

### Check Service Status

**Via Dashboard:**
- https://dashboard.render.com
- Shows "Running" or "Suspended"
- View logs in real-time when running

**Via API:**
```bash
curl https://cyberx-event-mgmt.onrender.com/health
# Returns 503 if suspended
# Returns 200 + health data if running
```

### Billing Monitoring

**Render:**
- Dashboard → Billing
- Shows current month charges
- See when service was active

**Supabase:**
- Dashboard → Billing & Usage
- Always shows $25/month (Pro plan)
- See bandwidth and storage usage

### Set Budget Alerts

**Render:**
1. Dashboard → Account Settings → Billing
2. Set spending limit: $10/month
3. Get email if exceeded (safety net)

**Supabase:**
1. Project Settings → Billing
2. Pro plan is fixed $25/month
3. Additional charges if exceed limits

---

## 🛠️ Troubleshooting

### Service Won't Resume

**Symptoms:** Click Resume, but service stays suspended

**Solutions:**
1. Hard refresh browser (Cmd+Shift+R)
2. Wait 30 seconds and check again
3. Check for Render service incidents: https://status.render.com
4. Contact Render support if stuck

### Database Connection Errors After Resume

**Symptoms:** App resumes but can't connect to Supabase

**Solutions:**
1. Check DATABASE_URL is correct in environment variables
2. Verify Supabase project is awake (Pro = always on)
3. Test connection directly:
   ```bash
   psql "postgresql://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres"
   ```
4. Check Supabase status: https://status.supabase.com

### Forgot to Resume Before Event

**Symptoms:** Event starts, app is suspended!

**Quick fix:**
1. Resume service immediately (2-3 min wait)
2. Have participants wait or send apology email
3. Service will be live in ~3 minutes
4. Set calendar reminders to prevent this!

### Forgot to Suspend After Event

**Symptoms:** Month ends, higher bill than expected

**Impact:**
- Extra $7 for that month
- Not catastrophic
- Suspend ASAP to prevent next month charge

**Prevention:**
- Set calendar reminder for 24 hours post-event
- Add to post-event checklist

---

## 📱 Automation Ideas (Optional)

### Calendar Reminders

Set recurring calendar events:

```
Event: Resume CyberX App
When: 2 days before each event
Reminder: 1 day before
Notes: Go to Render dashboard → Resume service
```

```
Event: Suspend CyberX App
When: 1 day after each event
Reminder: Same day
Notes: Go to Render dashboard → Suspend service
```

### Webhook Automation (Advanced)

You could automate suspend/resume using Render API:

```bash
# Resume service
curl -X POST https://api.render.com/v1/services/{serviceId}/resume \
  -H "Authorization: Bearer $RENDER_API_KEY"

# Suspend service
curl -X POST https://api.render.com/v1/services/{serviceId}/suspend \
  -H "Authorization: Bearer $RENDER_API_KEY"
```

But honestly, **manual is fine** for 4 events/year!

---

## 📈 When to Upgrade Strategy

### Switch to Always-On if:

1. **Usage increases**
   - Monthly events instead of quarterly
   - Savings diminish below $50/year

2. **Management burden**
   - Forgot to resume/suspend multiple times
   - Prefer zero-touch automation

3. **Need instant availability**
   - Monitoring/alerts require 24/7 uptime
   - Can't tolerate 3-minute resume time

### Upgrade Calculation

```
Break-even point:
If active > 5 months/year → Always-on makes sense
If active < 5 months/year → Suspend strategy saves money

Your case (1-2 months/year):
Suspend strategy saves ~$70/year ✅
```

---

## ✅ Summary

### Your Setup
```
Application:    Render Web (Starter, $7/month)
Database:       Supabase Pro ($25/month)
Cache/Redis:    None (not needed)
Strategy:       Manual suspend between events
Cost:           ~$311/year
Management:     ~10 minutes per event (resume/suspend)
```

### Benefits
- ✅ Best backups (Supabase PITR)
- ✅ 19% cost savings vs always-on
- ✅ Simple management (just 2 clicks)
- ✅ Zero data loss risk
- ✅ Professional infrastructure

### Trade-offs
- ⚠️ Manual suspend/resume (10 min/year)
- ⚠️ Need to plan ahead (resume 1-2 days early)
- ⚠️ 3-minute resume time

---

## 🚀 Quick Start

1. **Set up Supabase Pro** ($25/month)
   - Follow [SUPABASE_SETUP.md](SUPABASE_SETUP.md)

2. **Deploy to Render** ($7/month when active)
   - Use `render-supabase.yaml` config
   - Add DATABASE_URL from Supabase

3. **Test resume/suspend flow**
   - Practice before first event
   - Time the resume process (~3 min)

4. **Set calendar reminders**
   - Resume 2 days before events
   - Suspend 1 day after events

5. **Run your events!**
   - Enjoy professional infrastructure
   - Save $70+/year with minimal effort

---

**You're all set!** This strategy gives you professional-grade backups while saving money with minimal management overhead.

**Last Updated:** 2026-02-03
