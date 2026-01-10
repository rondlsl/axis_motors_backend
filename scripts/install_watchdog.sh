#!/bin/bash
# Установка watchdog как systemd service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="azv-watchdog"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Установка AZV Watchdog Service..."

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=AZV Motors Backend Watchdog
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/bin/bash ${SCRIPT_DIR}/watchdog.sh
Restart=always
RestartSec=10
User=ubuntu
WorkingDirectory=/home/ubuntu/azv_motors_backend_v2

[Install]
WantedBy=multi-user.target
EOF

sudo touch /var/log/azv_watchdog.log
sudo chown ubuntu:ubuntu /var/log/azv_watchdog.log

chmod +x "${SCRIPT_DIR}/watchdog.sh"

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

echo "✅ Watchdog установлен и запущен!"
echo ""
echo "Управление:"
echo "  sudo systemctl status $SERVICE_NAME   # Статус"
echo "  sudo systemctl stop $SERVICE_NAME     # Остановить"
echo "  sudo systemctl restart $SERVICE_NAME  # Перезапустить"
echo "  tail -f /var/log/azv_watchdog.log     # Логи"
