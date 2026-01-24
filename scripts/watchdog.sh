#!/bin/bash
# AZV Motors Backend Watchdog
# Проверяет критичные эндпойнты и логирует проблемы (без автоматического перезапуска)

set -e

# Настройки
BASE_URL="http://localhost:7139"
CHECK_INTERVAL=5           # Проверка каждые 5 секунд
TIMEOUT=10                 # Таймаут запроса 10 секунд
MAX_FAILURES=2             # Перезапуск после 2 неудачных проверок подряд
RESTART_COOLDOWN=120       # Ждать 2 минуты после рестарта
DOCKER_COMPOSE_DIR="/home/ubuntu/azv_motors_backend_v2"
LOG_FILE="/var/log/azv_watchdog.log"
MEMORY_THRESHOLD=85        # Порог памяти в процентах
CONTAINER_NAME="azv_motors_backend_v2-back-1"

ENDPOINTS=(
    "/health"
)

FAIL_COUNT=0
LAST_RESTART=0
LAST_CLEANUP=0

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

get_container_memory() {
    local mem_pct=$(docker stats --no-stream --format "{{.MemPerc}}" "$CONTAINER_NAME" 2>/dev/null | tr -d '%')
    if [ -z "$mem_pct" ]; then
        echo "0"
    else
        echo "${mem_pct%.*}"
    fi
}

cleanup_docker() {
    log "🧹 Очистка Docker..."
    
    truncate -s 0 /var/lib/docker/containers/*/*.log 2>/dev/null || true
    
    docker system prune -f > /dev/null 2>&1 || true
    
    docker image prune -f > /dev/null 2>&1 || true
    
    log "Очистка завершена"
}

restart_docker() {
    # Функция отключена - перезапуск не выполняется автоматически
    log "⚠️  Перезапуск отключен. Требуется ручное вмешательство для перезапуска контейнера."
    log "   Для ручного перезапуска выполните: cd $DOCKER_COMPOSE_DIR && docker compose restart back"
    LAST_RESTART=$(date +%s)
    FAIL_COUNT=0
}

check_memory() {
    local mem_pct=$(get_container_memory)
    
    if [ "$mem_pct" -ge "$MEMORY_THRESHOLD" ]; then
        log "Память контейнера: ${mem_pct}% (порог: ${MEMORY_THRESHOLD}%)"
        
        cleanup_docker
        sleep 5
        
        mem_pct=$(get_container_memory)
        if [ "$mem_pct" -ge "$MEMORY_THRESHOLD" ]; then
            log "⚠️  Память все еще высокая: ${mem_pct}% (перезапуск отключен, требуется ручное вмешательство)"
            # restart_docker  # Отключено - перезапуск не выполняется
        else
            log "Память после очистки: ${mem_pct}%"
        fi
    fi
}

main() {
    log "Watchdog запущен"
    log "Интервал: ${CHECK_INTERVAL}s, Таймаут: ${TIMEOUT}s, Память: ${MEMORY_THRESHOLD}%"
    
    while true; do
        all_ok=true
        
        for endpoint in "${ENDPOINTS[@]}"; do
            if ! check_endpoint "$endpoint"; then
                log "Эндпойнт $endpoint не отвечает"
                all_ok=false
                break
            fi
        done
        
        if [ "$all_ok" = true ]; then
            if [ $FAIL_COUNT -gt 0 ]; then
                log "Все эндпойнты снова отвечают"
            fi
            FAIL_COUNT=0
            
            local now=$(date +%s)
            if [ $((now - LAST_CLEANUP)) -ge 60 ]; then
                check_memory
                LAST_CLEANUP=$now
            fi
        else
            FAIL_COUNT=$((FAIL_COUNT + 1))
            log "Неудачная проверка ($FAIL_COUNT/$MAX_FAILURES)"
            
            if [ $FAIL_COUNT -ge $MAX_FAILURES ]; then
                log "⚠️  Достигнут лимит неудачных проверок! (перезапуск отключен, требуется ручное вмешательство)"
                # restart_docker  # Отключено - перезапуск не выполняется
            fi
        fi
        
        sleep "$CHECK_INTERVAL"
    done
}

main
