# CI/CD Setup Guide

Complete guide for setting up Continuous Integration and Continuous Deployment for the CyberX Event Management System using GitHub Actions.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [GitHub Actions Workflows](#github-actions-workflows)
- [Setting Up GitHub Secrets](#setting-up-github-secrets)
- [Branch Strategy](#branch-strategy)
- [Deployment Process](#deployment-process)
- [Monitoring and Rollback](#monitoring-and-rollback)

---

## Overview

The CI/CD pipeline is built using GitHub Actions and consists of three main workflows:

1. **Test Workflow** (`test.yml`) - Runs on every push and PR
2. **Lint Workflow** (`lint.yml`) - Code quality checks on every push and PR
3. **Deploy Workflow** (`deploy.yml`) - Deploys to staging/production

### Pipeline Architecture

```
┌─────────────┐
│ Git Push/PR │
└──────┬──────┘
       │
       ├─────────────┐
       │             │
       ▼             ▼
┌──────────┐  ┌──────────┐
│   Test   │  │   Lint   │
│ Workflow │  │ Workflow │
└─────┬────┘  └──────────┘
      │
      │ (on main branch)
      ▼
┌──────────┐
│  Build   │
│ Artifact │
└─────┬────┘
      │
      ├─────────────┐
      │             │
      ▼             ▼
┌──────────┐  ┌────────────┐
│ Staging  │  │ Production │
│ Deploy   │  │   Deploy   │
└──────────┘  └────────────┘
```

---

## Prerequisites

### Required Tools

1. **GitHub Repository**
   - Repository with admin access
   - GitHub Actions enabled

2. **Server Infrastructure**
   - Staging server (optional but recommended)
   - Production server
   - SSH access to both servers
   - Docker installed on servers (or systemd service)

3. **Third-Party Services**
   - SendGrid account (for email testing)
   - Codecov account (optional, for coverage reports)

### Server Requirements

**Minimum per server:**
- Ubuntu 20.04 LTS or newer
- 2 CPU cores
- 4GB RAM
- 20GB disk space
- Docker & Docker Compose installed
- PostgreSQL 15+ (via Docker or native)

---

## GitHub Actions Workflows

### 1. Test Workflow (`.github/workflows/test.yml`)

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`

**Jobs:**
- **test**: Runs pytest with coverage on Python 3.11 and 3.12
- **test-integration**: Runs integration tests

**Features:**
- Matrix testing across Python versions
- PostgreSQL and Redis services
- Code coverage reporting
- Test result artifacts
- Codecov integration
- PR comments with coverage

**Configuration:**
```yaml
# Required for this workflow
# No secrets needed for basic testing
# Optional: CODECOV_TOKEN for coverage uploads
```

### 2. Lint Workflow (`.github/workflows/lint.yml`)

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`

**Jobs:**
- **lint**: Ruff linter and formatter checks
- **complexity**: Code complexity analysis with radon
- **dependencies**: Security scan with pip-audit
- **docker**: Docker Compose validation
- **documentation**: Documentation completeness check

**Features:**
- Code style enforcement
- Type checking with mypy
- Security vulnerability scanning
- Cyclomatic complexity checks
- Maintainability index
- Docker configuration validation

**Configuration:**
```yaml
# No secrets required
# All checks run on public code
```

### 3. Deploy Workflow (`.github/workflows/deploy.yml`)

**Triggers:**
- Push to `main` branch (staging)
- Git tags starting with `v*` (production)
- Manual workflow dispatch

**Jobs:**
- **build**: Creates deployment package
- **deploy-staging**: Deploys to staging environment
- **deploy-production**: Deploys to production (with approval)
- **rollback**: Automatic rollback on failure

**Features:**
- Zero-downtime deployments
- Automatic database backups before deployment
- Health checks after deployment
- Smoke tests
- GitHub release creation
- Automatic rollback capability

---

## Setting Up GitHub Secrets

### Navigate to Repository Settings

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**

### Required Secrets

#### Staging Environment

```
STAGING_SSH_KEY
  Description: Private SSH key for staging server access
  Format: Full private key content (-----BEGIN OPENSSH PRIVATE KEY-----)
  Generation: ssh-keygen -t ed25519 -C "github-actions-staging"

STAGING_HOST
  Description: Staging server hostname or IP
  Example: staging.events.cyberxredteam.org

STAGING_USER
  Description: SSH username for staging server
  Example: deploy
```

#### Production Environment

```
PRODUCTION_SSH_KEY
  Description: Private SSH key for production server access
  Format: Full private key content
  Generation: ssh-keygen -t ed25519 -C "github-actions-production"

PRODUCTION_HOST
  Description: Production server hostname or IP
  Example: events.cyberxredteam.org

PRODUCTION_USER
  Description: SSH username for production server
  Example: deploy
```

#### Optional Secrets

```
CODECOV_TOKEN
  Description: Token for Codecov coverage uploads
  Get from: https://codecov.io/

GRAFANA_PASSWORD
  Description: Grafana admin password
  Note: Only needed if using monitoring stack
```

### Generating SSH Keys

```bash
# Generate key pair for GitHub Actions
ssh-keygen -t ed25519 -C "github-actions-deploy" -f github_deploy_key

# Copy public key to server
ssh-copy-id -i github_deploy_key.pub deploy@your-server.com

# Add private key to GitHub Secrets
cat github_deploy_key
# Copy the entire output including BEGIN and END lines
```

---

## Branch Strategy

### Recommended Git Flow

```
main (production)
  ↑
  └── develop (staging)
       ↑
       └── feature/* (development)
```

### Branch Policies

**main branch:**
- Protected branch
- Requires PR reviews
- Status checks must pass
- Deploys to production on merge
- Tagged releases (v1.0.0, v1.1.0, etc.)

**develop branch:**
- Integration branch
- Deploys to staging on push
- Used for testing before production

**feature/* branches:**
- Short-lived development branches
- PR to develop when complete
- Naming: feature/add-vpn-management

### Workflow Example

```bash
# Create feature branch
git checkout -b feature/new-feature develop

# Make changes and commit
git add .
git commit -m "Add new feature"

# Push and create PR to develop
git push origin feature/new-feature

# After review, merge to develop (triggers staging deployment)

# After testing on staging, create PR from develop to main

# After review, merge to main (triggers production deployment)
```

---

## Deployment Process

### Automatic Deployments

#### Staging Deployment

**Trigger:** Push to `main` branch

**Process:**
1. Code is pushed to `main`
2. Test and lint workflows run
3. If tests pass, build job creates deployment package
4. Deploy-staging job runs:
   - Connects to staging server via SSH
   - Uploads deployment package
   - Runs database migrations
   - Restarts application
   - Runs health checks
5. Smoke tests verify deployment
6. Notification sent (optional)

#### Production Deployment

**Trigger:** Git tag (e.g., `v1.0.0`)

**Process:**
1. Create and push tag: `git tag v1.0.0 && git push origin v1.0.0`
2. Test and lint workflows run
3. Build job creates deployment package
4. **Manual approval required** (GitHub environment protection)
5. Deploy-production job runs:
   - Creates backup of current state
   - Connects to production server via SSH
   - Uploads deployment package
   - Runs database migrations
   - Restarts application (zero-downtime reload)
   - Runs health checks
6. Production smoke tests verify deployment
7. GitHub release created automatically
8. Notification sent (optional)

### Manual Deployment

You can also trigger deployments manually:

1. Go to **Actions** tab in GitHub
2. Select **Deploy** workflow
3. Click **Run workflow**
4. Choose environment (staging or production)
5. Click **Run workflow**

---

## Server Setup

### Prepare Deployment Server

```bash
# 1. Create deployment user
sudo useradd -m -s /bin/bash deploy
sudo usermod -aG docker deploy

# 2. Create application directory
sudo mkdir -p /opt/cyberx-event-mgmt
sudo chown deploy:deploy /opt/cyberx-event-mgmt

# 3. Set up SSH access for GitHub Actions
sudo -u deploy mkdir -p /home/deploy/.ssh
sudo -u deploy touch /home/deploy/.ssh/authorized_keys
sudo -u deploy chmod 700 /home/deploy/.ssh
sudo -u deploy chmod 600 /home/deploy/.ssh/authorized_keys

# Add GitHub Actions public key to authorized_keys
sudo -u deploy nano /home/deploy/.ssh/authorized_keys

# 4. Install Docker (if not already installed)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker deploy

# 5. Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 6. Set up systemd service (optional)
sudo cp /opt/cyberx-event-mgmt/scripts/cyberx-event-mgmt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cyberx-event-mgmt
```

### Environment Configuration

Create `.env` file on each server:

```bash
# On staging server
sudo -u deploy nano /opt/cyberx-event-mgmt/backend/.env

# On production server
sudo -u deploy nano /opt/cyberx-event-mgmt/backend/.env
```

Use [.env.production.example](/.env.production.example) as a template.

---

## Monitoring and Rollback

### Monitoring Deployment

**Check workflow status:**
```bash
# View recent workflow runs
gh run list --workflow=deploy.yml

# View logs for specific run
gh run view <run-id> --log
```

**Monitor application:**
```bash
# SSH to server
ssh deploy@your-server.com

# Check application status
systemctl status cyberx-event-mgmt
# or
docker-compose ps

# Check logs
docker-compose logs -f app

# Run health check
curl http://localhost:8000/health
```

### Manual Rollback

If deployment fails or issues are detected:

**Option 1: Automatic Rollback (on deployment failure)**
The pipeline automatically rolls back if health checks fail.

**Option 2: Manual Rollback to Previous Backup**

```bash
# SSH to server
ssh deploy@your-server.com

# Find available backups
ls -lht /opt/backups/cyberx/

# Rollback to specific backup
cd /opt/cyberx-event-mgmt
./scripts/rollback.sh <backup_date>

# Example
./scripts/rollback.sh 20260203_120000
```

**Option 3: Rollback via Git**

```bash
# Revert to previous commit
git revert HEAD
git push origin main

# Or reset to previous tag
git reset --hard v1.0.0
git push --force origin main

# This will trigger a new deployment
```

---

## Troubleshooting

### Common Issues

#### SSH Connection Failed

**Symptoms:** Deployment fails with "Permission denied" or "Connection refused"

**Solutions:**
1. Verify SSH key in GitHub Secrets
2. Check public key is in server's `~/.ssh/authorized_keys`
3. Test SSH connection: `ssh -i <key> deploy@server`
4. Check server firewall allows SSH (port 22)

#### Database Migration Failed

**Symptoms:** Alembic upgrade fails during deployment

**Solutions:**
1. Check database is running: `docker-compose ps postgres`
2. Verify DATABASE_URL in .env
3. Check migration files for errors
4. Manually run migrations: `alembic upgrade head`
5. Rollback to previous version if needed

#### Health Check Failed

**Symptoms:** Deployment succeeds but health checks fail

**Solutions:**
1. Check application logs: `docker-compose logs -f app`
2. Verify all services are running: `docker-compose ps`
3. Test health endpoint: `curl http://localhost:8000/health`
4. Check database connection
5. Verify .env configuration

#### Deployment Timeout

**Symptoms:** Deployment hangs or times out

**Solutions:**
1. Increase timeout in workflow file
2. Check server resources (CPU, memory, disk)
3. Check for slow database migrations
4. Verify network connectivity

---

## Best Practices

### Development Workflow

1. **Always work in feature branches**
2. **Write tests for new features**
3. **Run tests locally before pushing**
4. **Keep PRs small and focused**
5. **Use meaningful commit messages**

### Deployment Workflow

1. **Test on staging first**
2. **Deploy during low-traffic periods**
3. **Monitor application after deployment**
4. **Have rollback plan ready**
5. **Communicate deployments to team**

### Security

1. **Rotate SSH keys regularly**
2. **Use separate keys for staging/production**
3. **Never commit secrets to repository**
4. **Review security scan results**
5. **Keep dependencies up to date**

---

## Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [PostgreSQL Backup and Restore](https://www.postgresql.org/docs/current/backup.html)

---

## Support

For issues with CI/CD setup:
1. Check GitHub Actions logs
2. Review this documentation
3. Contact DevOps team
4. Create issue in repository

---

**Last Updated:** 2026-02-03
**Version:** 1.0.0
