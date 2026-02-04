# Deploy with Supabase Database

Guide for deploying CyberX Event Management with Render (web) + Supabase (database).

**Cost:** $32/month ($7 Render + $25 Supabase)
**Best For:** Superior backup/recovery and future expansion

---

## Why This Combo?

✅ **Point-in-Time Recovery** - Restore to any second in the last 7 days
✅ **8GB database** vs 1GB (8x larger)
✅ **Better backups** - Download directly, continuous archiving
✅ **Growth ready** - Auth, Storage, APIs included
✅ **Simple deployment** - FastAPI on Render, DB on Supabase

---

## Step 1: Create Supabase Project

1. **Sign up at [supabase.com](https://supabase.com)**
   - Use GitHub for easy login

2. **Create new project**
   - Click **New Project**
   - **Name:** `cyberx-events`
   - **Database Password:** Generate strong password (save this!)
   - **Region:** Choose closest to users
     - `us-west-1` - San Francisco
     - `us-east-1` - North Virginia
     - `eu-west-1` - Ireland
   - **Pricing Plan:** Pro ($25/month)
   - Click **Create Project** (takes ~2 minutes)

3. **Get connection string**
   - Go to **Project Settings** → **Database**
   - Copy **Connection string** (URI format)
   - Should look like:
     ```
     postgresql://postgres:[YOUR-PASSWORD]@db.xxxxx.supabase.co:5432/postgres
     ```
   - Replace `[YOUR-PASSWORD]` with actual password

4. **Enable connection pooling** (recommended)
   - Same page, find **Connection Pooler**
   - Copy **Transaction** mode connection string
   - Format:
     ```
     postgresql://postgres.xxxxx:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:6543/postgres
     ```

---

## Step 2: Configure Database for FastAPI

### Update Connection String for SQLAlchemy

Your app uses `asyncpg`, so modify the connection string:

**Original Supabase string:**
```
postgresql://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
```

**For FastAPI (asyncpg):**
```
postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
```

Just add `+asyncpg` after `postgresql`!

### Test Connection Locally

```bash
cd backend

# Set DATABASE_URL
export DATABASE_URL="postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres"

# Test connection
python -c "
from app.database import engine
import asyncio

async def test():
    async with engine.connect() as conn:
        print('✅ Connected to Supabase!')

asyncio.run(test())
"
```

---

## Step 3: Run Migrations

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
    --no-prompt
```

---

## Step 4: Deploy to Render

### Option A: Update render.yaml

Edit `render.yaml`:

```yaml
services:
  - type: web
    name: cyberx-event-mgmt
    runtime: python
    plan: starter
    envVars:
      # Remove DATABASE_URL fromDatabase reference
      - key: DATABASE_URL
        sync: false  # You'll add this manually

      # Keep Redis from Render
      - key: REDIS_URL
        fromService:
          name: cyberx-redis
          type: redis
          property: connectionString

      # ... rest of config

# Remove databases section (no Render PostgreSQL needed)
# databases:
#   - name: cyberx-postgres  # DELETE THIS
```

### Option B: Manual Render Setup

1. **Create web service** on Render (follow RENDER_DEPLOYMENT.md)
2. **Skip PostgreSQL creation** (using Supabase instead)
3. **Create Redis** on Render ($10/month)
4. **Add environment variable:**
   ```
   DATABASE_URL=postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
   ```

---

## Step 5: Configure Backups

### Automatic Backups (Included)

Supabase Pro automatically:
- Daily backups at ~2:00 AM UTC
- Keeps 7 days of daily backups
- Point-in-time recovery for last 7 days
- Continuous WAL archiving

**No configuration needed!** ✅

### Manual Backups

**Via Supabase Dashboard:**
1. Go to **Database** → **Backups**
2. Click **Create Backup Now**
3. Backup completes in ~1-5 minutes

**Via Command Line:**
```bash
# Get connection string from Supabase dashboard
export SUPABASE_URL="postgresql://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres"

# Create backup
pg_dump $SUPABASE_URL | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Restore backup
gunzip < backup_20260203_120000.sql.gz | psql $SUPABASE_URL
```

### Download Backups

Supabase Pro lets you download backups directly:

1. **Database** → **Backups**
2. Select backup
3. Click **Download**
4. Gets `.tar.gz` file you can store offline

---

## Step 6: Point-in-Time Recovery (PITR)

### When to Use PITR

- Accidental data deletion
- Bad migration applied
- Need to see historical data state
- Restore to exact moment before incident

### How to Use PITR

1. **Go to Database → Backups**
2. **Click "Point in Time Recovery"**
3. **Select date and time:**
   - Can restore to ANY second in last 7 days
   - Timezone shown in dashboard
4. **Choose recovery method:**
   - **Replace current database** (destructive, recommended)
   - **Create new database** (safe but requires reconnection)
5. **Confirm and restore** (~5-10 minutes)

### Example Scenario

```
Timeline:
Mon 10:00 AM - Import 100 participants ✅
Mon 2:00 PM  - Update email templates ✅
Mon 3:30 PM  - Accidentally delete all participants ❌
Mon 3:32 PM  - Notice mistake!

Solution:
1. Go to Backups → PITR
2. Select Monday 3:29 PM (1 minute before mistake)
3. Restore
4. Result: All participants restored, email templates intact!
```

---

## Cost Breakdown

### Monthly Costs

```
Render Web Service (Starter):    $7/month
Render Redis (Starter):          $10/month
Supabase Pro:                    $25/month
─────────────────────────────────────────
Total:                           $42/month
```

**Wait, I thought you said $32?**

You're right! You have two options:

### Option A: Skip Render Redis ($32/month)

Use Supabase for sessions instead of Redis:

```python
# Store sessions in PostgreSQL instead
# Already have session table in your schema
# Slightly slower but works fine for 100 users
```

**Costs:**
```
Render Web (Starter):    $7/month
Supabase Pro:            $25/month
Total:                   $32/month
```

### Option B: Keep Redis ($42/month)

Better performance for sessions, but costs more.

**Recommendation:** For 100 sporadic users, **skip Redis** and use PostgreSQL sessions ($32/month).

---

## Alternative: Supabase for Everything ($50/month)

Supabase can also host your FastAPI app!

**Option: Supabase Pro + Compute Add-on**
```
Supabase Pro:            $25/month
Compute Add-on (Small):  $10/month
IPv4 Add-on:             $4/month
Total:                   $39/month
```

But Render is easier for FastAPI deployment, so stick with **Render + Supabase** combo.

---

## Configuration Changes for Your App

### Using PostgreSQL Sessions (No Redis)

If skipping Redis, update your app:

**In `app/config.py`:**
```python
# Add optional Redis URL
REDIS_URL: Optional[str] = None

@property
def use_redis_sessions(self) -> bool:
    """Check if Redis is available for sessions."""
    return self.REDIS_URL is not None
```

**In `app/services/auth_service.py`:**
```python
# Use database sessions by default
# Your current implementation already uses DB sessions!
# No changes needed!
```

**Good news:** Your app already stores sessions in PostgreSQL! You can safely skip Redis for sessions.

### What Redis Was For

Looking at your code:
- Session storage: ✅ Already in PostgreSQL
- Rate limiting: ⚠️ In-memory (single instance only)
- Cache: ❌ Not currently used

**For 100 users on single instance:** You don't need Redis at all!

---

## Final Configuration

### Environment Variables for Render

```env
# Database (Supabase)
DATABASE_URL=postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres

# No Redis needed!
# REDIS_URL=  # Leave empty or remove

# Your app settings
SECRET_KEY=<generate-strong-key>
CSRF_SECRET_KEY=<generate-strong-key>
ENCRYPTION_KEY=<generate-fernet-key>

# SendGrid
SENDGRID_API_KEY=SG.xxx
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
SENDGRID_FROM_NAME=CyberX Red Team

# VPN
VPN_SERVER_PUBLIC_KEY=xxx
VPN_SERVER_ENDPOINT=vpn.yourdomain.com:51820
VPN_DNS_SERVERS=10.20.200.1
VPN_ALLOWED_IPS=10.0.0.0/8,fd00:a::/32

# URLs
FRONTEND_URL=https://cyberx-event-mgmt.onrender.com
ALLOWED_HOSTS=cyberx-event-mgmt.onrender.com

# Standard settings
DEBUG=False
SENDGRID_SANDBOX_MODE=false
SESSION_EXPIRY_HOURS=24
BULK_EMAIL_INTERVAL_MINUTES=45
```

---

## Monitoring Database

### Supabase Dashboard

**Database Health:**
- **Database** → **Database Health**
- Shows: CPU, RAM, Disk, Connections

**Query Performance:**
- **Database** → **Query Performance**
- Identify slow queries
- View connection pool status

**Logs:**
- **Database** → **Logs**
- Real-time PostgreSQL logs
- Filter by error level

### Connection Pooling Stats

```sql
-- View active connections
SELECT
    count(*),
    state,
    usename,
    application_name
FROM pg_stat_activity
GROUP BY state, usename, application_name;

-- Check pool usage
SELECT * FROM pg_stat_database
WHERE datname = 'postgres';
```

---

## Backup Best Practices

### Regular Testing

**Monthly drill:**
1. Create test backup
2. Restore to new instance
3. Verify data integrity
4. Document time taken

### Disaster Recovery Plan

```markdown
1. Identify issue and timestamp
2. Stop application (prevent more damage)
3. Go to Supabase Dashboard → Backups
4. PITR to 5 minutes before incident
5. Restart application
6. Verify data restored
7. Document incident
```

### External Backups (Extra Safety)

Weekly backup to external storage:

```bash
#!/bin/bash
# Weekly backup script

DATE=$(date +%Y%m%d)
BACKUP_FILE="cyberx_backup_${DATE}.sql.gz"

# Backup database
pg_dump $DATABASE_URL | gzip > $BACKUP_FILE

# Upload to S3 (or any storage)
aws s3 cp $BACKUP_FILE s3://your-backup-bucket/

# Keep last 4 weeks (monthly)
find . -name "cyberx_backup_*.sql.gz" -mtime +28 -delete

echo "✅ Backup completed: $BACKUP_FILE"
```

---

## Migration from Render PostgreSQL

If you later want to migrate FROM Render TO Supabase:

```bash
# 1. Backup from Render
pg_dump $RENDER_DATABASE_URL > render_backup.sql

# 2. Restore to Supabase
psql $SUPABASE_DATABASE_URL < render_backup.sql

# 3. Update Render environment variable
# Change DATABASE_URL to Supabase connection string

# 4. Restart Render service
# Done!
```

---

## Comparison: What You Get

### Render PostgreSQL ($7/month)
```
✅ 1GB storage
✅ Daily backups (7 days)
✅ 97 connections
❌ No point-in-time recovery
❌ No backup downloads
❌ Basic monitoring
```

### Supabase Pro ($25/month)
```
✅ 8GB storage (8x more!)
✅ Daily backups (7 days)
✅ Point-in-time recovery (ANY second!)
✅ Download backups
✅ 200 direct connections + pooler
✅ Advanced monitoring
✅ Bonus: Auth, Storage, APIs
✅ Better compliance story
```

**Extra $18/month gets you:**
- 8x more storage
- Point-in-time recovery (critical!)
- Direct backup downloads
- Better monitoring
- Future expansion features

---

## Decision Matrix

| Scenario | Use Render DB | Use Supabase |
|----------|--------------|--------------|
| Tight budget | ✅ $7 | ❌ $25 |
| Need PITR | ❌ No | ✅ Yes |
| < 1GB data | ✅ Enough | ⚠️ Overkill |
| Compliance required | ⚠️ Basic | ✅ Better |
| Future growth | ⚠️ Limited | ✅ Ready |
| Need external backups | ⚠️ Manual | ✅ Built-in |

---

## My Recommendation

For **$32/month** (Render Web + Supabase Pro):

✅ **Best backup solution** for your critical event data
✅ **Peace of mind** during live events
✅ **Room to grow** without platform change
✅ **Only $8/month more** than Render-only solution

**Worth it if:**
- Events are important/high-stakes
- Data loss would be costly
- You want professional-grade backups

**Skip it if:**
- Budget is tight
- Database < 500MB
- Can tolerate 24-hour data loss

---

## Next Steps

1. ✅ Create Supabase project
2. ✅ Run migrations to Supabase
3. ✅ Deploy Render web service
4. ✅ Test backup/restore
5. ✅ Document recovery procedures

---

**Ready to deploy?** Follow the steps above!

**Questions?** Check Supabase docs: https://supabase.com/docs
