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
- get_telemetry_posture: 遥测态势探针与脱敏元数据（SRE诊断与前端卡片）
- parse_otlp_headers: W3C/OTel 标准标头解析
- is_local_trace_only: 本地 Trace 模式判定
- assert_local_trace_only: 本地 Trace 零泄漏断言
- get_tracer: 获取追踪器（框架内部使用）
- trace_async: 异步函数装饰器（框架内部使用）
- trace_context: 上下文管理器（框架内部使用）

[POS]
Tracer utilities. Provides OpenTelemetry span creation and tracing decorators.

"""

from __future__ import annotations

import functools
import logging
import os
import threading
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


def is_local_trace_only() -> bool:
    """Return True if local-trace-only security isolation is enforced."""
    return os.getenv("MYRM_LOCAL_TRACE_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def assert_local_trace_only(endpoint: str | None = None) -> None:
    """Verify that no remote endpoint is configured when local-trace-only mode is active."""
    if (
        (is_local_trace_only())
        and endpoint
        and not (
            endpoint.startswith(
                (
                    "http://localhost",
                    "http://127.0.0.1",
                    "grpc://localhost",
                    "grpc://127.0.0.1",
                )
            )
        )
    ):
        raise PermissionError(
            f"Security Policy Violation: Remote trace export to '{endpoint}' is blocked in local-trace-only mode."
        )


def parse_otlp_headers(raw_headers: str | None = None) -> dict[str, str]:
    """Parse W3C / OpenTelemetry standard comma-separated key=value headers string.

    Supports URL-encoded characters as per OTel spec (e.g. key1=val1,key2=val2).
    """
    raw = (
        raw_headers
        if raw_headers is not None
        else os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    )
    if not raw or not raw.strip():
        return {}

    import urllib.parse

    headers: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        key = urllib.parse.unquote(k.strip())
        val = urllib.parse.unquote(v.strip())
        if key:
            headers[key] = val
    return headers


def get_telemetry_posture() -> dict[str, object]:
    """Return read-only posture and health metadata of current OpenTelemetry tracing state.

    Safe for SRE health probes, diagnostic status cards, and administrative introspection.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf").strip().lower()
    local_trace_only = is_local_trace_only()
    has_headers = bool(parse_otlp_headers())

    status = "noop"
    if _initialized:
        status = "active" if endpoint else "console"
    elif not HAS_OTEL_SDK:
        status = "missing_sdk"
    elif local_trace_only:
        status = "local_only"

    # Redact endpoint credentials if present
    sanitized_endpoint = endpoint
    if "@" in endpoint:
        try:
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(endpoint)
            netloc = f"{parsed.username or ''}:[REDACTED]@{parsed.hostname}{f':{parsed.port}' if parsed.port else ''}"
            sanitized_endpoint = urlunparse(
                (
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
        except Exception:
            sanitized_endpoint = "[FILTERED]"

    return {
        "status": status,
        "initialized": _initialized,
        "has_sdk": HAS_OTEL_SDK,
        "endpoint": sanitized_endpoint or None,
        "protocol": protocol,
        "headers_configured": has_headers,
        "local_trace_only": local_trace_only,
        "three_tier_semantics": True,
        "prompt_cache_metering": True,
    }


def setup_tracing(
    service_name: str = "myrm-agent-harness",
    console_export: bool = True,
    sample_rate: float = 0.1,
    otlp_endpoint: str | None = None,
    otlp_headers: dict[str, str] | str | None = None,
    otlp_protocol: str | None = None,
    local_trace_only: bool = False,
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
        local_trace_only: If True, enforce that no external remote OTLP export occurs.
    """
    global _tracer_provider, _initialized

    if local_trace_only or is_local_trace_only():
        assert_local_trace_only(otlp_endpoint)
        if otlp_endpoint and not (
            otlp_endpoint.startswith(
                (
                    "http://localhost",
                    "http://127.0.0.1",
                    "grpc://localhost",
                    "grpc://127.0.0.1",
                )
            )
        ):
            logger.warning(
                "Local-trace-only mode active: ignoring remote OTLP endpoint '%s'",
                otlp_endpoint,
            )
            otlp_endpoint = None

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

    # Attach privacy sanitizer processor prior to any batch exporters
    from .sanitizer import SanitizingSpanProcessor

    _tracer_provider.add_span_processor(SanitizingSpanProcessor())

    # Add exporter
    if otlp_endpoint:
        # Determine protocol
        protocol = (
            otlp_protocol
            or os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL")
            or (
                "grpc"
                if ":4317" in otlp_endpoint or otlp_endpoint.startswith("grpc://")
                else "http/protobuf"
            )
        ).lower()

        # Resolve headers
        headers_dict: dict[str, str] = {}
        if isinstance(otlp_headers, dict):
            headers_dict = dict(otlp_headers)
        elif isinstance(otlp_headers, str):
            headers_dict = parse_otlp_headers(otlp_headers)
        else:
            headers_dict = parse_otlp_headers()

        exporter_created = False
        # Try HTTP/Protobuf first if protocol is http or endpoint matches http(s)
        if "http" in protocol or protocol == "http/protobuf":
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter as HttpOTLPSpanExporter,
                )

                exporter_kwargs: dict[str, Any] = {"endpoint": otlp_endpoint}
                if headers_dict:
                    exporter_kwargs["headers"] = headers_dict

                http_exporter = HttpOTLPSpanExporter(**exporter_kwargs)
                _tracer_provider.add_span_processor(BatchSpanProcessor(http_exporter))
                exporter_created = True
                logger.info(
                    "OTLP HTTP trace exporter configured: %s (headers=%d)",
                    otlp_endpoint,
                    len(headers_dict),
                )
            except (ImportError, TypeError, Exception) as exc:
                logger.debug(
                    "Failed to initialize OTLP HTTP exporter, falling back to gRPC/console: %s",
                    exc,
                )

        if not exporter_created:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

                grpc_kwargs: dict[str, Any] = {"endpoint": otlp_endpoint}
                # Check if TLS should be used
                if otlp_endpoint.startswith("https://"):
                    grpc_kwargs["insecure"] = False
                elif not otlp_endpoint.startswith("http://"):
                    grpc_kwargs["insecure"] = True
                else:
                    grpc_kwargs["insecure"] = True

                if headers_dict:
                    grpc_kwargs["headers"] = tuple(headers_dict.items())

                exporter = OTLPSpanExporter(**grpc_kwargs)
                _tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
                exporter_created = True
                logger.info("OTLP gRPC trace exporter configured: %s", otlp_endpoint)
            except (ImportError, TypeError, Exception) as exc:
                logger.warning(
                    "opentelemetry-exporter-otlp not usable (%s), falling back to console",
                    exc,
                )
                _tracer_provider.add_span_processor(
                    BatchSpanProcessor(ConsoleSpanExporter())
                )
    elif console_export:
        _tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Set as global tracer provider
    trace.set_tracer_provider(_tracer_provider)

    _initialized = True
    logger.info(
        "Tracing initialized: service=%s, sample_rate=%.1f", service_name, sample_rate
    )


def is_tracing_initialized() -> bool:
    """Return True when ``setup_tracing()`` has configured a real TracerProvider."""
    return _initialized


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


def shutdown_tracing(timeout_ms: float = 1500.0) -> bool:
    """Gracefully shutdown tracing provider with bounded timeout and daemon thread isolation.

    Uses a dedicated daemon thread to invoke tracer provider shutdown so that if remote
    OTLP endpoints hang or network lags, the process/session exit is not blocked indefinitely,
    and Python's atexit handler avoids deadlocks waiting on non-daemon threads.

    Args:
        timeout_ms: Maximum duration in milliseconds to wait for flush/shutdown (default 1500ms).

    Returns:
        True if shutdown completed within timeout, False if it timed out or was already uninitialized.
    """
    global _tracer_provider, _initialized

    if not _initialized or _tracer_provider is None:
        return False

    provider = _tracer_provider
    _tracer_provider = None
    _initialized = False

    if not hasattr(provider, "shutdown"):
        return True

    shutdown_error: list[Exception] = []

    def _worker() -> None:
        try:
            provider.shutdown()
        except Exception as exc:
            shutdown_error.append(exc)

    thread = threading.Thread(target=_worker, name="otel-bounded-shutdown", daemon=True)
    thread.start()
    timeout_sec = max(0.01, timeout_ms / 1000.0)
    thread.join(timeout=timeout_sec)

    if thread.is_alive():
        logger.warning(
            "Tracing provider shutdown timed out after %.1fms (daemon thread detached)",
            timeout_ms,
        )
        return False

    if shutdown_error:
        logger.error("Error during tracing shutdown: %s", shutdown_error[0])
        return False

    logger.info("Tracing provider shutdown complete")
    return True


# =====================================================================
# OpenTelemetry GenAI Semantic Conventions (SSOT)
# =====================================================================
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_CACHE_READ_TOKENS = "gen_ai.usage.cache_read_tokens"
GEN_AI_USAGE_TOTAL_TOKENS = "gen_ai.usage.total_tokens"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"
GEN_AI_TOOL_STATUS = "gen_ai.tool.status"
GEN_AI_AGENT_TURN = "gen_ai.agent.turn"
GEN_AI_SERVER_TTFT_MS = "gen_ai.server.ttft_ms"
