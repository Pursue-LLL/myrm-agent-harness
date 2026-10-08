"""Unit tests for SSO Redirect Idempotent and Probe Hysteresis suite in Harness.

Verifies WHATWG open redirect defense, idempotent URL construction, parameter
de-duplication, and client probe hysteresis dampening.
"""

from myrm_agent_harness.core.security.sso_redirect_idempotent import (
    ProbeEvaluation,
    ProbeHysteresisConfig,
    ProbeHysteresisTracker,
    SafeNavigationOptions,
    SsoRedirectResult,
    build_sso_redirect_url,
    is_safe_navigation_target,
    is_same_origin_relative_path,
    resolve_safe_redirect_target,
)


def test_is_same_origin_relative_path() -> None:
    # Safe relative paths
    assert is_same_origin_relative_path("/") is True
    assert is_same_origin_relative_path("/edu/management") is True
    assert is_same_origin_relative_path("/admin/users?page=1#tab") is True

    # WHATWG open redirect bypass attempts
    assert is_same_origin_relative_path("/\\evil.com") is False
    assert is_same_origin_relative_path("/\\/\\evil.com") is False
    assert is_same_origin_relative_path("/\\\\evil.com") is False
    assert is_same_origin_relative_path("//evil.com") is False
    assert is_same_origin_relative_path("///evil.com") is False

    # Non-path strings
    assert is_same_origin_relative_path("") is False
    assert is_same_origin_relative_path("admin/users") is False
    assert is_same_origin_relative_path("https://example.com") is False


def test_is_safe_navigation_target() -> None:
    # Relative paths always safe
    assert is_safe_navigation_target("/workspace") is True

    # Self-executing protocols strictly rejected
    assert is_safe_navigation_target("javascript:alert(1)") is False
    assert is_safe_navigation_target("data:text/html,<b>xss</b>") is False
    assert is_safe_navigation_target("blob:https://evil.com/uuid") is False
    assert is_safe_navigation_target("file:///etc/passwd") is False

    # HTTP/HTTPS without origin restriction
    assert is_safe_navigation_target("https://myrm.ai/login") is True

    # HTTP/HTTPS with origin restrictions
    opts = SafeNavigationOptions(
        allowed_origins=("https://trusted.myrm.io", "https://auth.myrm.io")
    )
    assert is_safe_navigation_target("https://trusted.myrm.io/callback", opts) is True
    assert is_safe_navigation_target("https://untrusted.com/callback", opts) is False

    # Deep links
    deep_opts_disabled = SafeNavigationOptions(allow_deep_link=False)
    assert is_safe_navigation_target("myrm://sso/callback", deep_opts_disabled) is False

    deep_opts_enabled = SafeNavigationOptions(allow_deep_link=True)
    assert is_safe_navigation_target("myrm://sso/callback", deep_opts_enabled) is True
    assert is_safe_navigation_target("ihui://auth", deep_opts_enabled) is True
    assert is_safe_navigation_target("unknownapp://sso", deep_opts_enabled) is False


def test_build_sso_redirect_url_idempotence() -> None:
    # 1. Fresh append
    res1: SsoRedirectResult = build_sso_redirect_url("/admin?page=1", "code-123")
    assert res1.redirect_url == "/admin?page=1&sso_code=code-123"
    assert res1.stripped_existing_code is False
    assert res1.is_relative is True

    # 2. Existing single sso_code is stripped and replaced
    res2: SsoRedirectResult = build_sso_redirect_url(
        "/admin?page=1&sso_code=stale-code", "code-new"
    )
    assert res2.redirect_url == "/admin?page=1&sso_code=code-new"
    assert res2.stripped_existing_code is True

    # 3. Multiple recursively accumulated sso_codes are completely purged
    res3: SsoRedirectResult = build_sso_redirect_url(
        "/admin?sso_code=c1&sso_code=c2&sso_code=c3&tab=logs", "code-clean"
    )
    assert res3.redirect_url == "/admin?tab=logs&sso_code=code-clean"
    assert res3.stripped_existing_code is True

    # 4. Preserves hash fragment
    res4: SsoRedirectResult = build_sso_redirect_url(
        "/app?query=1&sso_code=old#settings", "code-hash"
    )
    assert res4.redirect_url == "/app?query=1&sso_code=code-hash#settings"

    # 5. Absolute URL
    res5: SsoRedirectResult = build_sso_redirect_url(
        "https://app.myrm.io/dashboard?sso_code=old", "code-abs"
    )
    assert res5.redirect_url == "https://app.myrm.io/dashboard?sso_code=code-abs"
    assert res5.is_relative is False

    # 6. Custom scheme deep link
    res6: SsoRedirectResult = build_sso_redirect_url(
        "myrm://sso/callback?client_id=desktop&sso_code=old", "code-deep"
    )
    assert (
        res6.redirect_url
        == "myrm://sso/callback?client_id=desktop&sso_code=code-deep"
    )


def test_resolve_safe_redirect_target() -> None:
    assert resolve_safe_redirect_target("/admin/home") == "/admin/home"
    assert resolve_safe_redirect_target("/\\evil.com") == "/"

    opts = SafeNavigationOptions(fallback_url="/custom-fallback")
    assert resolve_safe_redirect_target("javascript:evil()", opts) == "/custom-fallback"


def test_probe_hysteresis_tracker_dampening() -> None:
    config = ProbeHysteresisConfig(
        consecutive_fail_threshold=3,
        offline_fallback_url="/offline-page",
    )
    tracker = ProbeHysteresisTracker(config=config, initial_online=True, initial_url="/")

    # Initial state
    assert tracker.is_online is True

    # User navigates to workspace
    eval1: ProbeEvaluation = tracker.record_probe(healthy=True, current_url="/workspace/agent-42")
    assert eval1.is_online is True
    assert eval1.consecutive_fails == 0
    assert eval1.suggested_navigation_url == "/workspace/agent-42"

    # First transient failure: remains online! (Hysteresis dampening)
    eval2: ProbeEvaluation = tracker.record_probe(healthy=False)
    assert eval2.is_online is True
    assert eval2.transitioned_to_offline is False
    assert eval2.consecutive_fails == 1
    assert eval2.suggested_navigation_url == "/workspace/agent-42"

    # Second transient failure: remains online!
    eval3: ProbeEvaluation = tracker.record_probe(healthy=False)
    assert eval3.is_online is True
    assert eval3.transitioned_to_offline is False
    assert eval3.consecutive_fails == 2
    assert eval3.suggested_navigation_url == "/workspace/agent-42"

    # Third failure: threshold reached, transitions to offline!
    eval4: ProbeEvaluation = tracker.record_probe(healthy=False)
    assert eval4.is_online is False
    assert eval4.transitioned_to_offline is True
    assert eval4.consecutive_fails == 3
    assert eval4.suggested_navigation_url == "/offline-page"

    # Fourth failure: remains offline
    eval5: ProbeEvaluation = tracker.record_probe(healthy=False)
    assert eval5.is_online is False
    assert eval5.consecutive_fails == 4

    # Single successful probe recovers immediately to online!
    # Restores user back to /workspace/agent-42, NOT defaulting to home page!
    eval6: ProbeEvaluation = tracker.record_probe(healthy=True)
    assert eval6.is_online is True
    assert eval6.transitioned_to_online is True
    assert eval6.consecutive_fails == 0
    assert eval6.suggested_navigation_url == "/workspace/agent-42"
