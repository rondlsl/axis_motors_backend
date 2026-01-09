#!/bin/bash

# Setup Cross-Service Health Monitoring Cron Jobs
# This script sets up cron jobs for mutual health checking between services

echo "Setting up cross-service health monitoring..."

# Add cron jobs
(crontab -l 2>/dev/null; echo "# Backend checks Cars service every 5 minutes") | crontab -
(crontab -l 2>/dev/null; echo "*/5 * * * * curl -f http://localhost:7139/health/cars > /dev/null 2>&1 || echo 'Cars check failed'") | crontab -

(crontab -l 2>/dev/null; echo "# Cars checks Backend service every 5 minutes") | crontab -
(crontab -l 2>/dev/null; echo "*/5 * * * * curl -f http://localhost:8667/health/backend > /dev/null 2>&1 || echo 'Backend check failed'") | crontab -

echo "✅ Cron jobs added successfully!"
echo ""
echo "Current crontab:"
crontab -l
