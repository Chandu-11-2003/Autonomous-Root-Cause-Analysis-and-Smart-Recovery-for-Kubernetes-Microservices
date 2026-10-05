import os
import time
import uuid
import logging
import sys
import traceback
import random
from typing import Callable
from pydantic import BaseModel
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

os.environ.setdefault("OTEL_EXPORTER_OTLP_TIMEOUT", "1")
os.environ.setdefault("OTEL_BSP_SCHEDULE_DELAY", "5000")
os.environ.setdefault("OTEL_BSP_EXPORT_TIMEOUT", "1000")
os.environ.setdefault("OTEL_BSP_MAX_QUEUE_SIZE", "512")
os.environ.setdefault("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "64")


class ChaosConfig(BaseModel):
    latency_ms: int = 0
    error_rate: float = 0.0
    enabled: bool = False


CHAOS_STATE = ChaosConfig()


def setup_logger(service_name: str) -> logging.Logger:
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    log_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(trace_id)s %(span_id)s"
    )
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)
    return logger


def setup_telemetry(app: FastAPI, service_name: str):
    logger = setup_logger(service_name)

    jaeger_otlp_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://jaeger.monitoring.svc.cluster.local:4318/v1/traces",
    )

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        class SafeOTLPExporter(SpanExporter):
            def __init__(self, endpoint: str):
                self._inner = OTLPSpanExporter(endpoint=endpoint, timeout=1)
                self._fail_count = 0

            def export(self, spans):
                try:
                    return self._inner.export(spans)
                except Exception:
                    self._fail_count += 1
                    return SpanExportResult.FAILURE

            def shutdown(self):
                try:
                    self._inner.shutdown()
                except Exception:
                    pass

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        safe_exporter = SafeOTLPExporter(jaeger_otlp_endpoint)
        span_processor = BatchSpanProcessor(
            safe_exporter,
            max_queue_size=512,
            schedule_delay_millis=5000,
            max_export_batch_size=64,
            export_timeout_millis=1000,
        )
        provider.add_span_processor(span_processor)
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        try:
            HTTPXClientInstrumentor().instrument()
        except Exception:
            pass

        logger.info(f"OpenTelemetry tracing initialized -> {jaeger_otlp_endpoint}")
    except Exception as e:
        logger.warning(f"OpenTelemetry initialization skipped: {e}")

    REQUEST_COUNT = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["service", "method", "endpoint", "status_code"],
    )
    REQUEST_LATENCY = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["service", "method", "endpoint"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )

    @app.middleware("http")
    async def telemetry_and_chaos_middleware(request: Request, call_next: Callable) -> Response:
        try:
            from opentelemetry import trace
            current_span = trace.get_current_span()
            ctx = current_span.get_span_context() if current_span else None
            if ctx and ctx.is_valid:
                trace_id = format(ctx.trace_id, "032x")
                span_id = format(ctx.span_id, "016x")
            else:
                trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
                span_id = str(uuid.uuid4())[:8]
        except Exception:
            trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
            span_id = str(uuid.uuid4())[:8]

        request.state.trace_id = trace_id
        request.state.span_id = span_id

        endpoint = request.url.path

        # SYSTEM PROBES EXCLUDED FROM CHAOS
        is_system_probe = endpoint in ["/healthz", "/ready", "/metrics"] or endpoint.startswith("/chaos")

        if CHAOS_STATE.enabled and not is_system_probe:
            if CHAOS_STATE.latency_ms > 0:
                time.sleep(CHAOS_STATE.latency_ms / 1000.0)

            if CHAOS_STATE.error_rate > 0 and random.random() < CHAOS_STATE.error_rate:
                logger.error(
                    f"[CHAOS INJECTED] Forced 500 error for {endpoint}",
                    extra={"trace_id": trace_id, "span_id": span_id, "chaos": True},
                )
                REQUEST_COUNT.labels(
                    service=service_name,
                    method=request.method,
                    endpoint=endpoint,
                    status_code=500,
                ).inc()
                return JSONResponse(
                    status_code=500,
                    content={"error": "Chaos Engine Injected Error", "trace_id": trace_id},
                    headers={"x-trace-id": trace_id},
                )

        start_time = time.time()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-trace-id"] = trace_id
            return response
        except HTTPException as he:
            status_code = he.status_code
            return JSONResponse(
                status_code=he.status_code,
                content={"error": he.detail, "trace_id": trace_id},
                headers={"x-trace-id": trace_id},
            )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(
                f"Unhandled error: {str(e)}\n{tb}",
                extra={"trace_id": trace_id, "span_id": span_id, "error": str(e)},
            )
            return JSONResponse(
                status_code=500,
                content={"error": str(e) or "Internal Server Error", "trace_id": trace_id},
                headers={"x-trace-id": trace_id},
            )
        finally:
            duration = time.time() - start_time

            if endpoint.startswith("/api/products/"):
                endpoint = "/api/products/{id}"
            elif endpoint.startswith("/api/orders/"):
                endpoint = "/api/orders/{id}"
            elif endpoint.startswith("/api/users/"):
                endpoint = "/api/users/{id}"

            REQUEST_COUNT.labels(
                service=service_name,
                method=request.method,
                endpoint=endpoint,
                status_code=status_code,
            ).inc()

            REQUEST_LATENCY.labels(
                service=service_name,
                method=request.method,
                endpoint=endpoint,
            ).observe(duration)

            if endpoint not in ["/metrics", "/healthz", "/ready"]:
                logger.info(
                    f"{request.method} {request.url.path} -> {status_code} ({duration*1000:.2f}ms)",
                    extra={
                        "trace_id": trace_id,
                        "span_id": span_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": round(duration * 1000, 2),
                    },
                )

    @app.get("/metrics")
    def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/healthz")
    def health():
        return {"status": "healthy", "service": service_name}

    @app.get("/ready")
    def ready():
        return {"status": "ready", "service": service_name}

    @app.post("/chaos/inject")
    def inject_chaos(config: ChaosConfig):
        global CHAOS_STATE
        CHAOS_STATE = config
        CHAOS_STATE.enabled = True
        logger.warning(f"[CHAOS INJECTED] Config updated: {CHAOS_STATE}")
        return {"status": "chaos_injected", "config": CHAOS_STATE.model_dump()}

    @app.post("/chaos/reset")
    def reset_chaos():
        global CHAOS_STATE
        CHAOS_STATE = ChaosConfig(enabled=False)
        logger.info("[CHAOS RESET] Service returned to normal operational state.")
        return {"status": "chaos_reset", "config": CHAOS_STATE.model_dump()}

    @app.get("/chaos/status")
    def get_chaos_status():
        return {"service": service_name, "chaos": CHAOS_STATE.model_dump()}

    return logger
