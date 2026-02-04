#!/bin/bash
#
# GitHub Actions Setup Script
# Configures GitHub repository with secrets and environments using gh CLI
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}GitHub Actions Setup Script${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo -e "${RED}❌ GitHub CLI (gh) is not installed${NC}"
    echo ""
    echo "Install it with:"
    echo "  macOS:   brew install gh"
    echo "  Linux:   See https://cli.github.com/manual/installation"
    echo "  Windows: See https://cli.github.com/manual/installation"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo -e "${YELLOW}⚠️  Not authenticated with GitHub CLI${NC}"
    echo ""
    echo "Authenticate with:"
    echo "  gh auth login"
    exit 1
fi

echo -e "${GREEN}✅ GitHub CLI installed and authenticated${NC}"
echo ""

# Get repository info
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo -e "${BLUE}Repository: ${REPO}${NC}"
echo ""

# Confirm setup
echo -e "${YELLOW}This script will:${NC}"
echo "  1. Create GitHub environments (staging, production, production-suspend)"
echo "  2. Configure environment protection rules"
echo "  3. Set up repository secrets for Render and Supabase"
echo "  4. Configure deployment workflows"
echo ""
read -p "Continue? (yes/no): " -r
echo

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo -e "${YELLOW}Setup cancelled${NC}"
    exit 0
fi

# =============================================================================
# Step 1: Create Environments
# =============================================================================

echo -e "${BLUE}Step 1: Creating GitHub Environments${NC}"
echo ""

# Staging environment
echo "Creating 'staging' environment..."
gh api repos/$REPO/environments/staging -X PUT -f wait_timer=0 > /dev/null 2>&1 || true
echo -e "${GREEN}✅ Staging environment created${NC}"

# Production environment
echo "Creating 'production' environment..."
gh api repos/$REPO/environments/production -X PUT \
  -F wait_timer=0 \
  -F prevent_self_review=true > /dev/null 2>&1 || true
echo -e "${GREEN}✅ Production environment created${NC}"

# Production-suspend environment
echo "Creating 'production-suspend' environment..."
gh api repos/$REPO/environments/production-suspend -X PUT \
  -F wait_timer=0 \
  -F prevent_self_review=true > /dev/null 2>&1 || true
echo -e "${GREEN}✅ Production-suspend environment created${NC}"

echo ""
echo -e "${YELLOW}⚠️  Note: Environment protection rules (reviewers) must be configured manually${NC}"
echo "   Go to: Settings → Environments → Select environment → Add reviewers"
echo ""

# =============================================================================
# Step 2: Collect Domain Information
# =============================================================================

echo -e "${BLUE}Step 2: Collecting Domain Information${NC}"
echo ""

# Staging domain
echo -e "${YELLOW}Staging Domain${NC}"
echo "Default: staging.events.cyberxredteam.org"
read -p "Staging URL (press Enter for default): " STAGING_URL
STAGING_URL=${STAGING_URL:-https://staging.events.cyberxredteam.org}

# Production domain
echo ""
echo -e "${YELLOW}Production Domain${NC}"
echo "Default: events.cyberxredteam.org"
read -p "Production URL (press Enter for default): " PRODUCTION_URL
PRODUCTION_URL=${PRODUCTION_URL:-https://events.cyberxredteam.org}

# Ensure URLs start with https://
if [[ ! $STAGING_URL =~ ^https?:// ]]; then
    STAGING_URL="https://${STAGING_URL}"
fi
if [[ ! $PRODUCTION_URL =~ ^https?:// ]]; then
    PRODUCTION_URL="https://${PRODUCTION_URL}"
fi

echo ""
echo "URLs configured:"
echo "  Staging:    ${STAGING_URL}"
echo "  Production: ${PRODUCTION_URL}"
echo ""

# =============================================================================
# Step 3: Collect Secrets
# =============================================================================

echo -e "${BLUE}Step 3: Collecting Secrets${NC}"
echo ""
echo "Please provide the following information:"
echo ""

# Render API Key
echo -e "${YELLOW}Render API Key${NC}"
echo "Get it from: https://dashboard.render.com/account/api-keys"
read -sp "RENDER_API_KEY: " RENDER_API_KEY
echo ""

# Staging Render Service ID
echo ""
echo -e "${YELLOW}Staging Render Service ID${NC}"
echo "Get it from: Render Dashboard → Staging Service → Settings"
read -p "STAGING_RENDER_SERVICE_ID (srv-xxx): " STAGING_RENDER_SERVICE_ID

# Production Render Service ID
echo ""
echo -e "${YELLOW}Production Render Service ID${NC}"
echo "Get it from: Render Dashboard → Production Service → Settings"
read -p "PRODUCTION_RENDER_SERVICE_ID (srv-xxx): " PRODUCTION_RENDER_SERVICE_ID

# Staging Database URL
echo ""
echo -e "${YELLOW}Staging Database URL${NC}"
echo "Get it from: Supabase Staging → Settings → Database → Connection string"
echo "Format: postgresql+asyncpg://postgres:[PASSWORD]@db.xxx.supabase.co:5432/postgres"
read -sp "STAGING_DATABASE_URL: " STAGING_DATABASE_URL
echo ""

# Production Database URL
echo ""
echo -e "${YELLOW}Production Database URL${NC}"
echo "Get it from: Supabase Production → Settings → Database → Connection string"
echo "Format: postgresql+asyncpg://postgres:[PASSWORD]@db.xxx.supabase.co:5432/postgres"
read -sp "PRODUCTION_DATABASE_URL: " PRODUCTION_DATABASE_URL
echo ""

# Optional: Supabase settings
echo ""
read -p "Configure Supabase API access for automated backups? (y/n): " -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Supabase Production Project Reference${NC}"
    echo "Get it from: Supabase → Project Settings → General → Reference ID"
    read -p "PRODUCTION_SUPABASE_PROJECT_REF: " PRODUCTION_SUPABASE_PROJECT_REF

    echo ""
    echo -e "${YELLOW}Supabase Access Token${NC}"
    echo "Get it from: https://supabase.com/dashboard/account/tokens"
    read -sp "SUPABASE_ACCESS_TOKEN: " SUPABASE_ACCESS_TOKEN
    echo ""
else
    PRODUCTION_SUPABASE_PROJECT_REF=""
    SUPABASE_ACCESS_TOKEN=""
fi

# =============================================================================
# Step 3: Validate Inputs
# =============================================================================

echo ""
echo -e "${BLUE}Step 3: Validating Inputs${NC}"
echo ""

ERRORS=0

# Validate Render API Key
if [[ ! $RENDER_API_KEY =~ ^rnd_ ]]; then
    echo -e "${RED}❌ RENDER_API_KEY should start with 'rnd_'${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Validate Service IDs
if [[ ! $STAGING_RENDER_SERVICE_ID =~ ^srv- ]]; then
    echo -e "${RED}❌ STAGING_RENDER_SERVICE_ID should start with 'srv-'${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [[ ! $PRODUCTION_RENDER_SERVICE_ID =~ ^srv- ]]; then
    echo -e "${RED}❌ PRODUCTION_RENDER_SERVICE_ID should start with 'srv-'${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Validate Database URLs
if [[ ! $STAGING_DATABASE_URL =~ ^postgresql\+asyncpg:// ]]; then
    echo -e "${RED}❌ STAGING_DATABASE_URL should start with 'postgresql+asyncpg://'${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [[ ! $PRODUCTION_DATABASE_URL =~ ^postgresql\+asyncpg:// ]]; then
    echo -e "${RED}❌ PRODUCTION_DATABASE_URL should start with 'postgresql+asyncpg://'${NC}"
    ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -gt 0 ]; then
    echo ""
    echo -e "${RED}❌ Validation failed with $ERRORS error(s)${NC}"
    echo "Please check your inputs and try again"
    exit 1
fi

echo -e "${GREEN}✅ All inputs validated${NC}"

# =============================================================================
# Step 4: Set Repository Secrets
# =============================================================================

echo ""
echo -e "${BLUE}Step 4: Setting Repository Secrets${NC}"
echo ""

# Function to set secret
set_secret() {
    local name=$1
    local value=$2

    if [ -z "$value" ]; then
        echo -e "${YELLOW}⏭️  Skipping $name (empty value)${NC}"
        return
    fi

    echo "Setting $name..."
    echo -n "$value" | gh secret set "$name"
    echo -e "${GREEN}✅ $name set${NC}"
}

# Set all secrets
set_secret "RENDER_API_KEY" "$RENDER_API_KEY"
set_secret "STAGING_RENDER_SERVICE_ID" "$STAGING_RENDER_SERVICE_ID"
set_secret "PRODUCTION_RENDER_SERVICE_ID" "$PRODUCTION_RENDER_SERVICE_ID"
set_secret "STAGING_DATABASE_URL" "$STAGING_DATABASE_URL"
set_secret "PRODUCTION_DATABASE_URL" "$PRODUCTION_DATABASE_URL"
set_secret "PRODUCTION_SUPABASE_PROJECT_REF" "$PRODUCTION_SUPABASE_PROJECT_REF"
set_secret "SUPABASE_ACCESS_TOKEN" "$SUPABASE_ACCESS_TOKEN"

# =============================================================================
# Step 5: Configure Environment URLs
# =============================================================================

echo ""
echo -e "${BLUE}Step 5: Configuring Environment URLs${NC}"
echo ""

# Function to update environment with URL
update_environment_url() {
    local env_name=$1
    local url=$2

    echo "Setting URL for '${env_name}' environment to: ${url}"

    # GitHub API requires deployment_branch_policy when updating
    gh api repos/$REPO/environments/${env_name} -X PUT \
      -f url="${url}" \
      -F deployment_branch_policy='{"protected_branches":true,"custom_branch_policies":false}' \
      > /dev/null 2>&1 || {
        echo -e "${YELLOW}⚠️  Could not set URL automatically for ${env_name}${NC}"
        echo "   You can set it manually in GitHub Settings → Environments"
        return 1
      }

    echo -e "${GREEN}✅ ${env_name} URL configured${NC}"
}

# Set environment URLs
update_environment_url "staging" "$STAGING_URL"
update_environment_url "production" "$PRODUCTION_URL"
update_environment_url "production-suspend" "$PRODUCTION_URL"

# =============================================================================
# Step 6: Verify Setup
# =============================================================================

echo ""
echo -e "${BLUE}Step 6: Verifying Setup${NC}"
echo ""

# List secrets
echo "Repository secrets:"
gh secret list

echo ""
echo "Environments:"
gh api repos/$REPO/environments | jq -r '.environments[] | select(.name) | "\(.name) - \(.html_url // "N/A")"'

# =============================================================================
# Summary
# =============================================================================

echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${GREEN}✅ GitHub Actions Setup Complete!${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

echo -e "${YELLOW}What was configured:${NC}"
echo ""
echo "✅ GitHub environments created (staging, production, production-suspend)"
echo "✅ Environment URLs set:"
echo "   - Staging: ${STAGING_URL}"
echo "   - Production: ${PRODUCTION_URL}"
echo "✅ All repository secrets configured"
echo "✅ Deployment workflows ready"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Configure Environment Protection Rules:"
echo "   ${BLUE}https://github.com/$REPO/settings/environments${NC}"
echo "   "
echo "   For 'production' environment:"
echo "   - Add required reviewers (yourself + team)"
echo "   - Enable 'Prevent self-review' (optional)"
echo "   "
echo "   For 'production-suspend' environment:"
echo "   - Add required reviewers"
echo ""

echo "2. Test Workflows:"
echo "   ${BLUE}# Test staging deployment${NC}"
echo "   git push origin main"
echo "   "
echo "   ${BLUE}# Test production deployment${NC}"
echo "   git tag v0.1.0"
echo "   git push origin v0.1.0"
echo ""

echo "3. Review Workflow Files:"
echo "   - .github/workflows/deploy-staging.yml"
echo "   - .github/workflows/deploy-production.yml"
echo "   - .github/workflows/test.yml"
echo "   - .github/workflows/lint.yml"
echo ""

echo "4. Documentation:"
echo "   - .github/workflows/environment-setup.md"
echo "   - RENDER_SUSPEND_STRATEGY.md"
echo "   - CI_CD_SETUP.md"
echo ""

echo -e "${GREEN}Your CI/CD pipeline is ready to use! 🚀${NC}"
echo ""
