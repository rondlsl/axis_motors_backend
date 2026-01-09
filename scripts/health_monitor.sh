#!/bin/bash

# Health Monitor Script for AZV Motors Backend
# Checks production and test environments and sends Telegram alerts

# Load environment variables from .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | grep -E 'TELEGRAM_BOT_TOKEN_2|MONITOR_GROUP_ID' | xargs)
fi

# Configuration
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN_2:-}"
TELEGRAM_CHAT_ID="${MONITOR_GROUP_ID:-}"
PROD_URL="http://localhost:7139/health"
TEST_URL="http://localhost:7141/health"
LOG_FILE="/tmp/health_monitor.log"

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Send Telegram alert
send_telegram_alert() {
    local message=$1
    
    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
        log "${YELLOW}⚠️  Telegram credentials not configured${NC}"
        return 1
    fi
    
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d text="🚨 <b>AZV Motors Alert</b>

$message

Time: $(date '+%Y-%m-%d %H:%M:%S')
Server: $(hostname)" \
        -d parse_mode="HTML" > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        log "${GREEN}✅ Telegram alert sent${NC}"
    else
        log "${RED}❌ Failed to send Telegram alert${NC}"
    fi
}

# Check service health
check_service() {
    local url=$1
    local name=$2
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        if curl -f -s --max-time 10 "$url" > /dev/null 2>&1; then
            log "${GREEN}✅ $name is UP${NC}"
            return 0
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $max_retries ]; then
            log "${YELLOW}⚠️  $name check failed, retrying ($retry_count/$max_retries)...${NC}"
            sleep 5
        fi
    done
    
    log "${RED}❌ $name is DOWN after $max_retries attempts${NC}"
    send_telegram_alert "❌ <b>$name is DOWN!</b>

Service failed health check after $max_retries attempts.
URL: $url

Action required: Check service logs and restart if needed."
    return 1
}

# Main monitoring
log "🔍 Starting health check..."

# Check production
check_service "$PROD_URL" "Production Backend (7139)"
prod_status=$?

# Check test
check_service "$TEST_URL" "Test Backend (7141)"
test_status=$?

# Summary
if [ $prod_status -eq 0 ] && [ $test_status -eq 0 ]; then
    log "${GREEN}✅ All services are healthy${NC}"
    exit 0
else
    log "${RED}❌ Some services are down${NC}"
    exit 1
fi
