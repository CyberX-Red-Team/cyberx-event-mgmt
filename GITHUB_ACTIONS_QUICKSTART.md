# GitHub Actions Quick Start Guide

Complete guide to setting up and using GitHub Actions CI/CD for staging and production deployments.

---

## 🚀 Quick Setup (5 Minutes)

### Prerequisites

1. **Install GitHub CLI:**
   ```bash
   # macOS
   brew install gh

   # Linux (see https://cli.github.com/manual/installation)
   # Windows (see https://cli.github.com/manual/installation)
   ```

2. **Authenticate:**
   ```bash
   gh auth login
   ```

3. **Have ready:**
   - Render API key
   - Staging Render service ID
   - Production Render service ID
   - Staging Supabase database URL
   - Production Supabase database URL

### Run Setup Script

```bash
cd cyberx-event-mgmt
./scripts/setup-github-actions.sh
```

The script will:
1. ✅ Create GitHub environments (staging, production, production-suspend)
2. ✅ Set up all repository secrets
3. ✅ Configure deployment workflows
4. ✅ Validate all inputs

**That's it!** Your CI/CD is ready.

---

## 📋 Manual Configuration Steps

After running the script:

### 1. Configure Environment Protection Rules

Go to: https://github.com/YOUR_ORG/cyberx-event-mgmt/settings/environments

**For `production` environment:**
1. Click **production**
2. Under **Deployment protection rules:**
   - Check **Required reviewers**
   - Add yourself + team members
   - Optionally check **Prevent self-review**
3. Under **Environment secrets** (optional):
   - Add environment-specific secrets if needed
4. Under **Deployment branches:**
   - Select **Selected branches**
   - Add `main` branch
5. Click **Save protection rules**

**For `production-suspend` environment:**
1. Click **production-suspend**
2. Add **Required reviewers** (can be same or different)
3. Click **Save protection rules**

**For `staging` environment:**
- No protection rules needed (auto-deploy)
- Optionally add environment URL: `https://staging.events.cyberxredteam.org`

### 2. Update Render Service Settings

**Disable auto-deploy on Render:**

Both staging and production services should have auto-deploy disabled since GitHub Actions will manage deployments:

1. Go to Render Dashboard
2. Select service (staging or production)
3. Click **Settings**
4. Under **Build & Deploy:**
   - Disable **Auto-Deploy**
   - This prevents Render from auto-deploying on git push

---

## 🎯 Usage Guide

### Automatic Staging Deployment

**Trigger:** Push to `main` or `develop`

```bash
# Make changes
git checkout main
git add .
git commit -m "Add new feature"
git push origin main

# GitHub Actions automatically:
# ✅ Runs tests
# ✅ Runs linters
# ✅ Deploys to staging
# ✅ Runs health checks
```

**Monitor:**
- Go to **Actions** tab
- View "Deploy to Staging" workflow

### Production Deployment (Tag-based)

**Trigger:** Create and push a version tag

```bash
# Ensure changes are on main branch
git checkout main
git pull

# Create tag
git tag v1.0.0 -m "Release v1.0.0"

# Push tag
git push origin v1.0.0

# GitHub Actions:
# ✅ Runs tests
# ✅ Creates database backup
# ⏸️  WAITS for manual approval
```

**Approve deployment:**

1. Go to **Actions** tab
2. Find "Deploy to Production" workflow
3. Click on the running workflow
4. Click **Review deployments**
5. Select **production** environment
6. Click **Approve and deploy**

**After approval:**
- ✅ Resumes service if suspended
- ✅ Runs migrations
- ✅ Deploys to production
- ✅ Runs health checks
- ✅ Creates GitHub release

### Manual Production Deployment

**Trigger:** Workflow dispatch

1. Go to **Actions** → **Deploy to Production**
2. Click **Run workflow**
3. Select **action: deploy**
4. Click **Run workflow**
5. Approve when prompted

