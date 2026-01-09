# Performance Monitoring

## Overview

Middleware that tracks slow API requests and sends Telegram alerts for very slow requests.

## Configuration

- **Slow Threshold**: 3 seconds - logs warning
- **Alert Threshold**: 10 seconds - sends Telegram alert

## Features

✅ Tracks all API request times  
✅ Logs requests taking > 3 seconds  
✅ Sends Telegram alerts for requests > 10 seconds  
✅ Adds `X-Process-Time` header to all responses  
✅ Stores last 100 slow requests for analysis  
✅ Skips health check endpoints  

## Response Headers

Every response includes processing time:
```
X-Process-Time: 1.234
```

## Telegram Alerts

When request takes > 10 seconds:
```
🐌 Very Slow Request Detected!

Method: POST
Path: /api/v1/rent/reserve
Time: 12.45s
Client: 192.168.1.100
```

## Logs

Slow requests are logged:
```
⚠️ Slow request: POST /api/v1/rent/reserve took 4.23s
```

## Monitoring

Check logs for slow requests:
```bash
# View slow request logs
docker compose logs back | grep "Slow request"

# View very slow requests
docker compose logs back | grep "Very Slow"
```

## Common Slow Endpoints

Based on typical patterns, these might be slow:

1. **GPS Commands** - External API calls
2. **Photo Upload** - Large file processing
3. **Billing** - Complex calculations
4. **Reports** - Heavy database queries

## Optimization Tips

If you see repeated slow requests:

1. **Add database indexes** on frequently queried fields
2. **Cache results** for data that doesn't change often
3. **Optimize queries** - use `select_related()` / `joinedload()`
4. **Background tasks** for heavy operations
5. **Pagination** for large result sets

## Disable Alerts

To disable Telegram alerts, set higher threshold:
```python
app.add_middleware(PerformanceMonitoringMiddleware, 
    slow_threshold=3.0, 
    alert_threshold=999.0  # Effectively disabled
)
```
