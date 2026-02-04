#!/bin/bash
#
# Rollback Script for CyberX Event Management System
# Restores application and database from a previous backup
#

set -e

# Configuration
BACKUP_DIR="/opt/backups/cyberx"
DEPLOY_DIR="/opt/cyberx-event-mgmt"
BACKUP_DATE="$1"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}CyberX Event Management - Rollback${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check if backup date is provided
if [ -z "${BACKUP_DATE}" ]; then
    echo -e "${YELLOW}Available backups:${NC}"
    ls -lht "${BACKUP_DIR}" | grep "^d" | head -10
    echo ""
    echo -e "${RED}Usage: $0 <backup_date>${NC}"
    echo "Example: $0 20260203_120000"
    exit 1
fi

BACKUP_PATH="${BACKUP_DIR}/${BACKUP_DATE}"

# Check if backup exists
if [ ! -d "${BACKUP_PATH}" ]; then
    echo -e "${RED}❌ Backup not found: ${BACKUP_PATH}${NC}"
    exit 1
fi

echo -e "${YELLOW}⚠️  WARNING: This will rollback to backup from ${BACKUP_DATE}${NC}"
echo "This will:"
echo "  - Restore application files"
echo "  - Restore database"
echo "  - Restart services"
echo ""
read -p "Are you sure you want to continue? (yes/no): " -r
echo

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo -e "${YELLOW}Rollback cancelled${NC}"
    exit 0
fi

echo -e "${GREEN}Step 1: Stopping services...${NC}"

if [ -f /etc/systemd/system/cyberx-event-mgmt.service ]; then
    sudo systemctl stop cyberx-event-mgmt
elif command -v docker-compose &> /dev/null; then
    docker-compose down
fi

echo -e "${GREEN}✅ Services stopped${NC}"
echo ""

echo -e "${GREEN}Step 2: Restoring application files...${NC}"

if [ -f "${BACKUP_PATH}/app_backup.tar.gz" ]; then
    cd "${DEPLOY_DIR}"
    tar -xzf "${BACKUP_PATH}/app_backup.tar.gz"
    echo -e "${GREEN}✅ Application files restored${NC}"
else
    echo -e "${YELLOW}⚠️  No application backup found${NC}"
fi

echo ""

echo -e "${GREEN}Step 3: Restoring database...${NC}"

if [ -f "${BACKUP_PATH}/db_backup.sql.gz" ]; then
    # Start database if needed
    if command -v docker-compose &> /dev/null; then
        docker-compose up -d postgres
        sleep 10
    fi

    # Restore database
    if docker ps --format '{{.Names}}' | grep -q "cyberx_postgres"; then
        gunzip < "${BACKUP_PATH}/db_backup.sql.gz" | \
            docker exec -i cyberx_postgres psql -U cyberx -d cyberx_events
    else
        gunzip < "${BACKUP_PATH}/db_backup.sql.gz" | psql -U cyberx -d cyberx_events
    fi

    echo -e "${GREEN}✅ Database restored${NC}"
else
    echo -e "${RED}❌ No database backup found${NC}"
    exit 1
fi

echo ""

echo -e "${GREEN}Step 4: Starting services...${NC}"

if [ -f /etc/systemd/system/cyberx-event-mgmt.service ]; then
    sudo systemctl start cyberx-event-mgmt
    sleep 5
    sudo systemctl status cyberx-event-mgmt
elif command -v docker-compose &> /dev/null; then
    docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
    sleep 10
    docker-compose ps
fi

echo -e "${GREEN}✅ Services started${NC}"
echo ""

echo -e "${GREEN}Step 5: Running health checks...${NC}"
sleep 5

if ./scripts/health-check.sh; then
    echo -e "${GREEN}✅ Health checks passed${NC}"
else
    echo -e "${RED}❌ Health checks failed${NC}"
    echo "Please investigate and fix any issues"
fi

echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${GREEN}✅ Rollback completed!${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo "Restored from: ${BACKUP_PATH}"
echo "Backup date: ${BACKUP_DATE}"
