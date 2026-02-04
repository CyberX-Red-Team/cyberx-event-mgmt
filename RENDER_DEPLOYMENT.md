# Deploy to Render.com

Quick guide to deploy the CyberX Event Management System to Render.com.

**Estimated Cost:** $24/month
**Setup Time:** 15 minutes
**Suitable For:** Up to 500+ users with sporadic traffic

---

## Why Render?

✅ **Perfect for your scale** - Handles 100 users easily on starter tier
✅ **Complete stack** - PostgreSQL + Redis included
✅ **Auto-deploy** - Push to GitHub, auto-deploys
✅ **Zero DevOps** - Fully managed SSL, backups, monitoring
✅ **Better than Heroku** - Similar experience, half the cost

---

## Quick Deploy (5 minutes)

### Option 1: One-Click Deploy

1. **Click this button:**

   [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/CyberX-Red-Team/cyberx-event-mgmt)

2. **Fill in required environment variables:**
   - `SENDGRID_API_KEY` - Your SendGrid API key
   - `SENDGRID_FROM_EMAIL` - Your sender email
   - `VPN_SERVER_PUBLIC_KEY` - Your WireGuard public key
   - `VPN_SERVER_ENDPOINT` - Your VPN server endpoint

3. **Wait 5-10 minutes** for deployment to complete

4. **Access your app** at `https://cyberx-event-mgmt.onrender.com`

---

## Option 2: Manual Setup (15 minutes)

### Step 1: Create Render Account

