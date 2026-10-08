"""
[POS] tests/unit/test_case_variant_scrubber_suite.py
[INPUT] pytest, typing
[OUTPUT] Unit tests for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite

Validates canonical case folding, delimiter normalization, injection detection,
and RFC 7636 compliant OAuth PKCE flow lifecycle.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.case_variant_scrubber import (
    REDACTED_PLACEHOLDER,
    CaseFoldedCredentialScrubber,
    CaseVariantScrubberSuite,
    OAuthPKCEChallengeMethod,
    OAuthPKCESeam,
    OAuthProviderManifest,
    ScrubActionEnum,
)


def test_case_folded_scrubber_case_variants_dropped() -> None:
    """Validate that mixed-case and hyphenated variants of secret keys are intercepted and dropped."""
    scrubber = CaseFoldedCredentialScrubber()

    raw_env: dict[str, str] = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/alice",
        "Openai_Api_Key": "sk-proj-secret-1234",
        "github_Token": "ghp_secret_token_5678",
        "Aws_Secret_Access_Key": "AKIA_SECRET_KEY",
        "OPENAI-KEY": "sk-another-secret",
        "SAFE_CONFIG_FLAG": "true",
    }

    clean_env, report = scrubber.scrub_env(raw_env, action=ScrubActionEnum.DROP)

    # Secrets must be physically dropped
    assert "Openai_Api_Key" not in clean_env
    assert "github_Token" not in clean_env
    assert "Aws_Secret_Access_Key" not in clean_env
    assert "OPENAI-KEY" not in clean_env

    # Safe vars must be preserved intact
    assert clean_env["PATH"] == "/usr/bin:/bin"
    assert clean_env["HOME"] == "/Users/alice"
    assert clean_env["SAFE_CONFIG_FLAG"] == "true"

    assert report.total_dropped == 4
    assert report.total_scanned == 7


def test_case_folded_scrubber_redaction_mode() -> None:
    """Validate REDACT_PLACEHOLDER mode where values are masked instead of dropped."""
    scrubber = CaseFoldedCredentialScrubber()

    raw_env: dict[str, str] = {
        "ANTHROPIC_API_KEY": "sk-ant-1234",
        "gemini_api_key": "AIzaSySecret",
        "USER": "developer",
    }

    clean_env, report = scrubber.scrub_env(raw_env, action=ScrubActionEnum.REDACT_PLACEHOLDER)

    assert clean_env["ANTHROPIC_API_KEY"] == REDACTED_PLACEHOLDER
    assert clean_env["gemini_api_key"] == REDACTED_PLACEHOLDER
    assert clean_env["USER"] == "developer"

    assert report.total_redacted == 2
    assert report.total_dropped == 0


def test_injection_probe_detection() -> None:
    """Validate detection of intentional mixed-case or hyphenated credential injection attempts."""
    scrubber = CaseFoldedCredentialScrubber()

    tampered_env: dict[str, str] = {
        "Openai_Api_Key": "malicious_attempt",
        "aws-secret-access-key": "another_attempt",
        "STANDARD_UPPERCASE_KEY": "legit",
    }

    injections = scrubber.detect_injection_attempts(tampered_env)
    assert "Openai_Api_Key" in injections
    assert "aws-secret-access-key" in injections
    assert "STANDARD_UPPERCASE_KEY" not in injections


def test_oauth_pkce_seam_lifecycle() -> None:
    """Validate RFC 7636 PKCE flow generation, URL assembly, and exchange validation."""
    seam = OAuthPKCESeam()

    # 1. Initiate flow
    redirect_uri = "https://app.myrm.ai/oauth/callback"
    state, auth_url = seam.initiate_flow(
        provider_id="openrouter",
        redirect_uri=redirect_uri,
    )

    assert state.flow_id.startswith("flow-")
    assert state.challenge_method == OAuthPKCEChallengeMethod.S256
    assert state.code_challenge != ""
    assert "client_id=" in auth_url
    assert f"redirect_uri={redirect_uri.replace('/', '%2F').replace(':', '%3A')}" in auth_url
    assert f"code_challenge={state.code_challenge}" in auth_url

    # 2. State mismatch should raise ValueError (anti-CSRF)
    with pytest.raises(ValueError, match="State parameter mismatch"):
        seam.validate_and_prepare_exchange(
            flow_id=state.flow_id,
            auth_code="auth-code-12345",
            incoming_state="tampered-state-token",
        )

    # 3. Valid exchange
    payload = seam.validate_and_prepare_exchange(
        flow_id=state.flow_id,
        auth_code="auth-code-12345",
        incoming_state=state.state_token,
    )
    assert payload["code"] == "auth-code-12345"
    assert payload["code_verifier"] == state.code_verifier
    assert payload["grant_type"] == "authorization_code"

    # 4. Replaying the same flow ID must fail (single-use token invariant)
    with pytest.raises(ValueError, match="Invalid or expired PKCE flow ID"):
        seam.validate_and_prepare_exchange(
            flow_id=state.flow_id,
            auth_code="auth-code-12345",
            incoming_state=state.state_token,
        )


def test_custom_provider_registration() -> None:
    """Validate registering a third-party declarative OAuth provider manifest."""
    seam = OAuthPKCESeam()
    custom_manifest = OAuthProviderManifest(
        provider_id="custom_llm_hub",
        display_name="Custom LLM Hub",
        authorization_endpoint="https://hub.example.com/oauth/authorize",
        token_endpoint="https://hub.example.com/oauth/token",
        client_id="myrm-custom-id",
        scopes=("models:read", "inference"),
        challenge_method=OAuthPKCEChallengeMethod.S256,
    )

    seam.register_provider(custom_manifest)
    fetched = seam.get_provider("custom_llm_hub")
    assert fetched is not None
    assert fetched.display_name == "Custom LLM Hub"


def test_case_variant_scrubber_suite_end_to_end_metrics() -> None:
    """Validate CaseVariantScrubberSuite metrics and overall facade integration."""
    suite = CaseVariantScrubberSuite()

    # Scrub environment
    test_env = {
        "Openai_Api_Key": "secret1",
        "GITHUB_TOKEN": "secret2",
        "NORMAL_VAR": "val",
    }
    _, report = suite.scrub_environment(test_env, action=ScrubActionEnum.DROP)
    assert report.total_dropped == 2

    # Initiate PKCE
    state, _ = suite.initiate_pkce_flow("openrouter", "https://localhost/callback")
    suite.exchange_pkce_token(state.flow_id, "test_code", state.state_token)

    metrics = suite.metrics
    assert metrics.envs_scrubbed_total == 1
    assert metrics.credentials_intercepted_total == 2
    assert metrics.pkce_flows_initiated_total == 1
    assert metrics.pkce_tokens_exchanged_total == 1
