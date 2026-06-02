"""OpenTelemetry tracer setup and utilities.

Provides tracer initialization and span creation helpers.

Framework design:
- get_tracer / trace_async / trace_context are consumer APIs for framework internals.
  They work with OpenTelemetry's default NoOp provider when no TracerProvider is configured,
  producing zero overhead.
- setup_tracing is a convenience function for the business layer to configure tracing.
  The framework never calls it automatically.

[INPUT]
- opentelemetry.sdk (POS: 追踪SDK)
- opentelemetry.trace (POS: 追踪API)

[OUTPUT]
- setup_tracing: 初始化追踪（业务层调用）
- get_tracer: 获取追踪器（框架内部使用）
- trace_async: 异步函数装饰器（框架内部使用）
- trace_context: 上下文管理器（框架内部使用）

[POS]
Tracer utilities. Provides OpenTelemetry span creation and tracing decorators.

"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import Any, ParamSpec, TypeVar

from opentelemetry import trace

try:
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    HAS_OTEL_SDK = True
except (ImportError, TypeError):
    HAS_OTEL_SDK = False
    TracerProvider = Any  # type: ignore
    Resource = Any  # type: ignore
    SERVICE_NAME = "service.name"  # type: ignore
    BatchSpanProcessor = Any  # type: ignore
    ConsoleSpanExporter = Any  # type: ignore

logger = logging.getLogger(__name__)

_tracer_provider: TracerProvider | None = None
_initialized = False

P = ParamSpec("P")
T = TypeVar("T")


def setup_tracing(
    service_name: str = "myrm-agent-harness",
    console_export: bool = True,
    sample_rate: float = 0.1,
    otlp_endpoint: str | None = None,
) -> None:
    """Initialize OpenTelemetry tracing.

    This is a convenience function intended for the business layer.
    The framework never calls it automatically — without explicit initialization,
    OpenTelemetry uses its default NoOp provider (zero overhead).

    Args:
        service_name: Service name for traces
        console_export: Whether to export traces to console (for development)
        sample_rate: Base sampling rate for normal requests (default: 0.1 = 10%).
            Errors, slow requests, and critical paths are always 100% sampled.
        otlp_endpoint: OTLP exporter endpoint for production. When set, takes
            priority over console_export.
    """
    global _tracer_provider, _initialized

    if not HAS_OTEL_SDK:
        logger.warning(
            "OpenTelemetry SDK not installed. Tracing will run in NoOp mode. Install with `uv add opentelemetry-sdk`"
        )
        return

    if _initialized:
        logger.warning("Tracing already initialized")
        return

    from .sampling import create_intelligent_sampler

    # Create resource
    resource = Resource(
        attributes={
            SERVICE_NAME: service_name,
        }
    )

    # Create intelligent sampler (errors 100%, critical 100%, normal by rate)
    sampler = create_intelligent_sampler(base_rate=sample_rate)

    # Create tracer provider with sampler
    _tracer_provider = TracerProvider(resource=resource, sampler=sampler)

    # Add exporter
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTLP trace exporter configured: %s", otlp_endpoint)
        except (ImportError, TypeError):
            logger.warning("opentelemetry-exporter-otlp not installed, falling back to console")
            _tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif console_export:
        _tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Set as global tracer provider
    trace.set_tracer_provider(_tracer_provider)

    _initialized = True
    logger.info("Tracing initialized: service=%s, sample_rate=%.1f", service_name, sample_rate)


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer instance.

    Returns a NoOp tracer if no TracerProvider has been configured via setup_tracing().

    Args:
        name: Tracer name (typically module name)

    Returns:
        Tracer instance (NoOp if tracing not initialized)
    """
    return trace.get_tracer(name)


@contextmanager
def trace_context(
    tracer_name: str,
    span_name: str,
    attributes: dict[str, Any] | None = None,
):
    """Context manager for creating a span.

    Args:
        tracer_name: Tracer name
        span_name: Span name
        attributes: Optional span attributes

    Example:
        with trace_context("my_module", "operation", {"key": "value"}):
            # do work
            pass
    """
    tracer = get_tracer(tracer_name)

    with tracer.start_as_current_span(span_name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)

        try:
            yield span
        except Exception as exc:
            span.set_attribute("error", True)
            span.set_attribute("error.type", type(exc).__name__)
            span.set_attribute("error.message", str(exc))
            span.record_exception(exc)
            raise


def trace_async(
    tracer_name: str | None = None,
    span_name: str | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator for tracing async functions.

    Args:
        tracer_name: Tracer name (defaults to function module)
        span_name: Span name (defaults to function name)

    Example:
        @trace_async()
        async def my_function(arg: str) -> str:
            return arg.upper()
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            _tracer_name = tracer_name or func.__module__
            _span_name = span_name or func.__name__

            tracer = get_tracer(_tracer_name)

            with tracer.start_as_current_span(_span_name) as span:
                # Record function arguments as attributes
                if args:
                    span.set_attribute("args.count", len(args))
                if kwargs:
                    span.set_attribute("kwargs.count", len(kwargs))
                    # Record specific kwargs (avoid sensitive data)
                    for key in ["channel", "recipient", "model", "provider"]:
                        if key in kwargs:
                            span.set_attribute(f"arg.{key}", str(kwargs[key]))

                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("success", True)
                    return result

                except Exception as exc:
                    span.set_attribute("error", True)
                    span.set_attribute("error.type", type(exc).__name__)
                    span.set_attribute("error.message", str(exc))
                    span.record_exception(exc)
                    raise

        return wrapper

    return decorator


def shutdown_tracing() -> None:
    """Gracefully shutdown tracing provider and flush buffered spans.

    Call this on process exit (e.g., via atexit or signal handler) to ensure
    all buffered spans in BatchSpanProcessor are exported before the process
    terminates. Without this, the last batch of spans may be lost.
    """
    global _tracer_provider, _initialized

    if not _initialized or _tracer_provider is None:
        return

    try:
        if hasattr(_tracer_provider, "shutdown"):
            _tracer_provider.shutdown()
        logger.info("Tracing provider shutdown complete")
    except Exception as exc:
        logger.error("Error during tracing shutdown: %s", exc)
    finally:
        _tracer_provider = None
        _initialized = False