### Resume Production Service (Before Event)

**Use:** 2 days before event starts

1. Go to **Actions** → **Deploy to Production**
2. Click **Run workflow**
3. **Action:** Select `resume`
4. **Skip tests:** Check ✓ (optional)
5. Click **Run workflow**
6. Approve when prompted
7. Wait ~3 minutes for service to start

**Verify:**
```bash
curl https://events.cyberxredteam.org/health
```

### Suspend Production Service (After Event)

**Use:** 1 day after event ends

1. Go to **Actions** → **Deploy to Production**
2. Click **Run workflow**
3. **Action:** Select `suspend`
4. **Skip tests:** Check ✓
5. Click **Run workflow**
6. Approve when prompted
7. Service suspends immediately

**Result:**
- ✅ Service stopped
- ✅ Billing paused
- ✅ Database remains active

---

## 🔄 Typical Workflow

### Development Cycle

```bash
# 1. Create feature branch
git checkout -b feature/new-feature

# 2. Make changes
# ... code changes ...

# 3. Commit and push
git add .
git commit -m "Add new feature"
git push origin feature/new-feature

# 4. Create pull request
# Tests run automatically on PR

# 5. After review, merge to main
# Staging deploys automatically

# 6. Test on staging
open https://staging.events.cyberxredteam.org

# 7. When ready, create release tag
git checkout main
git pull
git tag v1.1.0
git push origin v1.1.0

# 8. Approve production deployment
# Go to Actions → Approve deployment
```

### Event Management Cycle

```bash
# 2 days before event
Actions → Deploy to Production → resume

# Test production
curl https://events.cyberxredteam.org/health

# During event
# No action needed - service runs normally

# 1 day after event
Actions → Deploy to Production → suspend

# Verify suspension
# Service returns 503 (expected)
```

---

## 📊 Monitoring Deployments

### GitHub Actions

**View workflows:**
- Go to **Actions** tab
- See all running and completed workflows
- Click on workflow to view logs

**Deployment status:**
- Green checkmark ✅ = Success
- Red X ❌ = Failed
- Yellow circle 🟡 = In progress
- Blue pause ⏸️ = Waiting for approval

### Render Dashboard

**View deployments:**
- Go to https://dashboard.render.com
- Select service
- View **Events** tab for deployment history
- View **Logs** tab for real-time logs

### Health Checks

**Staging:**
```bash
curl https://staging.events.cyberxredteam.org/health
```

**Production:**
```bash
curl https://events.cyberxredteam.org/health
```

**Expected response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2026-02-03T12:00:00Z"
}
```

---

## 🔐 Security

### Secrets Management

**Never commit secrets!** All secrets are stored in GitHub:

**View secrets:**
```bash
gh secret list
```

**Update secret:**
```bash
echo "new-value" | gh secret set SECRET_NAME
```

**Rotate secrets regularly:**
- Render API key: Every 90 days
- Database passwords: Every 180 days

### Access Control

**Environment protection:**
- Staging: No approval needed (auto-deploy)
- Production: Requires approval from designated reviewers
- Production-suspend: Requires approval

**GitHub permissions:**
- Only admins can modify workflows
- Only reviewers can approve production deployments
- All deployments are logged and auditable

---

## 🛠️ Troubleshooting

### Setup Script Fails

**Issue:** "gh: command not found"

**Solution:**
```bash
# Install GitHub CLI
brew install gh  # macOS
```

**Issue:** "Not authenticated"

**Solution:**
```bash
gh auth login
```

### Deployment Fails

**Issue:** "Service not found"

**Check:**
```bash
# Verify service ID is correct
gh secret list | grep RENDER_SERVICE_ID

# Test Render API
curl -H "Authorization: Bearer $RENDER_API_KEY" \
  https://api.render.com/v1/services/srv-XXX
```

**Issue:** "Database migration error"

**Debug:**
```bash
# Check DATABASE_URL
gh secret list | grep DATABASE_URL

