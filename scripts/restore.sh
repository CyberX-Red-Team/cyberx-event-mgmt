#!/bin/bash
#
# Database Restore Script for CyberX Event Management System
# Restores PostgreSQL database from a backup file
#

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/backups}"
POSTGRES_USER="${POSTGRES_USER:-cyberx}"
POSTGRES_DB="${POSTGRES_DB:-cyberx_events}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if backup file is provided
if [ -z "$1" ]; then
    echo -e "${YELLOW}Available backups:${NC}"
    ls -lht "${BACKUP_DIR}"/cyberx_backup_*.sql.gz | head -10
    echo ""
    echo -e "${RED}Usage: $0 <backup_file>${NC}"
    echo "Example: $0 ${BACKUP_DIR}/cyberx_backup_20260203_120000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"

# Check if backup file exists
if [ ! -f "${BACKUP_FILE}" ]; then
    echo -e "${RED}❌ Backup file not found: ${BACKUP_FILE}${NC}"
    exit 1
fi

echo -e "${YELLOW}⚠️  WARNING: This will replace the current database!${NC}"
echo "Database: ${POSTGRES_DB}"
echo "Backup file: ${BACKUP_FILE}"
echo ""
read -p "Are you sure you want to continue? (yes/no): " -r
echo

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo -e "${YELLOW}Restore cancelled${NC}"
    exit 0
fi

echo -e "${GREEN}🔄 Starting database restore...${NC}"

# Create a backup of the current database before restoring
SAFETY_BACKUP="${BACKUP_DIR}/pre_restore_backup_$(date +%Y%m%d_%H%M%S).sql.gz"
echo "Creating safety backup: ${SAFETY_BACKUP}"
pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | gzip > "${SAFETY_BACKUP}"

# Drop existing connections
echo "Terminating existing database connections..."
psql -U "${POSTGRES_USER}" -d postgres -c "
    SELECT pg_terminate_backend(pg_stat_activity.pid)
    FROM pg_stat_activity
    WHERE pg_stat_activity.datname = '${POSTGRES_DB}'
    AND pid <> pg_backend_pid();
" > /dev/null

# Drop and recreate database
echo "Dropping and recreating database..."
psql -U "${POSTGRES_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${POSTGRES_DB};" > /dev/null
psql -U "${POSTGRES_USER}" -d postgres -c "CREATE DATABASE ${POSTGRES_DB};" > /dev/null

# Restore from backup
echo "Restoring from backup..."
if gunzip < "${BACKUP_FILE}" | psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Database restored successfully${NC}"
    echo "Safety backup saved: ${SAFETY_BACKUP}"
else
    echo -e "${RED}❌ Restore failed${NC}"
    echo "Rolling back to safety backup..."
    gunzip < "${SAFETY_BACKUP}" | psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" > /dev/null 2>&1
    echo -e "${YELLOW}Rolled back to safety backup${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Restore process completed${NC}"
