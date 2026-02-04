#!/bin/bash
#
# Render Environment Variables Setup Script
# Configures environment variables for Render services using the Render API
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}Render Environment Setup Script${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check for required tools
if ! command -v curl &> /dev/null; then
    echo -e "${RED}❌ curl is required but not installed${NC}"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo -e "${RED}❌ jq is required but not installed${NC}"
    echo "Install with: brew install jq"
    exit 1
fi

echo -e "${GREEN}✅ Required tools installed${NC}"
echo ""

# =============================================================================
# Step 1: Get Render API Credentials
# =============================================================================

echo -e "${BLUE}Step 1: Render API Configuration${NC}"
echo ""

echo -e "${YELLOW}Render API Key${NC}"
echo "Get it from: https://dashboard.render.com/account/api-keys"
read -sp "RENDER_API_KEY: " RENDER_API_KEY
echo ""
echo ""

if [[ ! $RENDER_API_KEY =~ ^rnd_ ]]; then
    echo -e "${RED}❌ Invalid Render API key format (should start with 'rnd_')${NC}"
    exit 1
fi

# =============================================================================
# Step 2: Select Environment
# =============================================================================

echo -e "${BLUE}Step 2: Select Environment${NC}"
echo ""
echo "Which environment do you want to configure?"
echo "  1) Staging"
echo "  2) Production"
echo "  3) Both"
echo ""
read -p "Selection (1-3): " ENV_SELECTION

case $ENV_SELECTION in
    1)
        CONFIGURE_STAGING=true
        CONFIGURE_PRODUCTION=false
        ;;
    2)
        CONFIGURE_STAGING=false
        CONFIGURE_PRODUCTION=true
        ;;
    3)
        CONFIGURE_STAGING=true
        CONFIGURE_PRODUCTION=true
        ;;
    *)
        echo -e "${RED}❌ Invalid selection${NC}"
        exit 1
        ;;
esac

# =============================================================================
# Step 3: Get Service IDs
# =============================================================================

echo ""
echo -e "${BLUE}Step 3: Render Service IDs${NC}"
echo ""

if [ "$CONFIGURE_STAGING" = true ]; then
    echo -e "${YELLOW}Staging Service ID${NC}"
    echo "Get it from: Render Dashboard → Staging Service → Settings"
    read -p "STAGING_SERVICE_ID (srv-xxx): " STAGING_SERVICE_ID

    if [[ ! $STAGING_SERVICE_ID =~ ^srv- ]]; then
        echo -e "${RED}❌ Invalid service ID format (should start with 'srv-')${NC}"
        exit 1
    fi
fi

if [ "$CONFIGURE_PRODUCTION" = true ]; then
    echo ""
    echo -e "${YELLOW}Production Service ID${NC}"
    echo "Get it from: Render Dashboard → Production Service → Settings"
    read -p "PRODUCTION_SERVICE_ID (srv-xxx): " PRODUCTION_SERVICE_ID

    if [[ ! $PRODUCTION_SERVICE_ID =~ ^srv- ]]; then
        echo -e "${RED}❌ Invalid service ID format (should start with 'srv-')${NC}"
        exit 1
    fi
fi

# =============================================================================
# Step 4: Collect Environment Variables
# =============================================================================

echo ""
echo -e "${BLUE}Step 4: Application Configuration${NC}"
echo ""

# Security Keys (auto-generated)
echo -e "${GREEN}Generating secure keys...${NC}"
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
CSRF_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
echo "✅ Secure keys generated"
echo ""

# SendGrid Configuration
echo -e "${YELLOW}SendGrid Email Configuration${NC}"
echo "Get API key from: https://app.sendgrid.com/settings/api_keys"
read -sp "SENDGRID_API_KEY: " SENDGRID_API_KEY
echo ""
read -p "SENDGRID_FROM_EMAIL (e.g., noreply@cyberxredteam.org): " SENDGRID_FROM_EMAIL
read -p "SENDGRID_FROM_NAME (e.g., CyberX Red Team): " SENDGRID_FROM_NAME
echo ""

