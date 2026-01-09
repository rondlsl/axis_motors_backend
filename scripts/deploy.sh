#!/bin/bash

# Deployment script for azv_motors_backend_v2
# Usage: ./scripts/deploy.sh

set -e  # Exit on error

echo "🚀 Starting deployment..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
APP_DIR=~/azv_motors_backend_v2
BACKUP_DIR=~/azv_motors_backend_v2/backups
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create backup directory if it doesn't exist
mkdir -p $BACKUP_DIR

echo -e "${YELLOW}📦 Pulling latest code...${NC}"
cd $APP_DIR
git fetch origin
git reset --hard origin/main

echo -e "${YELLOW}💾 Creating database backup...${NC}"
docker-compose exec -T db pg_dump -U $POSTGRES_USER $POSTGRES_DB > $BACKUP_DIR/db_backup_$TIMESTAMP.sql || echo "⚠️ Backup failed"

echo -e "${YELLOW}🔧 Stopping services...${NC}"
docker-compose down

echo -e "${YELLOW}🏗️ Building Docker image...${NC}"
docker-compose build --no-cache

echo -e "${YELLOW}🗄️ Running database migrations...${NC}"
docker-compose run --rm back alembic upgrade head || echo "⚠️ Migration failed or already applied"

echo -e "${YELLOW}🚀 Starting services...${NC}"
docker-compose up -d

echo -e "${YELLOW}⏳ Waiting for services to start...${NC}"
sleep 10

echo -e "${YELLOW}🏥 Health check...${NC}"
if curl -f http://localhost:7138/docs > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Deployment successful!${NC}"
    docker-compose ps
else
    echo -e "${RED}❌ Health check failed! Rolling back...${NC}"
    docker-compose down
    echo -e "${YELLOW}Restore manually from: $BACKUP_DIR/db_backup_$TIMESTAMP.sql${NC}"
    exit 1
fi

echo -e "${GREEN}🎉 Deployment completed successfully!${NC}"
