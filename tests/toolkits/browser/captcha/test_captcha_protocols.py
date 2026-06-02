"""Tests for captcha protocol types and data classes."""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.browser.captcha.protocols import (
    CaptchaInfo,
    CaptchaSolver,
    CaptchaSolveResult,
    CaptchaStatus,
    CaptchaType,
)


class TestCaptchaType:
    """CaptchaType enum tests."""

    def test_all_types_are_strings(self) -> None:
        for t in CaptchaType:
            assert isinstance(t.value, str)

    def test_known_types_exist(self) -> None:
        expected = {
            "cloudflare_challenge",
            "cloudflare_turnstile",
            "recaptcha",
            "hcaptcha",
            "perimeterx",
            "datadome",
            "kasada",
            "akamai",
            "imperva",
            "unknown",
        }
        actual = {t.value for t in CaptchaType}
        assert expected == actual


class TestCaptchaStatus:
    """CaptchaStatus state machine tests."""

    def test_all_statuses_exist(self) -> None:
        expected = {"none", "detected", "solving", "resolved", "timeout"}
        actual = {s.value for s in CaptchaStatus}
        assert expected == actual


class TestCaptchaInfo:
    """CaptchaInfo dataclass tests."""

    def test_defaults(self) -> None:
        info = CaptchaInfo(
            captcha_type=CaptchaType.CLOUDFLARE_CHALLENGE,
            reason="test",
        )
        assert info.blocking is True
        assert info.confidence == 1.0
        assert info.detected_at > 0

    def test_frozen(self) -> None:
        info = CaptchaInfo(
            captcha_type=CaptchaType.RECAPTCHA,
            reason="reCAPTCHA",
        )
        try:
            info.reason = "changed"  # type: ignore[misc]
            assert False, "Should not allow mutation"
        except AttributeError:
            pass

    def test_custom_confidence(self) -> None:
        info = CaptchaInfo(
            captcha_type=CaptchaType.HCAPTCHA,
            reason="hCaptcha block",
            confidence=0.8,
        )
        assert info.confidence == 0.8

    def test_detected_at_monotonic(self) -> None:
        before = time.monotonic()
        info = CaptchaInfo(captcha_type=CaptchaType.UNKNOWN, reason="test")
        after = time.monotonic()
        assert before <= info.detected_at <= after


class TestCaptchaSolveResult:
    """CaptchaSolveResult dataclass tests."""

    def test_success_result(self) -> None:
        result = CaptchaSolveResult(
            success=True,
            method="manual",
            elapsed_ms=5000.0,
        )
        assert result.success is True
        assert result.method == "manual"
        assert result.message == ""

    def test_failure_result(self) -> None:
        result = CaptchaSolveResult(
            success=False,
            method="timeout",
            elapsed_ms=120000.0,
            message="Timed out",
        )
        assert result.success is False
        assert result.message == "Timed out"


class TestCaptchaSolverProtocol:
    """CaptchaSolver protocol tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(CaptchaSolver, "__protocol_attrs__") or hasattr(
            CaptchaSolver, "__abstractmethods__"
        )

    def test_manual_solver_implements_protocol(self) -> None:
        from myrm_agent_harness.toolkits.browser.captcha.manual_solver import ManualSolver

        assert isinstance(ManualSolver(), CaptchaSolver)
