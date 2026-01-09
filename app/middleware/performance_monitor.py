import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import logger
from app.utils.telegram_logger import telegram_error_logger
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
                alert_message = (
                    f"Very Slow Request Detected!\n\n"
                    f"Method: {request.method}\n"
                    f"Path: {request.url.path}\n"
                    f"Time: {process_time:.2f}s\n"
                    f"Client: {request.client.host if request.client else 'unknown'}"
                )
                try:
                    # Send via telegram_error_logger
                    asyncio.create_task(
                        telegram_error_logger.send_warning(
                            alert_message,
                            context={
                                "method": request.method,
                                "path": request.url.path,
                                "time_seconds": round(process_time, 2)
                            }
                        )
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
