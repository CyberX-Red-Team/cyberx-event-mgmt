#!/bin/bash

# Usage: ./setup-render-env-cli.sh [answers_file]
# If answers_file is provided, it will be sourced for configuration values

# Show help
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Render Environment Variables Setup Script"
    echo ""
    echo "Usage: $0 [answers_file]"
    echo ""
    echo "This script configures environment variables for Render staging and production services."
    echo ""
    echo "Options:"
    echo "  answers_file    Optional file containing configuration values"
    echo "                  See render-env-answers.example.sh for template"
    echo ""
    echo "Examples:"
    echo "  $0                              # Interactive mode"
    echo "  $0 render-env-answers.sh        # Use answers file"
    echo ""
    echo "The script will:"
    echo "  - Generate separate security keys for staging and production"
    echo "  - Prompt for configuration values (or use answers file)"
    echo "  - Set all environment variables via Render API"
    echo "  - Auto-derive ALLOWED_HOSTS from URLs"
    echo ""
    exit 0
fi

# Check if answers file provided
if [ -n "$1" ]; then
    if [ -f "$1" ]; then
        echo "Loading configuration from: $1"
        source "$1"
        echo "✅ Configuration loaded"
        echo ""
    else
        echo "Error: Answers file '$1' not found"
        exit 1
    fi
fi

# Generate secure keys - SEPARATE for staging and production
echo "Generating secure keys for STAGING and PRODUCTION..."
echo ""

echo "Staging Keys:"
STAGING_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
STAGING_CSRF_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
STAGING_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
echo "  STAGING_SECRET_KEY=$STAGING_SECRET_KEY"
echo "  STAGING_CSRF_SECRET_KEY=$STAGING_CSRF_SECRET_KEY"
echo "  STAGING_ENCRYPTION_KEY=$STAGING_ENCRYPTION_KEY"
echo ""

echo "Production Keys:"
PRODUCTION_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
PRODUCTION_CSRF_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
PRODUCTION_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
echo "  PRODUCTION_SECRET_KEY=$PRODUCTION_SECRET_KEY"
echo "  PRODUCTION_CSRF_SECRET_KEY=$PRODUCTION_CSRF_SECRET_KEY"
echo "  PRODUCTION_ENCRYPTION_KEY=$PRODUCTION_ENCRYPTION_KEY"
echo ""

echo "✅ Separate keys generated for staging and production"
echo ""

# Prompt for user inputs (skip if already set from answers file)
if [ -z "$SENDGRID_API_KEY" ]; then
    read -p "SendGrid API Key: " SENDGRID_API_KEY
fi

if [ -z "$SENDGRID_FROM_EMAIL" ]; then
    read -p "SendGrid From Email: " SENDGRID_FROM_EMAIL
fi

if [ -z "$SENDGRID_FROM_NAME" ]; then
    read -p "SendGrid From Name: " SENDGRID_FROM_NAME
fi

if [ -z "$VPN_SERVER_PUBLIC_KEY" ]; then
    read -p "VPN Server Public Key: " VPN_SERVER_PUBLIC_KEY
fi

if [ -z "$VPN_SERVER_ENDPOINT" ]; then
    read -p "VPN Server Endpoint: " VPN_SERVER_ENDPOINT
fi

if [ -z "$VPN_DNS_SERVERS" ]; then
    read -p "VPN DNS Servers (default: 10.20.200.1): " VPN_DNS_SERVERS
fi
VPN_DNS_SERVERS=${VPN_DNS_SERVERS:-10.20.200.1}

if [ -z "$VPN_ALLOWED_IPS" ]; then
    read -p "VPN Allowed IPs (default: 10.0.0.0/8,fd00:a::/32): " VPN_ALLOWED_IPS
fi
VPN_ALLOWED_IPS=${VPN_ALLOWED_IPS:-10.0.0.0/8,fd00:a::/32}

echo ""
echo "Application Configuration (press Enter for defaults):"
if [ -z "$SESSION_EXPIRY_HOURS" ]; then
    read -p "Session Expiry Hours (default: 24): " SESSION_EXPIRY_HOURS
fi
SESSION_EXPIRY_HOURS=${SESSION_EXPIRY_HOURS:-24}

if [ -z "$BULK_EMAIL_INTERVAL_MINUTES" ]; then
    read -p "Bulk Email Interval Minutes (default: 45): " BULK_EMAIL_INTERVAL_MINUTES
