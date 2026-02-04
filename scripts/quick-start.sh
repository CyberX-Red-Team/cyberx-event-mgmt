#!/bin/bash
#
# Quick Start Script for CyberX Event Management System
# Sets up the entire system with one command
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}CyberX Event Management - Quick Start${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check prerequisites
echo -e "${GREEN}Checking prerequisites...${NC}"

command -v docker >/dev/null 2>&1 || { echo -e "${RED}❌ Docker is not installed${NC}"; exit 1; }
command -v docker-compose >/dev/null 2>&1 || { echo -e "${RED}❌ Docker Compose is not installed${NC}"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}❌ Python 3 is not installed${NC}"; exit 1; }

echo -e "${GREEN}✅ All prerequisites met${NC}"
echo ""

# Get project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "${PROJECT_ROOT}"

echo -e "${GREEN}Step 1: Starting Docker services...${NC}"
docker-compose up -d postgres redis

echo "Waiting for services to be ready..."
sleep 10

echo -e "${GREEN}✅ Docker services started${NC}"
echo ""

echo -e "${GREEN}Step 2: Setting up Python environment...${NC}"
cd backend

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo -e "${GREEN}✅ Python environment ready${NC}"
echo ""

echo -e "${GREEN}Step 3: Configuring environment...${NC}"

if [ ! -f ".env" ]; then
    echo "Creating .env file from example..."
    cp .env.example .env

    # Generate secret key
    SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(64))")
    sed -i.bak "s|SECRET_KEY=your-secret-key-here-change-in-production|SECRET_KEY=${SECRET_KEY}|g" .env
    rm .env.bak

    echo -e "${YELLOW}⚠️  Please update .env with your SendGrid API key and other settings${NC}"
else
    echo ".env file already exists, skipping..."
fi

echo -e "${GREEN}✅ Environment configured${NC}"
echo ""

echo -e "${GREEN}Step 4: Setting up database...${NC}"

echo "Running migrations..."
alembic upgrade head

echo "Creating admin user..."
python scripts/setup_clean_db.py \
    --admin-email admin@cyberxredteam.org \
    --admin-password changeme \
    --no-prompt \
    --seed-data

echo -e "${GREEN}✅ Database ready${NC}"
echo ""

echo -e "${GREEN}Step 5: Starting application...${NC}"
echo ""

# Check if uvicorn is already running
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}⚠️  Port 8000 is already in use${NC}"
    echo "Stop the existing process or use a different port"
else
    echo -e "${GREEN}Starting development server...${NC}"
    echo ""
    echo -e "${BLUE}======================================${NC}"
    echo -e "${GREEN}✅ Quick start completed!${NC}"
    echo -e "${BLUE}======================================${NC}"
    echo ""
    echo -e "${BLUE}Application URLs:${NC}"
    echo "  - API: http://localhost:8000"
    echo "  - Docs: http://localhost:8000/api/docs"
    echo "  - Health: http://localhost:8000/health"
    echo ""
    echo -e "${BLUE}Default Admin Credentials:${NC}"
    echo "  - Email: admin@cyberxredteam.org"
    echo "  - Password: changeme"
    echo ""
    echo -e "${YELLOW}⚠️  Remember to change the admin password!${NC}"
    echo ""
    echo "Starting server..."
    echo ""

    # Start the server
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
fi
