"""Tests for resilient_llm_call."""

import pytest

from myrm_agent_harness.toolkits.llms.errors.resilient import resilient_llm_call


class _BillingError(Exception):
    """Simulates a billing error (failoverable)."""

    def __str__(self) -> str:
        return "insufficient balance"


class _AuthError(Exception):
    """Simulates an auth error (not failoverable)."""

    def __str__(self) -> str:
        return "invalid api key"


class _TimeoutError(Exception):
    """Simulates a timeout error (failoverable)."""

    def __str__(self) -> str:
        return "request timeout"


@pytest.mark.asyncio
async def test_primary_succeeds() -> None:
    result = await resilient_llm_call(
        primary_fn=lambda: _async_return("primary"),
        fallback_fn=lambda: _async_return("fallback"),
    )
    assert result == "primary"


@pytest.mark.asyncio
async def test_failover_on_billing_error() -> None:
    result = await resilient_llm_call(
        primary_fn=lambda: _async_raise(_BillingError()),
        fallback_fn=lambda: _async_return("fallback"),
    )
    assert result == "fallback"


@pytest.mark.asyncio
async def test_failover_on_timeout_error() -> None:
    result = await resilient_llm_call(
        primary_fn=lambda: _async_raise(_TimeoutError()),
        fallback_fn=lambda: _async_return("fallback"),
    )
    assert result == "fallback"


@pytest.mark.asyncio
async def test_no_failover_on_auth_error() -> None:
    with pytest.raises(_AuthError):
        await resilient_llm_call(
            primary_fn=lambda: _async_raise(_AuthError()),
            fallback_fn=lambda: _async_return("fallback"),
        )


@pytest.mark.asyncio
async def test_no_fallback_fn_raises() -> None:
    with pytest.raises(_BillingError):
        await resilient_llm_call(
            primary_fn=lambda: _async_raise(_BillingError()),
            fallback_fn=None,
        )


@pytest.mark.asyncio
async def test_fallback_also_fails() -> None:
    with pytest.raises(_TimeoutError):
        await resilient_llm_call(
            primary_fn=lambda: _async_raise(_BillingError()),
            fallback_fn=lambda: _async_raise(_TimeoutError()),
        )


@pytest.mark.asyncio
async def test_preserves_return_type() -> None:
    result = await resilient_llm_call(
        primary_fn=lambda: _async_return(42),
    )
    assert result == 42
    assert isinstance(result, int)


async def _async_return(value: object) -> object:
    return value


async def _async_raise(exc: Exception) -> object:
    raise exc
