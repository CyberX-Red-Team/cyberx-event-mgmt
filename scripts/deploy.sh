#!/bin/bash
#
# Deployment Script for CyberX Event Management System
# Handles deployment to staging or production environments
#

set -e

# Configuration
ENVIRONMENT="${1:-staging}"
DEPLOY_DIR="/opt/cyberx-event-mgmt"
BACKUP_DIR="/opt/backups/cyberx"
DATE=$(date +%Y%m%d_%H%M%S)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}CyberX Event Management - Deployment${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Validate environment
if [[ ! "${ENVIRONMENT}" =~ ^(staging|production)$ ]]; then
    echo -e "${RED}❌ Invalid environment: ${ENVIRONMENT}${NC}"
    echo "Usage: $0 <staging|production>"
    exit 1
fi

# Confirm deployment
if [ "${ENVIRONMENT}" = "production" ]; then
    echo -e "${YELLOW}⚠️  WARNING: Deploying to PRODUCTION${NC}"
    read -p "Are you sure you want to continue? (yes/no): " -r
    echo
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo -e "${YELLOW}Deployment cancelled${NC}"
        exit 0
    fi
fi

# Create backup directory
mkdir -p "${BACKUP_DIR}/${DATE}"

echo -e "${GREEN}Step 1: Creating backup...${NC}"

# Backup current application
if [ -d "${DEPLOY_DIR}" ]; then
    echo "Backing up application..."
    tar -czf "${BACKUP_DIR}/${DATE}/app_backup.tar.gz" -C "${DEPLOY_DIR}" . || true
fi

# Backup database
echo "Backing up database..."
if docker ps --format '{{.Names}}' | grep -q "cyberx_postgres"; then
    docker exec cyberx_postgres pg_dump -U cyberx cyberx_events | gzip > "${BACKUP_DIR}/${DATE}/db_backup.sql.gz"
else
    pg_dump -U cyberx cyberx_events | gzip > "${BACKUP_DIR}/${DATE}/db_backup.sql.gz"
fi

echo -e "${GREEN}✅ Backup completed: ${BACKUP_DIR}/${DATE}${NC}"
echo ""

echo -e "${GREEN}Step 2: Pulling latest code...${NC}"
cd "${DEPLOY_DIR}"

# Pull latest changes
git fetch origin
git checkout "${ENVIRONMENT}"
git pull origin "${ENVIRONMENT}"

echo -e "${GREEN}✅ Code updated${NC}"
echo ""

echo -e "${GREEN}Step 3: Installing dependencies...${NC}"
cd "${DEPLOY_DIR}/backend"

# Activate virtual environment
source venv/bin/activate

# Update dependencies
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${GREEN}✅ Dependencies installed${NC}"
echo ""

echo -e "${GREEN}Step 4: Running database migrations...${NC}"
alembic upgrade head

echo -e "${GREEN}✅ Migrations completed${NC}"
echo ""

echo -e "${GREEN}Step 5: Restarting services...${NC}"

if [ -f /etc/systemd/system/cyberx-event-mgmt.service ]; then
    # Systemd service
    sudo systemctl reload cyberx-event-mgmt
    sleep 5
    sudo systemctl status cyberx-event-mgmt
elif command -v docker-compose &> /dev/null; then
    # Docker Compose
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
    sleep 10
    docker-compose ps
else
    echo -e "${YELLOW}⚠️  Could not detect service manager${NC}"
    echo "Please restart the application manually"
fi

echo -e "${GREEN}✅ Services restarted${NC}"
echo ""

echo -e "${GREEN}Step 6: Running health checks...${NC}"
sleep 5

# Run health check
if ./scripts/health-check.sh; then
    echo -e "${GREEN}✅ Health checks passed${NC}"
else
    echo -e "${RED}❌ Health checks failed${NC}"
    echo -e "${YELLOW}Consider rolling back using: ./scripts/rollback.sh ${DATE}${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${GREEN}✅ Deployment completed successfully!${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo "Environment: ${ENVIRONMENT}"
echo "Backup location: ${BACKUP_DIR}/${DATE}"
echo "Deployment time: ${DATE}"
echo ""
echo "To rollback if needed:"
echo "  ./scripts/rollback.sh ${DATE}"