# VPN Configuration
echo -e "${YELLOW}VPN Configuration${NC}"
echo "WireGuard server details:"
read -p "VPN_SERVER_PUBLIC_KEY: " VPN_SERVER_PUBLIC_KEY
read -p "VPN_SERVER_ENDPOINT (e.g., vpn.cyberxredteam.org:51820): " VPN_SERVER_ENDPOINT
read -p "VPN_DNS_SERVERS (default: 10.20.200.1): " VPN_DNS_SERVERS
VPN_DNS_SERVERS=${VPN_DNS_SERVERS:-10.20.200.1}
read -p "VPN_ALLOWED_IPS (default: 10.0.0.0/8): " VPN_ALLOWED_IPS
VPN_ALLOWED_IPS=${VPN_ALLOWED_IPS:-10.0.0.0/8}
echo ""

# Domain Configuration
if [ "$CONFIGURE_STAGING" = true ]; then
    echo -e "${YELLOW}Staging Domain${NC}"
    read -p "STAGING_FRONTEND_URL (e.g., https://staging.events.cyberxredteam.org): " STAGING_FRONTEND_URL
    STAGING_ALLOWED_HOSTS=$(echo "$STAGING_FRONTEND_URL" | sed 's|https://||' | sed 's|http://||')
fi

if [ "$CONFIGURE_PRODUCTION" = true ]; then
    echo ""
    echo -e "${YELLOW}Production Domain${NC}"
    read -p "PRODUCTION_FRONTEND_URL (e.g., https://events.cyberxredteam.org): " PRODUCTION_FRONTEND_URL
    PRODUCTION_ALLOWED_HOSTS=$(echo "$PRODUCTION_FRONTEND_URL" | sed 's|https://||' | sed 's|http://||')
fi

# =============================================================================
# Step 5: Set Environment Variables via Render API
# =============================================================================

echo ""
echo -e "${BLUE}Step 5: Configuring Render Services${NC}"
echo ""

