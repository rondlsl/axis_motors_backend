#!/bin/bash
# AZV Motors Backend Watchdog
# Проверяет критичные эндпойнты и перезапускает Docker если они не отвечают

set -e

# Настройки
BASE_URL="http://localhost:7139"
CHECK_INTERVAL=30          # Проверка каждые 30 секунд
TIMEOUT=10                 # Таймаут запроса 10 секунд
MAX_FAILURES=2             # Перезапуск после 2 неудачных проверок подряд
RESTART_COOLDOWN=120       # Ждать 2 минуты после рестарта
DOCKER_COMPOSE_DIR="/home/ubuntu/azv_motors_backend_v2"
LOG_FILE="/var/log/azv_watchdog.log"

ENDPOINTS=(
    "/health"
    "/vehicles/get_vehicles"
)

FAIL_COUNT=0
LAST_RESTART=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_endpoint() {
    local endpoint=$1
    local url="${BASE_URL}${endpoint}"
    
    if curl -sf --max-time "$TIMEOUT" "$url" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

restart_docker() {
    local now=$(date +%s)
    local since_last=$((now - LAST_RESTART))
    
    if [ $since_last -lt $RESTART_COOLDOWN ]; then
        log "⏳ Cooldown активен, до следующего возможного рестарта: $((RESTART_COOLDOWN - since_last)) сек"
        return
    fi
    
    log "🔄 Перезапуск Docker контейнера..."
    cd "$DOCKER_COMPOSE_DIR"
    docker compose restart back
    LAST_RESTART=$(date +%s)
    FAIL_COUNT=0
    log "✅ Docker контейнер перезапущен"
    
    sleep 30
}

main() {
    log "🚀 Watchdog запущен"
    log "   Интервал: ${CHECK_INTERVAL}s, Таймаут: ${TIMEOUT}s, Max failures: ${MAX_FAILURES}"
    
    while true; do
        all_ok=true
        
        for endpoint in "${ENDPOINTS[@]}"; do
            if ! check_endpoint "$endpoint"; then
                log "❌ Эндпойнт $endpoint не отвечает"
                all_ok=false
                break
            fi
        done
        
        if [ "$all_ok" = true ]; then
            if [ $FAIL_COUNT -gt 0 ]; then
                log "✅ Все эндпойнты снова отвечают"
            fi
            FAIL_COUNT=0
        else
            ((FAIL_COUNT++))
            log "⚠️ Неудачная проверка ($FAIL_COUNT/$MAX_FAILURES)"
            
            if [ $FAIL_COUNT -ge $MAX_FAILURES ]; then
                log "🚨 Достигнут лимит неудачных проверок!"
                restart_docker
            fi
        fi
        
        sleep "$CHECK_INTERVAL"
    done
}

main
