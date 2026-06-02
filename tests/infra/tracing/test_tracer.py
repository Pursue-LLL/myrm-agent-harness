"""Unit tests for OpenTelemetry tracer."""

import pytest

from myrm_agent_harness.infra.tracing import (
    get_tracer,
    setup_tracing,
    trace_async,
    trace_context,
)


def test_get_tracer_returns_noop_without_setup():
    """get_tracer returns a NoOp tracer when setup_tracing has not been called."""
    tracer = get_tracer("noop_module")
    assert tracer is not None


def test_setup_tracing():
    """Test tracing initialization."""
    setup_tracing(service_name="test-service", console_export=False)

    tracer = get_tracer("test_module")
    assert tracer is not None


def test_trace_context():
    """Test trace context manager."""
    setup_tracing(service_name="test-service", console_export=False)

    with trace_context("test_module", "test_operation", {"key": "value"}) as span:
        assert span is not None
        span.set_attribute("custom", "attribute")


def test_trace_context_with_error():
    """Test trace context with exception."""
    setup_tracing(service_name="test-service", console_export=False)

    with pytest.raises(ValueError), trace_context("test_module", "test_operation"):
        raise ValueError("Test error")


@pytest.mark.asyncio
async def test_trace_async_decorator():
    """Test async function tracing decorator."""
    setup_tracing(service_name="test-service", console_export=False)

    @trace_async()
    async def test_function(arg: str) -> str:
        return arg.upper()

    result = await test_function("hello")
    assert result == "HELLO"


@pytest.mark.asyncio
async def test_trace_async_with_error():
    """Test async decorator with exception."""
    setup_tracing(service_name="test-service", console_export=False)

    @trace_async()
    async def failing_function() -> None:
        raise ValueError("Test error")

    with pytest.raises(ValueError):
        await failing_function()


@pytest.mark.asyncio
async def test_trace_async_with_kwargs():
    """Test async decorator with kwargs."""
    setup_tracing(service_name="test-service", console_export=False)

    @trace_async()
    async def function_with_kwargs(channel: str, recipient: str) -> str:
        return f"{channel}:{recipient}"

    result = await function_with_kwargs(channel="telegram", recipient="user123")
    assert result == "telegram:user123"
