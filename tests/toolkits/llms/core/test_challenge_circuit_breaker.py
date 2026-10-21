"""Tests for Cloudflare Challenge Risk Circuit Breaker in KeyPoolLLM."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPool, CredentialPoolStrategy
from myrm_agent_harness.toolkits.llms.core.key_pool_llm import KeyPoolLLM
from myrm_agent_harness.toolkits.llms.errors.classifier import (
    ErrorKind,
    classify_error,
    classify_failover_reason,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import (
    FailoverReason,
    RecoverabilityLevel,
)
from myrm_agent_harness.toolkits.llms.errors.exceptions import EgressChallengeBlockedError


def _make_challenge_error() -> Exception:
    """Create an exception that triggers Cloudflare challenge detection."""
    exc = Exception(
        "Just a moment... Please turn on JavaScript and cookies to continue. "
        "Cloudflare Ray ID: 89ab12cd34ef5678"
    )
    exc.status_code = 403  # type: ignore[attr-defined]
    return exc


def _make_chat_result(text: str = "ok") -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def test_challenge_blocked_classification() -> None:
    exc = _make_challenge_error()
    assert classify_error(exc) == ErrorKind.CHALLENGE_BLOCKED
    assert classify_failover_reason(exc) == FailoverReason.CHALLENGE_BLOCKED
    assert FailoverReason.CHALLENGE_BLOCKED.recoverability == RecoverabilityLevel.PERMANENT


def test_aws_waf_challenge_classification() -> None:
    exc = Exception("403 Forbidden: Request blocked by AWS WAF (x-amzn-waf-action: block)")
    exc.status_code = 403  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.CHALLENGE_BLOCKED
    assert classify_failover_reason(exc) == FailoverReason.CHALLENGE_BLOCKED


def test_akamai_challenge_classification() -> None:
    exc = Exception("Access Denied - You don't have permission to access on this server. AkamaiGHost Reference #18.123")
    exc.status_code = 403  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.CHALLENGE_BLOCKED
    assert classify_failover_reason(exc) == FailoverReason.CHALLENGE_BLOCKED


def test_html_403_challenge_classification() -> None:
    """HTML 403 response with no JSON body must classify as CHALLENGE_BLOCKED to protect key pool."""
    exc = Exception("403 Forbidden: <!DOCTYPE html><html><head><title>403 Forbidden</title></head><body>WAF Block</body></html>")
    exc.status_code = 403  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.CHALLENGE_BLOCKED
    assert classify_failover_reason(exc) == FailoverReason.CHALLENGE_BLOCKED


def test_generic_proxy_html_403_classification() -> None:
    """Generic upstream proxy HTML 403 (no WAF keywords) must classify as CHALLENGE_BLOCKED."""
    exc = Exception(
        "403 Forbidden: <!DOCTYPE html><html><head><title>403 Forbidden</title></head>"
        "<body><h1>403 Forbidden</h1><p>Access denied by egress proxy</p></body></html>"
    )
    exc.status_code = 403  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.CHALLENGE_BLOCKED
    assert classify_failover_reason(exc) == FailoverReason.CHALLENGE_BLOCKED


def test_json_403_security_policy_classification() -> None:
    """JSON 403 response with security policy block must classify as CHALLENGE_BLOCKED."""
    exc = Exception("403 Forbidden: Blocked by security policy")
    exc.status_code = 403  # type: ignore[attr-defined]
    exc.body = {"error": "access_denied", "message": "Blocked by security policy"}  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.CHALLENGE_BLOCKED
    assert classify_failover_reason(exc) == FailoverReason.CHALLENGE_BLOCKED


def test_json_403_ip_blocked_classification() -> None:
    """JSON 403 response with client IP address blocked must classify as CHALLENGE_BLOCKED."""
    exc = Exception("403 Forbidden: Client IP address is blocked")
    exc.status_code = 403  # type: ignore[attr-defined]
    exc.body = {"error": "forbidden", "message": "Client IP address is blocked by firewall"}  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.CHALLENGE_BLOCKED
    assert classify_failover_reason(exc) == FailoverReason.CHALLENGE_BLOCKED


def test_json_bot_detection_classification() -> None:
    """JSON response with bot challenge or turnstile required must classify as CHALLENGE_BLOCKED."""
    exc = Exception("403 Forbidden: bot challenge required")
    exc.status_code = 403  # type: ignore[attr-defined]
    exc.body = {"code": "turnstile_required", "message": "Bot protection triggered"}  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.CHALLENGE_BLOCKED
    assert classify_failover_reason(exc) == FailoverReason.CHALLENGE_BLOCKED


def test_json_403_auth_classification() -> None:
    """Legitimate API 403 with JSON body must remain AUTH_PERMANENT."""
    exc = Exception("403 Forbidden: Permission Denied")
    exc.status_code = 403  # type: ignore[attr-defined]
    exc.body = {"error": {"type": "permission_denied", "message": "API key revoked"}}  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.AUTH
    assert classify_failover_reason(exc) == FailoverReason.AUTH_PERMANENT


def test_json_401_auth_classification() -> None:
    """Legitimate API 401 with JSON body must remain AUTH_PERMANENT."""
    exc = Exception("401 Unauthorized: Invalid API key")
    exc.status_code = 401  # type: ignore[attr-defined]
    exc.body = {"error": {"message": "Invalid API key provided"}}  # type: ignore[attr-defined]
    assert classify_error(exc) == ErrorKind.AUTH
    assert classify_failover_reason(exc) == FailoverReason.AUTH_PERMANENT


@pytest.mark.asyncio
async def test_challenge_circuit_breaker_agenerate_aborts_immediately() -> None:
    """When a Cloudflare challenge occurs, KeyPoolLLM must NOT rotate to other keys."""
    keys = ["sk-key1-aaaaa-11111", "sk-key2-bbbbb-22222"]
    pool = CredentialPool(keys, strategy=CredentialPoolStrategy.ROUND_ROBIN)

    llm1 = MagicMock()
    llm1.model = "test-model"
    llm1._agenerate = AsyncMock(side_effect=_make_challenge_error())

    llm2 = MagicMock()
    llm2.model = "test-model"
    llm2._agenerate = AsyncMock(return_value=_make_chat_result("should not reach here"))

    pool_llm = KeyPoolLLM(
        instances={keys[0]: llm1, keys[1]: llm2},
        pool=pool,
    )

    with pytest.raises(EgressChallengeBlockedError) as exc_info:
        await pool_llm._agenerate([HumanMessage(content="test")])

    assert exc_info.value.error_code == FailoverReason.CHALLENGE_BLOCKED
    assert exc_info.value.context.get("key_suffix") == keys[0][-6:]
    assert "check_egress_proxy" in exc_info.value.recovery_actions

    # Circuit breaker tripped on key1 — key2 MUST NEVER be called to protect accounts
    assert llm1._agenerate.call_count == 1
    llm2._agenerate.assert_not_called()


@pytest.mark.asyncio
async def test_challenge_circuit_breaker_astream_aborts_immediately() -> None:
    """Stream execution must also trip the circuit breaker and avoid subsequent pool keys."""
    keys = ["sk-key1-aaaaa-11111", "sk-key2-bbbbb-22222"]
    pool = CredentialPool(keys, strategy=CredentialPoolStrategy.ROUND_ROBIN)

    llm1 = MagicMock()
    llm1.model = "test-model"

    async def _failing_stream(*args, **kwargs):
        raise _make_challenge_error()
        yield  # make it a generator

    llm1._astream = _failing_stream

    llm2 = MagicMock()
    llm2.model = "test-model"
    llm2._astream = AsyncMock()

    pool_llm = KeyPoolLLM(
        instances={keys[0]: llm1, keys[1]: llm2},
        pool=pool,
    )

    with pytest.raises(EgressChallengeBlockedError) as exc_info:
        async for _ in pool_llm._astream([HumanMessage(content="test")]):
            pass

    assert exc_info.value.error_code == FailoverReason.CHALLENGE_BLOCKED
    assert exc_info.value.context.get("key_suffix") == keys[0][-6:]
    llm2._astream.assert_not_called()


def test_challenge_circuit_breaker_generate_sync_aborts_immediately() -> None:
    """Sync generate must trip the circuit breaker without rotating keys."""
    keys = ["sk-key1-aaaaa-11111", "sk-key2-bbbbb-22222"]
    pool = CredentialPool(keys, strategy=CredentialPoolStrategy.ROUND_ROBIN)

    llm1 = MagicMock()
    llm1.model = "test-model"
    llm1._generate = MagicMock(side_effect=_make_challenge_error())

    llm2 = MagicMock()
    llm2.model = "test-model"
    llm2._generate = MagicMock(return_value=_make_chat_result("should not reach"))

    pool_llm = KeyPoolLLM(
        instances={keys[0]: llm1, keys[1]: llm2},
        pool=pool,
    )

    with pytest.raises(EgressChallengeBlockedError) as exc_info:
        pool_llm._generate([HumanMessage(content="test")])

    assert exc_info.value.error_code == FailoverReason.CHALLENGE_BLOCKED
    assert exc_info.value.context.get("key_suffix") == keys[0][-6:]
    assert llm1._generate.call_count == 1
    llm2._generate.assert_not_called()