fi
BULK_EMAIL_INTERVAL_MINUTES=${BULK_EMAIL_INTERVAL_MINUTES:-45}

echo ""
echo "Reminder Configuration (press Enter for defaults):"
if [ -z "$REMINDER_1_DAYS_AFTER_INVITE" ]; then
    read -p "Reminder 1 - Days After Invite (default: 7): " REMINDER_1_DAYS_AFTER_INVITE
fi
REMINDER_1_DAYS_AFTER_INVITE=${REMINDER_1_DAYS_AFTER_INVITE:-7}

if [ -z "$REMINDER_1_MIN_DAYS_BEFORE_EVENT" ]; then
    read -p "Reminder 1 - Min Days Before Event (default: 14): " REMINDER_1_MIN_DAYS_BEFORE_EVENT
fi
REMINDER_1_MIN_DAYS_BEFORE_EVENT=${REMINDER_1_MIN_DAYS_BEFORE_EVENT:-14}

if [ -z "$REMINDER_2_DAYS_AFTER_INVITE" ]; then
    read -p "Reminder 2 - Days After Invite (default: 14): " REMINDER_2_DAYS_AFTER_INVITE
fi
REMINDER_2_DAYS_AFTER_INVITE=${REMINDER_2_DAYS_AFTER_INVITE:-14}

if [ -z "$REMINDER_2_MIN_DAYS_BEFORE_EVENT" ]; then
    read -p "Reminder 2 - Min Days Before Event (default: 7): " REMINDER_2_MIN_DAYS_BEFORE_EVENT
fi
REMINDER_2_MIN_DAYS_BEFORE_EVENT=${REMINDER_2_MIN_DAYS_BEFORE_EVENT:-7}

if [ -z "$REMINDER_3_DAYS_BEFORE_EVENT" ]; then
    read -p "Reminder 3 - Days Before Event (default: 3): " REMINDER_3_DAYS_BEFORE_EVENT
fi
REMINDER_3_DAYS_BEFORE_EVENT=${REMINDER_3_DAYS_BEFORE_EVENT:-3}

if [ -z "$REMINDER_CHECK_INTERVAL_HOURS" ]; then
    read -p "Reminder Check Interval Hours (default: 24): " REMINDER_CHECK_INTERVAL_HOURS
fi
REMINDER_CHECK_INTERVAL_HOURS=${REMINDER_CHECK_INTERVAL_HOURS:-24}

echo ""
if [ -z "$STAGING_SERVICE_ID" ]; then
    read -p "Staging Service ID: " STAGING_SERVICE_ID
fi

if [ -z "$PRODUCTION_SERVICE_ID" ]; then
    read -p "Production Service ID: " PRODUCTION_SERVICE_ID
fi

if [ -z "$STAGING_URL" ]; then
    read -p "Staging URL: " STAGING_URL
fi

if [ -z "$PRODUCTION_URL" ]; then
    read -p "Production URL: " PRODUCTION_URL
fi

# Derive ALLOWED_HOSTS from URLs
STAGING_ALLOWED_HOSTS=$(echo "$STAGING_URL" | sed 's|https://||' | sed 's|http://||' | sed 's|/.*||')
PRODUCTION_ALLOWED_HOSTS=$(echo "$PRODUCTION_URL" | sed 's|https://||' | sed 's|http://||' | sed 's|/.*||')

echo ""
if [ -z "$RENDER_API_KEY" ]; then
    read -sp "Render API Key: " RENDER_API_KEY
    echo ""
fi
echo ""

