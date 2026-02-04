#!/bin/bash
#
# Database Backup Script for CyberX Event Management System
# Creates timestamped backups of PostgreSQL database
#

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/backups}"
POSTGRES_USER="${POSTGRES_USER:-cyberx}"
POSTGRES_DB="${POSTGRES_DB:-cyberx_events}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/cyberx_backup_${DATE}.sql.gz"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔄 Starting database backup...${NC}"
echo "Backup file: ${BACKUP_FILE}"

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

# Perform backup
if pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | gzip > "${BACKUP_FILE}"; then
    echo -e "${GREEN}✅ Backup completed successfully${NC}"

    # Get backup size
    BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "Backup size: ${BACKUP_SIZE}"

    # Clean up old backups
    echo -e "${YELLOW}🧹 Cleaning up old backups (older than ${RETENTION_DAYS} days)...${NC}"
    find "${BACKUP_DIR}" -name "cyberx_backup_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

    # List recent backups
    echo -e "${GREEN}📦 Recent backups:${NC}"
    ls -lht "${BACKUP_DIR}"/cyberx_backup_*.sql.gz | head -5

else
    echo -e "${RED}❌ Backup failed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Backup process completed${NC}"