# Function to set environment variable
set_render_env() {
    local service_id=$1
    local key=$2
    local value=$3
    local env_name=$4

    echo "Setting ${key} for ${env_name}..."

    RESPONSE=$(curl -s -X PUT \
        "https://api.render.com/v1/services/${service_id}/env-vars/${key}" \
        -H "Authorization: Bearer ${RENDER_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"value\":\"${value}\"}")

    if echo "$RESPONSE" | grep -q "error"; then
        echo -e "${YELLOW}⚠️  Could not set ${key} (may need to be created first)${NC}"

        # Try creating instead of updating
        RESPONSE=$(curl -s -X POST \
            "https://api.render.com/v1/services/${service_id}/env-vars" \
            -H "Authorization: Bearer ${RENDER_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "[{\"key\":\"${key}\",\"value\":\"${value}\"}]")

        if echo "$RESPONSE" | grep -q "error"; then
            echo -e "${RED}❌ Failed to set ${key}${NC}"
            return 1
        fi
    fi

    echo -e "${GREEN}✅ ${key} set${NC}"
}

# Configure Staging
if [ "$CONFIGURE_STAGING" = true ]; then
    echo -e "${BLUE}Configuring Staging Service...${NC}"
    echo ""

    set_render_env "$STAGING_SERVICE_ID" "SECRET_KEY" "$SECRET_KEY" "staging"
    set_render_env "$STAGING_SERVICE_ID" "CSRF_SECRET_KEY" "$CSRF_SECRET_KEY" "staging"
    set_render_env "$STAGING_SERVICE_ID" "ENCRYPTION_KEY" "$ENCRYPTION_KEY" "staging"
    set_render_env "$STAGING_SERVICE_ID" "DEBUG" "False" "staging"
    set_render_env "$STAGING_SERVICE_ID" "FRONTEND_URL" "$STAGING_FRONTEND_URL" "staging"
    set_render_env "$STAGING_SERVICE_ID" "ALLOWED_HOSTS" "$STAGING_ALLOWED_HOSTS" "staging"
    set_render_env "$STAGING_SERVICE_ID" "SENDGRID_API_KEY" "$SENDGRID_API_KEY" "staging"
    set_render_env "$STAGING_SERVICE_ID" "SENDGRID_FROM_EMAIL" "$SENDGRID_FROM_EMAIL" "staging"
    set_render_env "$STAGING_SERVICE_ID" "SENDGRID_FROM_NAME" "$SENDGRID_FROM_NAME" "staging"
    set_render_env "$STAGING_SERVICE_ID" "SENDGRID_SANDBOX_MODE" "true" "staging"
    set_render_env "$STAGING_SERVICE_ID" "VPN_SERVER_PUBLIC_KEY" "$VPN_SERVER_PUBLIC_KEY" "staging"
    set_render_env "$STAGING_SERVICE_ID" "VPN_SERVER_ENDPOINT" "$VPN_SERVER_ENDPOINT" "staging"
    set_render_env "$STAGING_SERVICE_ID" "VPN_DNS_SERVERS" "$VPN_DNS_SERVERS" "staging"
    set_render_env "$STAGING_SERVICE_ID" "VPN_ALLOWED_IPS" "$VPN_ALLOWED_IPS" "staging"

    echo ""
    echo -e "${GREEN}✅ Staging service configured${NC}"
fi

# Configure Production
if [ "$CONFIGURE_PRODUCTION" = true ]; then
    echo ""
    echo -e "${BLUE}Configuring Production Service...${NC}"
    echo ""

    set_render_env "$PRODUCTION_SERVICE_ID" "SECRET_KEY" "$SECRET_KEY" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "CSRF_SECRET_KEY" "$CSRF_SECRET_KEY" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "ENCRYPTION_KEY" "$ENCRYPTION_KEY" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "DEBUG" "False" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "FRONTEND_URL" "$PRODUCTION_FRONTEND_URL" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "ALLOWED_HOSTS" "$PRODUCTION_ALLOWED_HOSTS" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "SENDGRID_API_KEY" "$SENDGRID_API_KEY" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "SENDGRID_FROM_EMAIL" "$SENDGRID_FROM_EMAIL" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "SENDGRID_FROM_NAME" "$SENDGRID_FROM_NAME" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "SENDGRID_SANDBOX_MODE" "false" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "VPN_SERVER_PUBLIC_KEY" "$VPN_SERVER_PUBLIC_KEY" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "VPN_SERVER_ENDPOINT" "$VPN_SERVER_ENDPOINT" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "VPN_DNS_SERVERS" "$VPN_DNS_SERVERS" "production"
    set_render_env "$PRODUCTION_SERVICE_ID" "VPN_ALLOWED_IPS" "$VPN_ALLOWED_IPS" "production"

    echo ""
    echo -e "${GREEN}✅ Production service configured${NC}"
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${GREEN}✅ Render Environment Setup Complete!${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

echo -e "${YELLOW}What was configured:${NC}"
echo ""
if [ "$CONFIGURE_STAGING" = true ]; then
    echo "✅ Staging service (${STAGING_SERVICE_ID})"
fi
if [ "$CONFIGURE_PRODUCTION" = true ]; then
    echo "✅ Production service (${PRODUCTION_SERVICE_ID})"
fi
echo ""
echo "Environment variables set:"
echo "  - SECRET_KEY (auto-generated)"
echo "  - CSRF_SECRET_KEY (auto-generated)"
echo "  - ENCRYPTION_KEY (auto-generated)"
echo "  - DEBUG=False"
echo "  - FRONTEND_URL"
echo "  - ALLOWED_HOSTS"
echo "  - SendGrid configuration"
echo "  - VPN configuration"
echo ""

echo -e "${YELLOW}⚠️  Important Notes:${NC}"
echo ""
echo "1. DATABASE_URL is set separately in GitHub secrets and injected by CI/CD"
echo "2. Services will automatically redeploy with new environment variables"
echo "3. Check Render dashboard to verify all variables are set correctly"
echo "4. Staging uses SENDGRID_SANDBOX_MODE=true (no emails sent)"
echo "5. Production uses SENDGRID_SANDBOX_MODE=false (emails will be sent)"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Verify environment variables in Render Dashboard:"
echo "   https://dashboard.render.com"
echo ""
echo "2. Monitor service deployment:"
echo "   Services will redeploy automatically with new variables"
echo ""
echo "3. Test the application:"
if [ "$CONFIGURE_STAGING" = true ]; then
    echo "   curl ${STAGING_FRONTEND_URL}/health"
fi
if [ "$CONFIGURE_PRODUCTION" = true ]; then
    echo "   curl ${PRODUCTION_FRONTEND_URL}/health"
fi
echo ""

echo -e "${GREEN}Configuration complete! 🚀${NC}"
echo ""
