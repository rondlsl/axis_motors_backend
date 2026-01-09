# Health Monitoring Setup

## Overview

Health monitoring system with Telegram notifications when services go down.

## Components

1. **Health Endpoint**: `/health` - Returns service status
2. **Monitoring Script**: `scripts/health_monitor.sh` - Checks health and sends alerts
3. **Docker Healthcheck**: Built-in container health monitoring

## Setup Instructions

### 1. Configure Telegram Bot

Get your Telegram credentials:

```bash
# 1. Create bot via @BotFather on Telegram
# 2. Get your chat ID from @userinfobot
# 3. Add to .env file on server:

echo "TELEGRAM_BOT_TOKEN_2=your_bot_token_here" >> ~/.bashrc
echo "TELEGRAM_CHAT_ID=your_chat_id_here" >> ~/.bashrc
source ~/.bashrc
```

### 2. Setup Cron Job

On the server, add cron job to run health check every 5 minutes:

```bash
# Edit crontab
crontab -e

# Add this line (runs every 5 minutes):
*/5 * * * * TELEGRAM_BOT_TOKEN_2=your_token TELEGRAM_CHAT_ID=your_chat_id /home/ubuntu/azv_motors_backend_v2/scripts/health_monitor.sh >> /tmp/health_monitor.log 2>&1
```

### 3. Test Monitoring

```bash
# Run manually to test
cd ~/azv_motors_backend_v2
./scripts/health_monitor.sh

# Stop a service to test alert
docker compose stop back

# Wait 5 minutes for alert
# Restart service
docker compose start back
```

## Health Check Endpoints

- **Production**: http://localhost:7139/health
- **Test**: http://localhost:7141/health

## Docker Healthcheck

Docker automatically monitors container health:

```bash
# Check health status
docker compose ps

# View health check logs
docker inspect azv_motors_backend_v2-back-1 | grep -A 10 Health
```

## Monitoring Features

- ✅ Checks both production and test environments
- ✅ 3 retry attempts before alerting
- ✅ Telegram notifications with details
- ✅ Logs to `/tmp/health_monitor.log`
- ✅ Docker built-in healthcheck every 30s

## Alert Example

When service is down, you'll receive:

```
🚨 AZV Motors Alert

❌ Production Backend (7139) is DOWN!

Service failed health check after 3 attempts.
URL: http://localhost:7139/health

Action required: Check service logs and restart if needed.

Time: 2026-01-10 01:55:00
Server: your-server-hostname
```

## Troubleshooting

**No alerts received:**
```bash
# Check if script is executable
ls -la scripts/health_monitor.sh

# Test Telegram manually
curl -X POST "https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage" \
  -d chat_id=<YOUR_CHAT_ID> \
  -d text="Test message"
```

**Cron not running:**
```bash
# Check cron logs
grep CRON /var/log/syslog

# Verify crontab
crontab -l
```
