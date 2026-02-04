# Render Environment Configuration Answers File
# Copy this file to render-env-answers.sh and fill in your values
# Usage: ./setup-render-env-cli.sh render-env-answers.sh

# ============================================================================
# SENDGRID CONFIGURATION
# ============================================================================
SENDGRID_API_KEY="SG.your_sendgrid_api_key_here"
SENDGRID_FROM_EMAIL="noreply@cyberxredteam.org"
SENDGRID_FROM_NAME="CyberX Red Team"

# ============================================================================
# VPN CONFIGURATION
# ============================================================================
VPN_SERVER_PUBLIC_KEY="your_wireguard_public_key_here"
VPN_SERVER_ENDPOINT="vpn.cyberxredteam.org:51820"
VPN_DNS_SERVERS="10.20.200.1"
VPN_ALLOWED_IPS="10.0.0.0/8,fd00:a::/32"

# ============================================================================
# APPLICATION CONFIGURATION
# ============================================================================
SESSION_EXPIRY_HOURS="24"
BULK_EMAIL_INTERVAL_MINUTES="45"

# ============================================================================
# REMINDER CONFIGURATION
# ============================================================================
REMINDER_1_DAYS_AFTER_INVITE="7"
REMINDER_1_MIN_DAYS_BEFORE_EVENT="14"
REMINDER_2_DAYS_AFTER_INVITE="14"
REMINDER_2_MIN_DAYS_BEFORE_EVENT="7"
REMINDER_3_DAYS_BEFORE_EVENT="3"
REMINDER_CHECK_INTERVAL_HOURS="24"

# ============================================================================
# RENDER SERVICE CONFIGURATION
# ============================================================================
STAGING_SERVICE_ID="srv-your-staging-service-id"
PRODUCTION_SERVICE_ID="srv-your-production-service-id"
STAGING_URL="https://staging.events.cyberxredteam.org"
PRODUCTION_URL="https://events.cyberxredteam.org"

# ============================================================================
# RENDER API KEY
# ============================================================================
# Get from: https://dashboard.render.com/account/api-keys
RENDER_API_KEY="rnd_your_render_api_key_here"

# ============================================================================
# NOTES
# ============================================================================
# - Security keys (SECRET_KEY, CSRF_SECRET_KEY, ENCRYPTION_KEY) are always
#   generated fresh each time the script runs for security
# - ALLOWED_HOSTS is automatically derived from STAGING_URL and PRODUCTION_URL
# - All values above can be left commented out to use interactive prompts
# - Uncomment and set values you want to automate