1. Go to [render.com](https://render.com)
2. Sign up with GitHub (recommended)
3. Connect your GitHub repository

### Step 2: Create PostgreSQL Database

1. Click **New** → **PostgreSQL**
2. **Name:** `cyberx-postgres`
3. **Database:** `cyberx_events`
4. **Region:** Choose closest to your users (Oregon for US West)
5. **Plan:** Starter ($7/month)
6. Click **Create Database**
7. Wait 2-3 minutes for provisioning

### Step 3: Create Redis Instance

1. Click **New** → **Redis**
2. **Name:** `cyberx-redis`
3. **Region:** Same as PostgreSQL
4. **Plan:** Starter ($10/month)
5. **Maxmemory Policy:** `allkeys-lru`
6. Click **Create Redis**

### Step 4: Deploy Web Service

1. Click **New** → **Web Service**
2. **Connect Repository:** Select `cyberx-event-mgmt`
3. **Name:** `cyberx-event-mgmt`
4. **Region:** Same as database
5. **Branch:** `main`
6. **Root Directory:** Leave blank
7. **Runtime:** Python 3
8. **Build Command:**
   ```bash
   cd backend && pip install -r requirements.txt
   ```
9. **Start Command:**
   ```bash
   cd backend && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
   ```
10. **Plan:** Starter ($7/month)

### Step 5: Configure Environment Variables

Click **Environment** tab and add:

```env
# Auto-configured (click Add dropdown → Add from Database/Service)
DATABASE_URL=<from cyberx-postgres>
REDIS_URL=<from cyberx-redis>

# Auto-generate (click Generate Value)
SECRET_KEY=<generate>
CSRF_SECRET_KEY=<generate>
ENCRYPTION_KEY=<generate>

# Your values (required)
SENDGRID_API_KEY=SG.your-api-key-here
SENDGRID_FROM_EMAIL=noreply@yourdomain.com
SENDGRID_FROM_NAME=CyberX Red Team
VPN_SERVER_PUBLIC_KEY=your-wireguard-public-key
VPN_SERVER_ENDPOINT=vpn.yourdomain.com:51820

# Standard values
DEBUG=False
FRONTEND_URL=https://cyberx-event-mgmt.onrender.com
ALLOWED_HOSTS=cyberx-event-mgmt.onrender.com
SENDGRID_SANDBOX_MODE=false
VPN_DNS_SERVERS=10.20.200.1
VPN_ALLOWED_IPS=10.0.0.0/8,fd00:a::/32
SESSION_EXPIRY_HOURS=24
BULK_EMAIL_INTERVAL_MINUTES=45
```

### Step 6: Deploy

1. Click **Create Web Service**
2. Wait 5-10 minutes for initial deployment
3. Monitor logs for any errors
4. Once deployed, visit your app URL

### Step 7: Create Admin User

1. Open **Shell** tab in Render dashboard
2. Run:
   ```bash
   cd backend
   python scripts/setup_clean_db.py \
       --admin-email admin@yourdomain.com \
       --admin-password your-secure-password \
       --no-prompt
   ```

---

## Optional: Background Worker

If you need scheduled email reminders:

1. Click **New** → **Background Worker**
2. **Name:** `cyberx-worker`
3. **Build Command:** Same as web service
4. **Start Command:**
   ```bash
   cd backend && python -m app.tasks.scheduler
   ```
5. **Environment:** Same as web service
6. **Plan:** Starter ($7/month)

**Total Cost with Worker:** $31/month

---

## Custom Domain (Optional)

### Add Your Domain

1. Go to web service **Settings**
2. Click **Custom Domain**
3. Add `events.yourdomain.com`
4. Follow DNS instructions:
   ```
   CNAME events.yourdomain.com → cyberx-event-mgmt.onrender.com
   ```
5. SSL certificate auto-provisions (5-10 minutes)

### Update Environment Variables

```env
FRONTEND_URL=https://events.yourdomain.com
ALLOWED_HOSTS=events.yourdomain.com,cyberx-event-mgmt.onrender.com
```

---

## Auto-Deployment

Render automatically deploys when you push to `main`:

```bash
git push origin main
# Render detects push and deploys in ~3-5 minutes
```

**Disable auto-deploy:**
- Go to **Settings** → **Build & Deploy**
- Turn off **Auto-Deploy**

---

## Database Management

### Connect to PostgreSQL

**From Render dashboard:**
1. Click on `cyberx-postgres`
2. Click **Connect** → Copy connection string
3. Use with psql:
   ```bash
   psql "postgresql://user:pass@host/db?sslmode=require"
   ```

**From local machine:**
```bash
# Get connection string from Render dashboard
export DATABASE_URL="postgresql://..."

# Connect
psql $DATABASE_URL

# Or use with Python
cd backend
python
>>> from app.database import engine
>>> # Your DB operations
```

### Run Migrations

**Via Render Shell:**
```bash
cd backend
alembic upgrade head
```

**Via local machine:**
```bash
export DATABASE_URL="<render-postgres-url>"
cd backend
alembic upgrade head
```

### Backups

Render automatically backs up PostgreSQL:
- **Free tier:** Daily backups, 7-day retention
- **Starter tier:** Daily backups, 7-day retention
- **Standard+:** Continuous backups, 30-day retention

**Manual backup:**
```bash
# From Render dashboard
# PostgreSQL service → Backups → Create Backup

# Or via CLI
pg_dump $DATABASE_URL | gzip > backup.sql.gz
```

**Restore from backup:**
```bash
# From Render dashboard
# Backups → Select backup → Restore

# Or via CLI
gunzip < backup.sql.gz | psql $DATABASE_URL
```

---

## Monitoring

### Built-in Metrics (Free)

1. **Web Service Dashboard:**
   - CPU usage
   - Memory usage
   - Response times
   - HTTP requests/errors
   - Deployment history

2. **Database Metrics:**
   - Storage used
   - Connection count
   - Query performance

### Logs

**View logs:**
1. Go to web service
2. Click **Logs** tab
3. Real-time streaming logs

**Download logs:**
```bash
# Via Render API (requires API key)
curl -H "Authorization: Bearer $RENDER_API_KEY" \
  https://api.render.com/v1/services/srv-xxx/logs
```

### Health Checks

Render automatically monitors `/health` endpoint:
- Checks every 30 seconds
- Auto-restarts on failure
- Sends notifications

**Configure:**
- Settings → Health Check Path: `/health`
- Health Check Interval: 30 seconds

---

## Scaling

### Vertical Scaling (Upgrade Plan)

| Plan | RAM | CPU | Price | Suitable For |
|------|-----|-----|-------|--------------|
| Free | 512MB | Shared | $0 | Testing only |
| Starter | 512MB | Shared | $7 | **100 users ✅** |
| Standard | 2GB | 1 CPU | $25 | 500+ users |
| Pro | 4GB | 2 CPU | $85 | 2000+ users |

**Your needs:** Starter tier is perfect for 100 users

### Horizontal Scaling (Add Instances)

For high availability:
1. **Settings** → **Scaling**
2. Increase **Instance Count** to 2+
3. Render load-balances automatically

**Note:** Redis would need upgrade for multi-instance

### Auto-Scaling

Not available on Starter tier. Upgrade to Standard for:
- Auto-scale based on CPU/memory
- Min/max instance configuration

---

## Cost Optimization

### Current Setup: $24/month

```
Web Service (Starter):     $7/month
PostgreSQL (Starter):      $7/month
Redis (Starter):           $10/month
Total:                     $24/month
```

### Save Money:

1. **Skip Worker:** Handle jobs in web service (-$7/month)
   - APScheduler runs in main process
   - Fine for 100 users

2. **Use Free Redis Alternative:** Upstash Redis Free tier
   - 10,000 commands/day free
   - Connect via REDIS_URL

3. **Suspend During Off-Season:**
   - Suspend services between events
   - Pay only for active months

### Potential Monthly Cost: $14/month
```
Web Service (Starter):     $7/month
PostgreSQL (Starter):      $7/month
Redis (Upstash Free):      $0/month
Total:                     $14/month
```

---

## Troubleshooting

### Build Fails

**Check build logs:**
- Logs tab → Build logs
- Common issues:
  - Missing dependencies in `requirements.txt`
  - Python version mismatch

**Fix:**
```bash
# Ensure requirements.txt is complete
cd backend
pip freeze > requirements.txt
git commit -am "Update requirements"
git push
```

### Database Connection Errors

**Check:**
1. DATABASE_URL is set correctly
2. PostgreSQL service is running
3. Connection string format:
   ```
   postgresql+asyncpg://user:pass@host/db?sslmode=require
   ```

### App Crashes on Start

**Common causes:**
1. Missing environment variables
2. Migration errors
3. Port binding issues

**Debug:**
```bash
# Check environment variables
# Settings → Environment → Verify all required vars

# Run migrations manually
# Shell → cd backend && alembic upgrade head

# Check logs for specific errors
```

### Slow Performance

**Check:**
1. Database connection pool settings
2. Memory usage (might need to upgrade plan)
3. Query performance (add indexes)

**Optimize:**
```python
# In app/database.py
# Adjust pool size for Render
engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,  # Lower for Starter tier
    max_overflow=10
)
```

---

## Migration from Development

### Export Data

```bash
# From local database
cd backend
python scripts/export_data.py > data.json
```

### Import to Render

```bash
# Via Render Shell
cd backend
python scripts/import_data.py < data.json
```

---

## Alternatives if Render Doesn't Work

### If you need cheaper: Railway.app
- Usage-based pricing (~$5-15/month)
- Similar deployment experience
- [See Railway guide](#)

### If you need more control: Fly.io
- More configuration options
- Better for global distribution
- Scale to zero capability
- [See Fly.io guide](#)

### If you need simplest: DigitalOcean App Platform
- Even simpler than Render
- Predictable pricing ($18/month)
- Great documentation

---

## Next Steps

1. ✅ **Deploy to Render** (follow steps above)
2. ✅ **Create admin user** (via Shell)
3. ✅ **Test application** (login, create event, etc.)
4. ✅ **Configure custom domain** (optional)
5. ✅ **Set up monitoring** (check metrics)
6. ✅ **Import your data** (participants, VPN configs)

---

## Support

- **Render Docs:** https://render.com/docs
- **Render Community:** https://community.render.com
- **Render Status:** https://status.render.com

---

**Ready to deploy?** Click the Deploy to Render button at the top!

**Last Updated:** 2026-02-03
