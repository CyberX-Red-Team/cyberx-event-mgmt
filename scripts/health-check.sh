#!/bin/bash
#
# Health Check Script for CyberX Event Management System
# Checks all services and reports their status
#

set -e

# Configuration
APP_URL="${APP_URL:-http://localhost:8000}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Status counters
PASSED=0
FAILED=0

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}CyberX Event Management - Health Check${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Function to check service
check_service() {
    local name="$1"
    local command="$2"

    echo -n "Checking ${name}... "

    if eval "${command}" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ OK${NC}"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}❌ FAILED${NC}"
        ((FAILED++))
        return 1
    fi
}

# Check PostgreSQL
check_service "PostgreSQL" "pg_isready -h ${DB_HOST} -p ${DB_PORT}"

# Check Redis
check_service "Redis" "redis-cli -h ${REDIS_HOST} -p ${REDIS_PORT} ping"

# Check Application Health Endpoint
check_service "Application /health" "curl -sf ${APP_URL}/health"

# Check Application API Docs
check_service "Application /api/docs" "curl -sf -o /dev/null ${APP_URL}/api/docs"

# Check disk space
echo -n "Checking disk space... "
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "${DISK_USAGE}" -lt 90 ]; then
    echo -e "${GREEN}✅ OK (${DISK_USAGE}% used)${NC}"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠️  WARNING (${DISK_USAGE}% used)${NC}"
    ((FAILED++))
fi

# Check memory usage
echo -n "Checking memory usage... "
MEM_USAGE=$(free | awk '/Mem:/ {printf "%.0f", $3/$2 * 100}')
if [ "${MEM_USAGE}" -lt 90 ]; then
    echo -e "${GREEN}✅ OK (${MEM_USAGE}% used)${NC}"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠️  WARNING (${MEM_USAGE}% used)${NC}"
    ((FAILED++))
fi

# Check if Docker services are running (if using Docker)
if command -v docker &> /dev/null; then
    echo ""
    echo -e "${BLUE}Docker Services:${NC}"

    for service in cyberx_postgres cyberx_redis cyberx_app; do
        if docker ps --format '{{.Names}}' | grep -q "^${service}$"; then
            STATUS=$(docker inspect --format='{{.State.Health.Status}}' ${service} 2>/dev/null || echo "unknown")
            if [ "${STATUS}" = "healthy" ] || [ "${STATUS}" = "unknown" ]; then
                echo -e "  ${service}: ${GREEN}✅ Running${NC}"
            else
                echo -e "  ${service}: ${YELLOW}⚠️  ${STATUS}${NC}"
            fi
        else
            echo -e "  ${service}: ${RED}❌ Not Running${NC}"
        fi
    done
fi

# Summary
echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "Passed: ${GREEN}${PASSED}${NC}"
echo -e "Failed: ${RED}${FAILED}${NC}"
echo -e "${BLUE}======================================${NC}"

if [ ${FAILED} -eq 0 ]; then
    echo -e "${GREEN}✅ All health checks passed${NC}"
    exit 0
else
    echo -e "${RED}❌ Some health checks failed${NC}"
    exit 1
fi