# Test connection locally
export DATABASE_URL="..."
cd backend
alembic upgrade head
```

### Health Check Fails

**Issue:** Health endpoint returns 500/503

**Check:**
1. View Render logs for errors
2. Verify environment variables in Render
3. Check database connection
4. Try manual health check:
   ```bash
   curl -v https://events.cyberxredteam.org/health
   ```

### Can't Approve Deployment

**Issue:** No "Review deployments" button

**Solution:**
- Ensure you're added as a reviewer in environment settings
- Go to Settings → Environments → production → Add yourself

---

## 📚 Workflow Files

**Location:** `.github/workflows/`

**Files:**
1. `test.yml` - Run tests (called by other workflows)
2. `lint.yml` - Code quality checks
3. `deploy-staging.yml` - Auto-deploy to staging
4. `deploy-production.yml` - Deploy/resume/suspend production
5. `deploy.yml` - Original deployment workflow (legacy)

**Documentation:**
- `.github/workflows/environment-setup.md` - Detailed setup guide
- `GITHUB_ACTIONS_QUICKSTART.md` - This file
- `CI_CD_SETUP.md` - General CI/CD guide

---

## 🎓 Best Practices

### Development

1. **Always work in branches** - Never push directly to main
2. **Write tests** - PRs with tests are more likely to be approved
3. **Test on staging first** - Always verify on staging before production
4. **Use semantic versioning** - v1.0.0, v1.1.0, v2.0.0
5. **Write meaningful commits** - Help reviewers understand changes

### Deployment

1. **Tag releases properly:**
   ```bash
   git tag v1.0.0 -m "Release v1.0.0: Add VPN management"
   ```

2. **Test staging thoroughly** before production deployment

3. **Schedule production deploys** during low-traffic periods

4. **Have rollback plan** - Know how to restore from Supabase backup

5. **Monitor after deployment:**
   - Check health endpoint
   - Review logs for errors
   - Verify key features work

### Event Management

1. **Resume early** - 2 days before event (not last minute!)

2. **Verify health** - Always test after resuming

3. **Monitor during event** - Check logs periodically

4. **Suspend promptly** - 1 day after event to save costs

5. **Document issues** - Note any problems for next time

---

## ✅ Checklist

### Initial Setup
```
□ Install and authenticate gh CLI
□ Run setup-github-actions.sh script
□ Configure environment protection rules
□ Add reviewers to production environment
□ Disable auto-deploy on Render services
□ Test staging deployment (push to main)
□ Test production deployment (create tag)
□ Test resume action
□ Test suspend action
□ Document team deployment process
```

### Pre-Event
```
□ 2 days before: Resume production service
□ Verify service is running (health check)
□ Test critical functionality
□ Verify VPN config downloads work
□ Import any new participants
□ Send reminder emails
```

### Post-Event
```
□ 1 day after: Suspend production service
□ Verify service is suspended
□ Export any reports needed
□ Review deployment logs
□ Document any issues
```

---

## 🆘 Support

**GitHub Actions Issues:**
- Check workflow logs in Actions tab
- Review secrets configuration
- Verify environment protection rules

**Render Issues:**
- Check Render dashboard for errors
- View service logs
- Contact Render support if needed

**Supabase Issues:**
- Check Supabase dashboard
- Verify connection string
- Test database connection

**Need Help?**
- Review `.github/workflows/environment-setup.md`
- Check CI_CD_SETUP.md for detailed guide
- Contact team lead or DevOps

---

## 🎉 You're Ready!

Your CI/CD pipeline is configured and ready to use:

✅ Automatic staging deployments
✅ Approval-gated production deployments
✅ Resume/suspend production service
✅ Database backups before deployment
✅ Health checks after deployment
✅ Complete audit trail

**Start deploying!** 🚀

---

**Last Updated:** 2026-02-03
