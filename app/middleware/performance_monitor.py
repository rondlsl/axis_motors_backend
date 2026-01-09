import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import logger, TELEGRAM_BOT_TOKEN_2
from app.notifications import send_telegram_message
import asyncio

class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """Middleware to monitor slow API requests"""
    
    def __init__(self, app, slow_threshold: float = 3.0, alert_threshold: float = 10.0):
        super().__init__(app)
        self.slow_threshold = slow_threshold  # Log if request takes > 3 seconds
        self.alert_threshold = alert_threshold  # Send Telegram alert if > 10 seconds
        self.slow_requests = []  # Store recent slow requests
        
    async def dispatch(self, request: Request, call_next):
        # Skip health check endpoints
        if request.url.path in ["/health", "/health/cars", "/health/backend"]:
            return await call_next(request)
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            
            # Add processing time header
            response.headers["X-Process-Time"] = str(round(process_time, 3))
            
            # Log slow requests
            if process_time > self.slow_threshold:
                log_message = (
                    f"⚠️ Slow request: {request.method} {request.url.path} "
                    f"took {process_time:.2f}s"
                )
                logger.warning(log_message)
                
                # Store for monitoring
                self.slow_requests.append({
                    "method": request.method,
                    "path": request.url.path,
                    "time": process_time,
                    "timestamp": time.time()
                })
                
                # Keep only last 100 slow requests
                if len(self.slow_requests) > 100:
                    self.slow_requests = self.slow_requests[-100:]
            
            # Send Telegram alert for very slow requests
            if process_time > self.alert_threshold:
                from app.core.config import TELEGRAM_CHAT_IDS
                
                alert_message = (
                    f"🐌 <b>Very Slow Request Detected!</b>\n\n"
                    f"Method: {request.method}\n"
                    f"Path: {request.url.path}\n"
                    f"Time: {process_time:.2f}s\n"
                    f"Client: {request.client.host if request.client else 'unknown'}"
                )
                try:
                    # Send to monitor group 
                    monitor_chat_id = TELEGRAM_CHAT_IDS.get("Muzon_remix")
                    if monitor_chat_id:
                        asyncio.create_task(
                            send_telegram_message(alert_message, TELEGRAM_BOT_TOKEN_2, monitor_chat_id)
                        )
                except Exception as e:
                    logger.error(f"Failed to send slow request alert: {e}")
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"❌ Request failed: {request.method} {request.url.path} "
                f"after {process_time:.2f}s - Error: {str(e)}"
            )
            raise
