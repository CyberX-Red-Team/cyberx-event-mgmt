# Hosting Platform Comparison

Complete comparison of hosting options for CyberX Event Management System.

**Your Requirements:**
- ~100 users per event
- Very sporadic usage (events only)
- Mainly VPN config downloads
- Need database backups
- 4-6 events per year (1 week each)

---

## 🏆 The Winner: Fly.io (Scale-to-Zero)

**Annual Cost:** ~$40/year
**Best For:** Intermittent usage, cost-conscious
**Cold Start:** 2 seconds (acceptable for your use case)

---

## Complete Comparison Table

| Platform | Always-On Cost | Intermittent Cost | Scale-to-Zero | Best For |
|----------|----------------|-------------------|---------------|----------|
| **Fly.io** | $60/year | **$40/year** | ✅ Auto | **Your use case!** |
| **Railway** | $180/year | $80/year | ⚠️ Manual | Good alternative |
| **Render** | $384/year | $211/year | ❌ No | Always-on apps |
| **Heroku** | $600/year | N/A | ❌ No | ❌ Too expensive |

---

## Detailed Platform Analysis

### 1. Fly.io - Best for Sporadic Usage

#### Pricing
```
FREE TIER INCLUDES:
- 3 shared VMs (256MB each)
- 3GB storage
- 160GB bandwidth/month

YOUR COSTS:
During event week (168 hours):
  App VM:              $7-10/week
  PostgreSQL:          Free tier
  Storage:             Free tier
                       ──────────
  Total per event:     $10/week

Between events (11 months):
  Storage only:        $0.15/month × 11 = $2

ANNUAL TOTAL:          ~$42/year
```

#### Features
- ✅ **Auto scale-to-zero** - Sleeps when idle
- ✅ **1-2 second wake** - Fast cold start
- ✅ **Pay per second** - Only charged when running
- ✅ **Global edge network** - Fast VPN downloads worldwide
- ✅ **No manual management** - Automatic wake/sleep
- ✅ **Built-in PostgreSQL** - Free tier sufficient
- ⚠️ **Cold start delay** - 2 seconds on first request

#### Best For
- ✅ Sporadic usage (your case!)
- ✅ Cost-conscious deployments
- ✅ Global distribution needed
- ✅ Can tolerate 2-second cold start
- ❌ Need instant 24/7 response

#### Setup Complexity
⭐⭐⭐⚪⚪ Medium (CLI-based, some config)

#### Deployment Guide
See: [FLY_IO_DEPLOYMENT.md](FLY_IO_DEPLOYMENT.md)

---

### 2. Railway - Good Alternative

#### Pricing
```
FREE TIER:
- $5 credit per month
- Usage-based billing

YOUR COSTS (Manual Stop/Start):
During event week:
  App:                 $10/week
  PostgreSQL:          $5/week
  Redis (optional):    $3/week
                       ──────────
  Total per event:     $15-18/week

4 events/year:         $60-72/year
Idle storage:          $20/year
                       ──────────
ANNUAL TOTAL:          ~$80-92/year
```

#### Features
- ✅ **Best developer experience** - Easiest to use
- ✅ **Usage-based pricing** - Pay only for what you use
- ✅ **One-click database** - PostgreSQL, Redis, etc.
- ✅ **Great monitoring** - Built-in dashboards
- ⚠️ **Manual stop/start** - Not automatic
- ⚠️ **No auto-sleep** - Need to manually control

#### Best For
- ✅ Developers who want simplicity
- ✅ Flexible usage patterns
- ✅ Great monitoring needed
- ⚠️ Willing to manually stop/start
- ❌ Want full automation

#### Setup Complexity
⭐⭐⚪⚪⚪ Easy (GUI-based, very intuitive)

#### Manual Control
```bash
# Stop all services (via dashboard)
# Billing pauses immediately

# Start before event (via dashboard)
# Services ready in ~2 minutes
```

---

### 3. Render - Best for Always-On

#### Pricing (Always-On)
```
Render Web:            $7/month × 12 = $84/year
Render PostgreSQL:     $7/month × 12 = $84/year
Render Redis:          $10/month × 12 = $120/year
                                        ─────────
ANNUAL TOTAL:                           $288/year
```

