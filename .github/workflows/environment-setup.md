# GitHub Actions Environment Setup Guide

Complete guide for configuring GitHub Actions workflows with staging and production environments.

---

## 🏗️ Architecture

```
┌──────────────┐
│ Push to main │
│ or develop   │
└──────┬───────┘
       │
       ├─────────────────┐
       ↓                 ↓
┌─────────────┐   ┌────────────┐
│ Run Tests   │   │ Code Lint  │
└──────┬──────┘   └─────┬──────┘
       │                │
       └────────┬───────┘
                │
                ↓
       ┌────────────────┐
       │ Deploy Staging │
       │ (Automatic)    │
       └────────┬───────┘
                │
         [Tag v* pushed?]
                │
                ↓ YES
       ┌────────────────┐
       │ Manual Approval│
       │   Required     │
       └────────┬───────┘
                │
                ↓
       ┌────────────────┐
       │ Backup Database│
       └────────┬───────┘
                │
                ↓
       ┌────────────────┐
       │Deploy Production│
       │ - Run migrations│
       │ - Health checks │
       │ - Smoke tests   │
       └────────────────┘
```

---

## 📋 Prerequisites

### 1. Two Render Services

Create two separate web services on Render:

**Staging Service:**
- Name: `cyberx-staging`
- Branch: `main` or `develop`
- Auto-deploy: Disabled (managed by GitHub Actions)
- Environment: Staging
- Domain: `staging.events.cyberxredteam.org`

**Production Service:**
- Name: `cyberx-production`
- Branch: `main`
- Auto-deploy: Disabled (managed by GitHub Actions)
- Environment: Production
- Domain: `events.cyberxredteam.org`

### 2. Two Supabase Projects

Create two separate Supabase projects:

**Staging Database:**
- Name: `cyberx-events-staging`
- Plan: Free or Pro (Free is sufficient for testing)
- Region: Same as Render staging

**Production Database:**
- Name: `cyberx-events-production`
- Plan: Pro (for PITR backups)
- Region: Same as Render production

### 3. Render API Key

