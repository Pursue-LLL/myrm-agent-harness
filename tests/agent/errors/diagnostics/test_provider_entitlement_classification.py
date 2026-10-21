"""Provider entitlement errors (no credits / no subscription) are billing, never a rejected key.

Both classifiers must agree: the diagnostics engine picks the user-facing card and recovery
button, the failover classifier picks cooldown policy and quota-exhaustion handling.
"""

import pytest

from myrm_agent_harness.agent.errors.diagnostics import LLMErrorDiagnostic
from myrm_agent_harness.toolkits.llms.errors.classifier import classify_failover_reason, is_quota_exhausted
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason


class _ProviderError(Exception):
    """An OpenAI-compatible SDK error: HTTP status plus the provider's raw body text."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"Error code: {status_code} - {body}")
        self.status_code = status_code


# The xAI bodies mirror the fixtures in the Hermes and OpenClaw test suites; none was captured by
# this project. The 402 and Chinese bodies are generic provider wordings. Single-phrase bodies
# ("run out of credits", "need a Grok subscription") make dropping any one billing phrase from
# either classifier fail at least one case.
_ENTITLEMENT_CASES = {
    "supergrok_403_no_active_subscription": _ProviderError(
        403,
        "{'code': 'The caller does not have permission to execute the specified operation', "
        "'error': 'You have either run out of available resources or do not have an active Grok subscription. "
        "Manage subscriptions at https://grok.com'}",
    ),
    "supergrok_403_need_subscription": _ProviderError(403, '{"error":"You need a Grok subscription"}'),
    "xai_403_out_of_credits": _ProviderError(403, '{"error":"You have run out of credits"}'),
    "xai_403_team_blocked": _ProviderError(
        403,
        "{'code': 'personal-team-blocked:spending-limit', "
        "'error': 'You have run out of credits or need a Grok subscription. Add credits at Grok or upgrade at Grok.'}",
    ),
    "xai_403_spending_limit": _ProviderError(
        403,
        '{"code":"The caller does not have permission to execute the specified operation",'
        '"error":"Your team team-redacted has either used all available credits or reached its monthly spending '
        'limit. To continue making API requests, please purchase more credits or raise your spending limit."}',
    ),
    "xai_429_credits_exhausted": _ProviderError(
        429,
        '{"code":"Some resource has been exhausted","error":"Your team team-redacted has either used all available '
        "credits or reached its monthly spending limit. To continue making API requests, please purchase more "
        'credits or raise your spending limit."}',
    ),
    "provider_402_payment_required": _ProviderError(402, '{"error":"Payment required"}'),
    "chinese_recharge_prompt": _ProviderError(400, "账户异常,请充值后重试"),
}

# Composed from the stale-token signals Hermes documents for xAI: the `[WKE=unauthenticated:...]`
# suffix, "OAuth2 access token could not be validated" and the `unauthenticated:bad-credentials` code.
_REJECTED_CREDENTIAL_CASES = {
    "stale_oauth_token": _ProviderError(
        403,
        "{'code': 'The caller does not have permission to execute the specified operation', "
        "'error': 'OAuth2 access token could not be validated [WKE=unauthenticated:invalid-token]'}",
    ),
    "bad_credentials": _ProviderError(
        403, "{'code': 'unauthenticated:bad-credentials', 'error': 'The OAuth2 access token could not be validated.'}"
    ),
    "invalid_api_key": _ProviderError(401, '{"error":"Incorrect API key provided"}'),
}


@pytest.mark.parametrize("exc", _ENTITLEMENT_CASES.values(), ids=_ENTITLEMENT_CASES.keys())
def test_diagnostics_marks_entitlement_error_as_billing(exc: _ProviderError) -> None:
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "billing"
    assert result.is_retryable is False


@pytest.mark.parametrize("exc", _ENTITLEMENT_CASES.values(), ids=_ENTITLEMENT_CASES.keys())
def test_failover_classifier_marks_entitlement_error_as_exhausted_billing(exc: _ProviderError) -> None:
    assert classify_failover_reason(exc) == FailoverReason.BILLING
    assert is_quota_exhausted(exc) is True


@pytest.mark.parametrize("exc", _REJECTED_CREDENTIAL_CASES.values(), ids=_REJECTED_CREDENTIAL_CASES.keys())
def test_rejected_credential_is_not_billing_in_either_classifier(exc: _ProviderError) -> None:
    assert LLMErrorDiagnostic.diagnose(exc).error_type == "api_key"
    assert classify_failover_reason(exc) != FailoverReason.BILLING
    assert is_quota_exhausted(exc) is False