#### Pricing (Manual Suspend - Web Only)
```
Render Web:            $7/month × 1 = $7/year
Render PostgreSQL:     $7/month × 12 = $84/year (can't stop)
Render Redis:          $10/month × 12 = $120/year (can't stop)
                                        ─────────
ANNUAL TOTAL:                           $211/year

Problem: Database and Redis always billed
```

#### Features
- ✅ **Easiest deployment** - Git push to deploy
- ✅ **Great documentation** - Excellent guides
- ✅ **Zero config** - Sensible defaults
- ✅ **No cold starts** - Always instant
- ❌ **No scale-to-zero** - Always billed
- ❌ **Can't stop database** - Database always charged

#### Best For
- ✅ Always-on applications
- ✅ Want zero cold starts
- ✅ Need instant response 24/7
- ❌ Sporadic usage (wasteful)
- ❌ Budget-conscious

#### Setup Complexity
⭐⭐⚪⚪⚪ Easy (Git-based, auto-deploy)

#### Deployment Guide
See: [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)

---

### 4. Supabase Database Options

#### Supabase Free (Can Pause)
```
Cost:                  $0/year
Storage:               500MB
Features:              Auth, Storage, APIs
Auto-pause:            After 7 days idle
Wake time:             5-10 seconds
Backups:               7 days (no PITR)

✅ Perfect for intermittent use!
⚠️ Limited storage (500MB)
⚠️ Longer cold start (5-10 seconds)
```

#### Supabase Pro (Always-On)
```
Cost:                  $25/month = $300/year
Storage:               8GB
Features:              Auth, Storage, APIs, PITR
Always-on:             Cannot pause
Backups:               7 days + PITR
Download:              Yes

✅ Best backups (PITR)
✅ More storage (8GB)
❌ Cannot pause (always billed)
❌ Expensive for intermittent use
```

---

## 🎯 Recommendations by Usage Pattern

### Sporadic Usage (Your Case: 4-6 events/year)

**Option 1: Fly.io + Supabase Free** 🏆
```
Annual Cost:           ~$40/year
Cold Start:            2 seconds (app) + 5 seconds (DB first time)
Savings:               90% vs always-on

Perfect if:
✅ Budget is priority
✅ Can tolerate 2-second wake
✅ Database < 500MB
✅ Don't need PITR backups
```

**Option 2: Fly.io + Supabase Pro**
```
Annual Cost:           ~$340/year
Cold Start:            2 seconds (app only, DB always on)
Backups:               Best (PITR)

Perfect if:
✅ Need best backups
✅ Database > 500MB
✅ Want professional-grade infrastructure
⚠️ More expensive (but still saves vs Render)
```

**Option 3: Railway (Manual Control)**
```
Annual Cost:           ~$80/year
Cold Start:            None (manually start before event)
Control:               Full manual control

Perfect if:
✅ Want middle ground on cost
✅ Prefer manual control
✅ Like Railway's developer experience
⚠️ Need to remember to start/stop
```

### Monthly Usage

**Render + Supabase Pro**
```
Annual Cost:           $384/year
Cold Start:            None
Backups:               Best (PITR)

Best for:
✅ Monthly active usage
✅ Need instant response
✅ Want zero cold starts
✅ Professional backups required
```

### Always-On Usage

**Render + Supabase Pro**
```
Annual Cost:           $384/year

Same as monthly, but makes more sense
✅ App used daily/weekly
✅ Real-time requirements
✅ Monitoring/alerts needed
```

---

## 💰 Cost Comparison Summary

### For 4 Events/Year (1 week each)

| Solution | Annual Cost | Savings | Cold Start | Backups |
|----------|-------------|---------|------------|---------|
| **Fly.io + Supabase Free** | **$40** | **90%** | 2 sec | Basic |
| Railway (manual) | $80 | 79% | 0 sec* | Basic |
| Fly.io + Supabase Pro | $340 | 11% | 2 sec | PITR |
| Render + Supabase Pro | $384 | 0% | 0 sec | PITR |

*If manually started before event

---

