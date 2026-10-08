"""Unit tests for SSO Redirect Idempotency and Probe Hysteresis suite.

[POS]
Harness core security test suite verifying IHUI-AI #2728e745 URL sanitization,
idempotent query parameter rewriting, and multi-threshold probe hysteresis.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.sso_redirect import (
    ProbeEvaluationResult,
    ProbeHysteresisController,
    ProbeHysteresisState,
    SsoUrlSanitizer,
    UrlPathCategory,
)


def test_is_same_origin_relative_path() -> None:
    sanitizer = SsoUrlSanitizer()

    # Valid relative paths
    assert sanitizer.is_same_origin_relative_path("/dashboard") is True
    assert sanitizer.is_same_origin_relative_path("/edu/courses?id=1") is True
    assert sanitizer.is_same_origin_relative_path("/a") is True
    assert sanitizer.is_same_origin_relative_path("/") is True

    # Dangerous relative paths (scheme-relative or backslash attack vectors)
    assert sanitizer.is_same_origin_relative_path("//evil.com") is False
    assert sanitizer.is_same_origin_relative_path("/\\evil.com") is False
    assert sanitizer.is_same_origin_relative_path("/\\") is False
    assert sanitizer.is_same_origin_relative_path("//") is False

    # Absolute or non-relative strings
    assert sanitizer.is_same_origin_relative_path("https://example.com") is False
    assert sanitizer.is_same_origin_relative_path("dashboard") is False
    assert sanitizer.is_same_origin_relative_path("") is False


def test_validate_redirect_target() -> None:
    sanitizer = SsoUrlSanitizer()

    # 1. Safe relative
    res_rel = sanitizer.validate_redirect_target("/settings/security")
    assert res_rel.is_safe is True
    assert res_rel.category == UrlPathCategory.SAFE_RELATIVE

    # 2. Unsafe relative
    res_unsafe = sanitizer.validate_redirect_target("//malicious.site/phish")
    assert res_unsafe.is_safe is False
    assert res_unsafe.category == UrlPathCategory.UNSAFE_RELATIVE

    # 3. Absolute with whitelist
    whitelist = frozenset(["auth.example.com", "app.example.com"])
    res_allowed = sanitizer.validate_redirect_target(
        "https://auth.example.com/sso", whitelist
    )
    assert res_allowed.is_safe is True
    assert res_allowed.category == UrlPathCategory.ABSOLUTE

    res_blocked = sanitizer.validate_redirect_target(
        "https://attacker.org/steal", whitelist
    )
    assert res_blocked.is_safe is False
    assert res_blocked.category == UrlPathCategory.ABSOLUTE

    # 4. Deep link
    res_deep = sanitizer.validate_redirect_target("myrm://oauth/callback?code=123")
    assert res_deep.is_safe is True
    assert res_deep.category == UrlPathCategory.DEEP_LINK


def test_build_sso_redirect_url_idempotence() -> None:
    sanitizer = SsoUrlSanitizer()

    # Initial append
    res1 = sanitizer.build_sso_redirect_url("/sso/callback", "CODE_A")
    assert res1.final_url == "/sso/callback?sso_code=CODE_A"
    assert res1.is_relative is True

    # Re-entrance with existing code: must strip CODE_A and append CODE_B without multiplying
    res2 = sanitizer.build_sso_redirect_url(res1.final_url, "CODE_B")
    assert res2.final_url == "/sso/callback?sso_code=CODE_B"
    assert "CODE_A" not in res2.final_url

    # Existing query parameters preserved
    complex_target = "/edu/management?tab=reports&filter=active&sso_code=OLD_CODE#view"
    res3 = sanitizer.build_sso_redirect_url(complex_target, "NEW_CODE")
    assert "sso_code=NEW_CODE" in res3.final_url
    assert "OLD_CODE" not in res3.final_url
    assert "tab=reports" in res3.final_url
    assert "filter=active" in res3.final_url
    assert res3.final_url.endswith("#view")

    # Absolute URL
    abs_target = "https://app.example.com/auth?tenant=acme&sso_code=EXPIRED"
    res_abs = sanitizer.build_sso_redirect_url(abs_target, "FRESH_TOKEN")
    assert (
        res_abs.final_url
        == "https://app.example.com/auth?tenant=acme&sso_code=FRESH_TOKEN"
    )
    assert res_abs.is_relative is False


def test_probe_hysteresis_controller() -> None:
    controller = ProbeHysteresisController(
        offline_failure_threshold=3, degraded_failure_threshold=1
    )

    assert controller.current_state == ProbeHysteresisState.ONLINE

    # 1st failure -> DEGRADED
    r1 = controller.record_probe_result(False)
    assert r1.new_state == ProbeHysteresisState.DEGRADED
    assert r1.state_changed is True
    assert r1.consecutive_failures == 1

    # 2nd failure -> still DEGRADED (threshold for offline is 3)
    r2 = controller.record_probe_result(False)
    assert r2.new_state == ProbeHysteresisState.DEGRADED
    assert r2.state_changed is False
    assert r2.consecutive_failures == 2

    # 3rd failure -> OFFLINE
    r3 = controller.record_probe_result(False)
    assert r3.new_state == ProbeHysteresisState.OFFLINE
    assert r3.state_changed is True
    assert r3.consecutive_failures == 3
    assert r3.recommended_action == "switch_to_offline_fallback"

    # Single success -> immediately back to ONLINE
    r4 = controller.record_probe_result(True)
    assert r4.new_state == ProbeHysteresisState.ONLINE
    assert r4.state_changed is True
    assert r4.consecutive_successes == 1
    assert r4.consecutive_failures == 0