# Function to set environment variable via Render API
set_env_var() {
    local service_id=$1
    local key=$2
    local value=$3

    echo -n "  Setting ${key}... "

    # Try to update existing env var
    response=$(curl -s -X PATCH \
        "https://api.render.com/v1/services/${service_id}/env-vars/${key}" \
        -H "Authorization: Bearer ${RENDER_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"value\":\"${value}\"}" 2>&1)

    # If update failed, try to create new env var
    if echo "$response" | grep -qi "error\|not found"; then
        response=$(curl -s -X POST \
            "https://api.render.com/v1/services/${service_id}/env-vars" \
            -H "Authorization: Bearer ${RENDER_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "[{\"key\":\"${key}\",\"value\":\"${value}\"}]" 2>&1)
    fi

    if echo "$response" | grep -qi "error"; then
        echo "❌ Failed"
        return 1
    else
        echo "✅"
        return 0
    fi
}

echo ""
echo "Setting environment variables for STAGING..."
set_env_var "$STAGING_SERVICE_ID" "SECRET_KEY" "$STAGING_SECRET_KEY"
set_env_var "$STAGING_SERVICE_ID" "CSRF_SECRET_KEY" "$STAGING_CSRF_SECRET_KEY"
set_env_var "$STAGING_SERVICE_ID" "ENCRYPTION_KEY" "$STAGING_ENCRYPTION_KEY"
set_env_var "$STAGING_SERVICE_ID" "DEBUG" "False"
set_env_var "$STAGING_SERVICE_ID" "FRONTEND_URL" "$STAGING_URL"
set_env_var "$STAGING_SERVICE_ID" "ALLOWED_HOSTS" "$STAGING_ALLOWED_HOSTS"
set_env_var "$STAGING_SERVICE_ID" "SESSION_EXPIRY_HOURS" "$SESSION_EXPIRY_HOURS"
set_env_var "$STAGING_SERVICE_ID" "SENDGRID_API_KEY" "$SENDGRID_API_KEY"
set_env_var "$STAGING_SERVICE_ID" "SENDGRID_FROM_EMAIL" "$SENDGRID_FROM_EMAIL"
set_env_var "$STAGING_SERVICE_ID" "SENDGRID_FROM_NAME" "$SENDGRID_FROM_NAME"
set_env_var "$STAGING_SERVICE_ID" "SENDGRID_SANDBOX_MODE" "true"
set_env_var "$STAGING_SERVICE_ID" "BULK_EMAIL_INTERVAL_MINUTES" "$BULK_EMAIL_INTERVAL_MINUTES"
set_env_var "$STAGING_SERVICE_ID" "REMINDER_1_DAYS_AFTER_INVITE" "$REMINDER_1_DAYS_AFTER_INVITE"
set_env_var "$STAGING_SERVICE_ID" "REMINDER_1_MIN_DAYS_BEFORE_EVENT" "$REMINDER_1_MIN_DAYS_BEFORE_EVENT"
set_env_var "$STAGING_SERVICE_ID" "REMINDER_2_DAYS_AFTER_INVITE" "$REMINDER_2_DAYS_AFTER_INVITE"
set_env_var "$STAGING_SERVICE_ID" "REMINDER_2_MIN_DAYS_BEFORE_EVENT" "$REMINDER_2_MIN_DAYS_BEFORE_EVENT"
set_env_var "$STAGING_SERVICE_ID" "REMINDER_3_DAYS_BEFORE_EVENT" "$REMINDER_3_DAYS_BEFORE_EVENT"
set_env_var "$STAGING_SERVICE_ID" "REMINDER_CHECK_INTERVAL_HOURS" "$REMINDER_CHECK_INTERVAL_HOURS"
set_env_var "$STAGING_SERVICE_ID" "VPN_SERVER_PUBLIC_KEY" "$VPN_SERVER_PUBLIC_KEY"
set_env_var "$STAGING_SERVICE_ID" "VPN_SERVER_ENDPOINT" "$VPN_SERVER_ENDPOINT"
set_env_var "$STAGING_SERVICE_ID" "VPN_DNS_SERVERS" "$VPN_DNS_SERVERS"
set_env_var "$STAGING_SERVICE_ID" "VPN_ALLOWED_IPS" "$VPN_ALLOWED_IPS"

echo ""
echo "Setting environment variables for PRODUCTION..."
set_env_var "$PRODUCTION_SERVICE_ID" "SECRET_KEY" "$PRODUCTION_SECRET_KEY"
set_env_var "$PRODUCTION_SERVICE_ID" "CSRF_SECRET_KEY" "$PRODUCTION_CSRF_SECRET_KEY"
set_env_var "$PRODUCTION_SERVICE_ID" "ENCRYPTION_KEY" "$PRODUCTION_ENCRYPTION_KEY"
set_env_var "$PRODUCTION_SERVICE_ID" "DEBUG" "False"
set_env_var "$PRODUCTION_SERVICE_ID" "FRONTEND_URL" "$PRODUCTION_URL"
set_env_var "$PRODUCTION_SERVICE_ID" "ALLOWED_HOSTS" "$PRODUCTION_ALLOWED_HOSTS"
set_env_var "$PRODUCTION_SERVICE_ID" "SESSION_EXPIRY_HOURS" "$SESSION_EXPIRY_HOURS"
set_env_var "$PRODUCTION_SERVICE_ID" "SENDGRID_API_KEY" "$SENDGRID_API_KEY"
set_env_var "$PRODUCTION_SERVICE_ID" "SENDGRID_FROM_EMAIL" "$SENDGRID_FROM_EMAIL"
set_env_var "$PRODUCTION_SERVICE_ID" "SENDGRID_FROM_NAME" "$SENDGRID_FROM_NAME"
set_env_var "$PRODUCTION_SERVICE_ID" "SENDGRID_SANDBOX_MODE" "false"
set_env_var "$PRODUCTION_SERVICE_ID" "BULK_EMAIL_INTERVAL_MINUTES" "$BULK_EMAIL_INTERVAL_MINUTES"
set_env_var "$PRODUCTION_SERVICE_ID" "REMINDER_1_DAYS_AFTER_INVITE" "$REMINDER_1_DAYS_AFTER_INVITE"
set_env_var "$PRODUCTION_SERVICE_ID" "REMINDER_1_MIN_DAYS_BEFORE_EVENT" "$REMINDER_1_MIN_DAYS_BEFORE_EVENT"
set_env_var "$PRODUCTION_SERVICE_ID" "REMINDER_2_DAYS_AFTER_INVITE" "$REMINDER_2_DAYS_AFTER_INVITE"
set_env_var "$PRODUCTION_SERVICE_ID" "REMINDER_2_MIN_DAYS_BEFORE_EVENT" "$REMINDER_2_MIN_DAYS_BEFORE_EVENT"
set_env_var "$PRODUCTION_SERVICE_ID" "REMINDER_3_DAYS_BEFORE_EVENT" "$REMINDER_3_DAYS_BEFORE_EVENT"
set_env_var "$PRODUCTION_SERVICE_ID" "REMINDER_CHECK_INTERVAL_HOURS" "$REMINDER_CHECK_INTERVAL_HOURS"
set_env_var "$PRODUCTION_SERVICE_ID" "VPN_SERVER_PUBLIC_KEY" "$VPN_SERVER_PUBLIC_KEY"
set_env_var "$PRODUCTION_SERVICE_ID" "VPN_SERVER_ENDPOINT" "$VPN_SERVER_ENDPOINT"
set_env_var "$PRODUCTION_SERVICE_ID" "VPN_DNS_SERVERS" "$VPN_DNS_SERVERS"
set_env_var "$PRODUCTION_SERVICE_ID" "VPN_ALLOWED_IPS" "$VPN_ALLOWED_IPS"

echo ""
echo "✅ Environment variables configured!"
echo ""
echo "Configuration Summary:"
echo ""
echo "Security:"
echo "  ✅ Separate SECRET_KEY for staging and production"
echo "  ✅ Separate CSRF_SECRET_KEY for staging and production"
echo "  ✅ Separate ENCRYPTION_KEY for staging and production"
echo ""
echo "Application Settings:"
echo "  ✅ ALLOWED_HOSTS auto-configured from URLs"
echo "  ✅ SESSION_EXPIRY_HOURS: ${SESSION_EXPIRY_HOURS}"
echo "  ✅ DEBUG: False"
echo ""
echo "Email Configuration:"
echo "  ✅ SendGrid configured"
echo "  ✅ Staging: SENDGRID_SANDBOX_MODE=true (no real emails sent)"
echo "  ✅ Production: SENDGRID_SANDBOX_MODE=false (emails will be sent)"
echo "  ✅ BULK_EMAIL_INTERVAL_MINUTES: ${BULK_EMAIL_INTERVAL_MINUTES}"
echo ""
echo "Reminder Settings:"
echo "  ✅ Reminder 1: ${REMINDER_1_DAYS_AFTER_INVITE} days after invite, ${REMINDER_1_MIN_DAYS_BEFORE_EVENT} days before event"
echo "  ✅ Reminder 2: ${REMINDER_2_DAYS_AFTER_INVITE} days after invite, ${REMINDER_2_MIN_DAYS_BEFORE_EVENT} days before event"
echo "  ✅ Reminder 3: ${REMINDER_3_DAYS_BEFORE_EVENT} days before event"
echo "  ✅ Check interval: ${REMINDER_CHECK_INTERVAL_HOURS} hours"
echo ""
echo "VPN Configuration:"
echo "  ✅ WireGuard server configured"
echo ""
echo "Note: Services will automatically redeploy with the new environment variables."
echo "Check the Render dashboard to monitor the deployment."