## 🎯 My Final Recommendation

### For Your Use Case (100 users, 4-6 events/year):

**Use Fly.io + Supabase Free**

**Why:**
```
1. COST: $40/year vs $384/year (90% savings!)
2. AUTOMATIC: Scale-to-zero with auto-wake
3. ACCEPTABLE: 2-second cold start is fine for events
4. SIMPLE: Set it up once, forget about it
5. GROWS: Easy to upgrade if needs change
```

**Trade-offs you accept:**
```
⚠️ 2-second delay on first request (then instant)
⚠️ Basic backups (no PITR)
⚠️ 500MB database limit
```

**When to upgrade:**
```
→ If database grows > 500MB: Add Supabase Pro (+$300/year)
→ If need PITR backups: Add Supabase Pro (+$300/year)
→ If can't tolerate cold start: Switch to Render (+$344/year)
→ If usage becomes weekly: Re-evaluate (might not save much)
```

---

## 🚀 Migration Path

### Phase 1: Start Cheap (Year 1)
```
Fly.io + Supabase Free
Cost: ~$40/year
Goal: Validate usage patterns
```

### Phase 2: Upgrade If Needed (Year 2+)
```
Option A: Database grows
  → Fly.io + Supabase Pro
  Cost: ~$340/year

Option B: Usage increases
  → Render + Supabase Pro
  Cost: $384/year

Option C: Usage stays low
  → Keep Fly.io + Free!
  Cost: $40/year forever
```

---

## ⚙️ Setup Guides

Choose your platform and follow the guide:

1. **[FLY_IO_DEPLOYMENT.md](FLY_IO_DEPLOYMENT.md)** - Best for sporadic use
2. **[RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)** - Best for always-on
3. **[SUPABASE_SETUP.md](SUPABASE_SETUP.md)** - Database setup (either platform)

---

## 📊 Decision Tree

```
┌─ How often is app used? ─┐
│                           │
├─ Few times/year           ├─ Monthly/Weekly         ├─ Daily/Always-On
│  (Your case!)             │                         │
│                           │                         │
└─ Fly.io Scale-to-Zero    └─ Render + Supabase      └─ Render + Supabase
   Cost: $40/year              Cost: $384/year           Cost: $384/year
   Cold start: 2 sec           Cold start: None          Cold start: None
   ✅ BEST FOR YOU!             ⚠️ Consider Fly.io        ✅ Makes sense
```

---

## 🎓 Key Learnings

1. **Always-on is wasteful** for sporadic usage
2. **Scale-to-zero saves 90%** for event-based apps
3. **2-second cold start is acceptable** for your use case
4. **Start cheap, upgrade later** as needs grow
5. **Fly.io is perfect** for intermittent usage

---

## ❓ FAQ

**Q: What if users complain about 2-second cold start?**
A: Manually wake app 30 minutes before event starts:
```bash
flyctl machine start --all
```
Then all users get instant response!

**Q: Can I test cold start time before committing?**
A: Yes! Deploy to Fly.io, let it sleep, then test first request time.

**Q: What if my database grows beyond 500MB?**
A: Upgrade to Supabase Pro ($25/month) for 8GB storage.

**Q: Can I switch platforms later?**
A: Yes! Your app is portable. Database export/import takes ~15 minutes.

**Q: What about data loss between events?**
A: Data persists during sleep. Cold start only affects app startup, not data.

---

## 📝 Next Steps

### To Deploy Fly.io (Recommended):

1. ✅ Read [FLY_IO_DEPLOYMENT.md](FLY_IO_DEPLOYMENT.md)
2. ✅ Install Fly CLI: `brew install flyctl`
3. ✅ Deploy app: `flyctl launch`
4. ✅ Test cold start time
5. ✅ Run your first event!

### To Deploy Render (Alternative):

1. ✅ Read [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)
2. ✅ Push render.yaml to repo
3. ✅ Click "Deploy to Render"
4. ✅ Set environment variables
5. ✅ Go live!

---

**Bottom Line:** For 4-6 events per year, **Fly.io saves you $344/year** with minimal tradeoffs!

**Last Updated:** 2026-02-03