1. Go to [Render Account Settings](https://dashboard.render.com/account)
2. Navigate to **API Keys**
3. Click **Create API Key**
4. Name: `GitHub Actions`
5. Copy the key (save securely!)

### 4. Supabase Access Token (Optional)

Only needed if using Supabase API for backups:

1. Go to [Supabase Account Settings](https://supabase.com/dashboard/account/tokens)
2. Click **Generate new token**
3. Name: `GitHub Actions`
4. Copy the token

---

## 🔐 GitHub Secrets Configuration

### Navigate to Secrets

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**

### Required Secrets

#### Render Secrets

```
RENDER_API_KEY
Description: Render API key for deployments
Value: rnd_xxxxxxxxxxxxxxxxxxxxxx
Where to get: Render Dashboard → Account → API Keys

STAGING_RENDER_SERVICE_ID
Description: Staging service ID
Value: srv-xxxxxxxxxxxxxxxxxxxxxx
Where to get: Render Dashboard → Staging Service → Settings → Service ID

PRODUCTION_RENDER_SERVICE_ID
Description: Production service ID
Value: srv-xxxxxxxxxxxxxxxxxxxxxx
Where to get: Render Dashboard → Production Service → Settings → Service ID
```

#### Database Secrets

```
STAGING_DATABASE_URL
Description: Staging Supabase connection string
Value: postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
Where to get: Supabase Staging Project → Settings → Database → Connection String
Note: Add "+asyncpg" after "postgresql"

PRODUCTION_DATABASE_URL
Description: Production Supabase connection string
Value: postgresql+asyncpg://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
Where to get: Supabase Production Project → Settings → Database → Connection String
Note: Add "+asyncpg" after "postgresql"
```

#### Supabase Secrets (Optional - for automated backups)

```
PRODUCTION_SUPABASE_PROJECT_REF
Description: Production project reference ID
Value: xxxxxxxxxxxxx
Where to get: Supabase Dashboard → Project Settings → General → Reference ID

SUPABASE_ACCESS_TOKEN
Description: Supabase API access token
Value: sbp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Where to get: Supabase Account → Access Tokens
```

### Getting Render Service ID

```bash
# Method 1: From URL
# When viewing your service: https://dashboard.render.com/web/srv-XXXXXXXX
# The srv-XXXXXXXX is your service ID

# Method 2: From Render Dashboard
# Service → Settings → Service Details → Service ID

# Method 3: Via API
curl -H "Authorization: Bearer $RENDER_API_KEY" \
  https://api.render.com/v1/services | jq '.[] | {name: .service.name, id: .service.id}'
```

---

## 🌍 GitHub Environments

Configure two environments with protection rules:

### 1. Staging Environment

1. Go to **Settings** → **Environments**
2. Click **New environment**
3. Name: `staging`
4. **Deployment protection rules:**
   - ❌ No required reviewers
   - ❌ No wait timer
   - ✅ Allow administrators to bypass
5. **Environment secrets:** (optional, can use repo secrets)
   - Can override repo secrets if needed
6. **Environment URL:** `https://staging.events.cyberxredteam.org`

### 2. Production Environment

1. Click **New environment**
2. Name: `production`
3. **Deployment protection rules:**
   - ✅ Required reviewers: Select yourself + team members
   - ⏱️ Wait timer: 0 minutes (optional: add 5 min for review)
   - ✅ Allow administrators to bypass (optional)
4. **Environment secrets:** (optional)
5. **Environment URL:** `https://events.cyberxredteam.org`

### 3. Production-Suspend Environment (Optional)

For suspend action approval:

1. Name: `production-suspend`
2. **Required reviewers:** Add reviewer(s)
3. Purpose: Requires approval before suspending production

---

## 🚀 Workflow Usage

### Automatic Staging Deployment

**Trigger:** Push to `main` or `develop` branch

```bash
# Make changes
git add .
git commit -m "Add new feature"
git push origin main

# GitHub Actions automatically:
# 1. Runs tests
# 2. Runs linters
# 3. Deploys to staging
# 4. Runs health checks
```

**Monitor:**
- Go to **Actions** tab
- View `Deploy to Staging` workflow
- Check logs for each step

### Manual Staging Deployment

**Via GitHub UI:**

1. Go to **Actions** → **Deploy to Staging**
2. Click **Run workflow**
3. Select branch
4. Click **Run workflow**

### Production Deployment (Tag-based)

**Trigger:** Push a version tag

```bash
# Create and push tag
git tag v1.0.0
git push origin v1.0.0

# GitHub Actions:
# 1. Runs tests
# 2. Creates database backup
# 3. WAITS for manual approval ⏸️
# 4. After approval:
#    - Resumes service if suspended
#    - Runs migrations
#    - Deploys to production
#    - Runs health checks
#    - Creates GitHub release
```

**Approve deployment:**

1. Go to **Actions** tab
2. Find deployment workflow
3. Click **Review deployments**
4. Select `production` environment
5. Click **Approve and deploy**

### Manual Production Deployment

**Via GitHub UI:**

1. Go to **Actions** → **Deploy to Production**
2. Click **Run workflow**
3. Select action: **deploy**
4. Click **Run workflow**
5. Wait for approval request
6. Approve deployment

### Resume Production Service

**Use before event starts:**

1. Go to **Actions** → **Deploy to Production**
2. Click **Run workflow**
3. Select action: **resume**
4. Check **skip_tests** (optional)
5. Click **Run workflow**

**Approve:**
- Requires approval from production environment reviewers

**What it does:**
- Resumes suspended Render service
- Waits for service to start (~2-3 minutes)
- Runs health checks
- Billing resumes

### Suspend Production Service

**Use after event ends:**

1. Go to **Actions** → **Deploy to Production**
2. Click **Run workflow**
3. Select action: **suspend**
4. Check **skip_tests**
5. Click **Run workflow**

**Approve:**
- Requires approval from production-suspend environment

**What it does:**
- Suspends Render service
- Stops billing
- Database remains active (Supabase)
- Can resume anytime

---

## 🔄 Typical Event Workflow

### Pre-Event (2 days before)

```bash
# Resume production service
# Via GitHub UI:
Actions → Deploy to Production → Run workflow
Action: resume
Skip tests: ✓
Approve → Wait 3 minutes
```

**Verify:**
```bash
curl https://events.cyberxredteam.org/health
```

### During Event Development

```bash
# Work on feature branch
git checkout -b feature/new-feature
# Make changes
git add .
git commit -m "Add feature"
git push origin feature/new-feature

# Create PR to main
# Tests run automatically

# After PR merge to main
# Staging deploys automatically
```

### Before Event (Deploy new version)

```bash
# Test on staging first
# Then create production release

git tag v1.0.0
git push origin v1.0.0

# Approve deployment when ready
# Monitor deployment in Actions tab
```

### Post-Event (1 day after)

```bash
# Suspend production service
# Via GitHub UI:
Actions → Deploy to Production → Run workflow
Action: suspend
Skip tests: ✓
Approve → Service suspends immediately
```

---

## 📊 Monitoring Deployments

### View Deployment Status

**GitHub Actions:**
- Go to **Actions** tab
- View running/completed workflows
- Check logs for each step

**Render Dashboard:**
- View deployment history
- Check service status
- View logs in real-time

**Health Checks:**
```bash
# Staging
curl https://staging.events.cyberxredteam.org/health

# Production
curl https://events.cyberxredteam.org/health
```

### Deployment Notifications

GitHub Actions will show:
- ✅ Success notifications
- ❌ Failure notifications
- 📊 Deployment summaries

**Optional:** Set up Slack/Discord notifications:
- Add notification steps to workflows
- Use GitHub Actions marketplace actions
- Or webhook notifications

---

## 🔍 Troubleshooting

### Workflow Fails: "Service not found"

**Cause:** Incorrect `RENDER_SERVICE_ID`

**Fix:**
1. Get correct service ID from Render dashboard
2. Update GitHub secret
3. Re-run workflow

### Workflow Fails: "Database migration error"

**Cause:** Database connection issue or migration conflict

**Fix:**
```bash
# Test connection locally
export DATABASE_URL="$STAGING_DATABASE_URL"
cd backend
alembic upgrade head

# If fails, check:
# 1. DATABASE_URL is correct
# 2. Database is accessible
# 3. No conflicting migrations
```

### Deployment Stuck: "Waiting for approval"

**Normal:** Production deployments require manual approval

**Action:**
1. Go to Actions tab
2. Click on running workflow
3. Click "Review deployments"
4. Approve or reject

### Health Check Fails After Deployment

**Cause:** Service not fully started or configuration issue

**Debug:**
1. Check Render logs for errors
2. Verify environment variables
3. Test database connection
4. Check `/health` endpoint manually

**Fix:**
```bash
# Check Render logs
# Render Dashboard → Service → Logs

# Test health endpoint
curl -v https://events.cyberxredteam.org/health
```

### Resume/Suspend Not Working

**Cause:** API key permissions or service ID incorrect

**Fix:**
1. Verify `RENDER_API_KEY` is correct
2. Verify service ID matches
3. Check Render API status
4. Test API call manually:
```bash
# Test resume
curl -X POST \
  "https://api.render.com/v1/services/srv-XXX/resume" \
  -H "Authorization: Bearer $RENDER_API_KEY"
```

---

## 🔐 Security Best Practices

### Secrets Management

1. **Rotate secrets regularly:**
   - Render API keys: Every 90 days
   - Database passwords: Every 180 days
   - Supabase tokens: Every 90 days

2. **Least privilege:**
   - GitHub Actions only needs deploy permission
   - Use separate API keys for CI/CD
   - Limit environment access

3. **Audit trail:**
   - GitHub tracks all deployments
   - Review deployment logs regularly
   - Monitor failed deployments

### Environment Protection

1. **Production environment:**
   - Always require approval
   - Limit reviewers to senior team
   - Enable audit logging

2. **Staging environment:**
   - Can be less restrictive
   - Good for testing workflows
   - Mirror production config

3. **Secrets:**
   - Never log secrets
   - Use GitHub's secret masking
   - Verify secrets in use

---

## 📈 Advanced Configuration

### Custom Deployment Triggers

Edit workflows to add custom triggers:

```yaml
on:
  push:
    branches: [ main, develop, feature/* ]  # Add more branches
  schedule:
    - cron: '0 0 * * 0'  # Weekly deployment
  workflow_dispatch:      # Manual trigger
```

### Slack Notifications

Add Slack notifications to workflows:

```yaml
- name: Notify Slack
  if: always()
  uses: slackapi/slack-github-action@v1
  with:
    payload: |
      {
        "text": "Deployment ${{ job.status }}: ${{ github.ref_name }}"
      }
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

### Rollback Automation

Add automatic rollback on health check failure:

```yaml
- name: Rollback on failure
  if: failure()
  run: |
    # Trigger previous deployment
    # Or restore from backup
```

---

## ✅ Setup Checklist

### Initial Setup
```
□ Create staging Render service
□ Create production Render service
□ Create staging Supabase project
□ Create production Supabase project
□ Generate Render API key
□ Generate Supabase access token (optional)
□ Add all GitHub secrets
□ Configure GitHub environments
□ Set up environment protection rules
□ Add team members as reviewers
□ Test staging deployment
□ Test production deployment
□ Test resume/suspend actions
```

### Before First Production Deployment
```
□ Test all workflows on staging
□ Verify database migrations work
□ Test health checks
□ Verify environment variables
□ Review deployment logs
□ Set up monitoring
□ Document deployment process
□ Train team on approval process
```

### Regular Maintenance
```
□ Rotate API keys (quarterly)
□ Review deployment logs (weekly)
□ Update dependencies (monthly)
□ Test rollback procedure (quarterly)
□ Review team access (quarterly)
□ Audit secrets usage (quarterly)
```

---

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Render API Documentation](https://render.com/docs/api)
- [Supabase API Documentation](https://supabase.com/docs/reference/api)
- [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments)

---

**Ready to deploy?** Follow the setup checklist above!

**Last Updated:** 2026-02-03
