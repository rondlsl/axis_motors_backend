# app/core/telemetry.py
"""
OpenTelemetry configuration for distributed tracing.
Exports traces to Tempo via OTLP/gRPC (port 4317).

Если Tempo недоступен или возвращает FAILED_PRECONDITION:
- задать OTEL_ENABLED=false в .env, чтобы отключить трейсинг;
- либо проверить, что Tempo слушает OTLP gRPC на 4317 и доступен по OTEL_EXPORTER_OTLP_ENDPOINT.
"""
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor


def setup_telemetry(app, engine):
    """
    Initialize OpenTelemetry tracing with auto-instrumentation.
    
    Args:
        app: FastAPI application instance
        engine: SQLAlchemy engine instance
    
    Returns:
        Tracer instance for manual span creation
    """
    if os.getenv("OTEL_ENABLED", "true").lower() != "true":
        print("⚠️ OpenTelemetry disabled via OTEL_ENABLED=false")
        return trace.get_tracer(__name__)
    
    resource = Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", "azv-motors-api"),
        "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
    })
    
    provider = TracerProvider(resource=resource)
    
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    
    try:
        otlp_exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            insecure=True  # Use insecure=False with TLS in production
        )
        
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        trace.set_tracer_provider(provider)
        
        FastAPIInstrumentor.instrument_app(app)
        
        SQLAlchemyInstrumentor().instrument(engine=engine)
        
        RequestsInstrumentor().instrument()
        
        HTTPXClientInstrumentor().instrument()
        
        print(f"✅ OpenTelemetry initialized, exporting to {otlp_endpoint}")
        
    except Exception as e:
        print(f"⚠️ OpenTelemetry initialization failed: {e}")
    
    return trace.get_tracer(__name__)


def get_tracer(name: str = __name__):
    """
    Get a tracer instance for manual span creation.
    
    Usage:
        from app.core.telemetry import get_tracer
        
        tracer = get_tracer(__name__)
        
        with tracer.start_as_current_span("my_operation") as span:
            span.set_attribute("key", "value")
            # ... do work ...
    """
    return trace.get_tracer(name)
