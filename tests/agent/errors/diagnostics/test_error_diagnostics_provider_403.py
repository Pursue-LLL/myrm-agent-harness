"""A provider 403 is either an account gate (billing) or a rejected credential (api_key)."""

from myrm_agent_harness.agent.errors.diagnostics import LLMErrorDiagnostic


class _PermissionDeniedError(Exception):
    """A provider 403 carrying its JSON body, as the OpenAI-compatible SDKs surface it."""

    status_code = 403

    def __init__(self, body: dict[str, str]) -> None:
        super().__init__(f"Error code: 403 - {body}")
        self.body = body


def test_diagnose_xai_out_of_credits_403_is_billing_not_api_key():
    """xAI answers an account without credits or plan with 403; the key itself is valid."""
    exc = _PermissionDeniedError(
        {
            "code": "personal-team-blocked:spending-limit",
            "error": "You have run out of credits or need a Grok subscription. Add credits at Grok or upgrade at Grok.",
        }
    )
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "billing"
    assert result.is_retryable is False


def test_diagnose_xai_rejected_token_403_stays_api_key():
    """A 403 that says the credential itself is invalid keeps pointing at the credential."""
    exc = _PermissionDeniedError(
        {
            "code": "unauthenticated:bad-credentials",
            "error": "The OAuth2 access token could not be validated.",
        }
    )
    result = LLMErrorDiagnostic.diagnose(exc)

    assert result.error_type == "api_key"
