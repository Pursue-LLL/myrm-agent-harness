"""Error context enhancement tests.

Verifies that enhanced error classes provide comprehensive diagnostic information
and actionable recovery suggestions for LLM agents.

Reference: MASTER_IMPLEMENTATION_ROADMAP.md §13.4
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import BrowserNavigationError
from myrm_agent_harness.utils.errors import ToolError


class TestToolErrorEnhancement:
    """Test ToolError diagnostic and recovery features."""

    def test_basic_tool_error(self):
        """Basic ToolError should work without enhancements."""
        error = ToolError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.user_hint == ""
        assert error.diagnostic_info == {}
        assert error.recovery_suggestions == []

    def test_tool_error_with_diagnostics(self):
        """ToolError with diagnostic info should be accessible."""
        error = ToolError(
            "Container exited with code 255",
            user_hint="Check return value structure",
            diagnostic_info={
                "error_category": "execution_failure",
                "exit_code": 255,
                "last_output": "TypeError: object is not JSON serializable",
            },
            recovery_suggestions=[
                "Ensure return value is JSON serializable",
                "Check for circular references in data structures",
                "Use simpler data types (dict, list, str, int, bool)",
            ],
            error_code="SANDBOX_EXIT_255",
        )

        assert error.error_code == "SANDBOX_EXIT_255"
        assert error.diagnostic_info["exit_code"] == 255
        assert len(error.recovery_suggestions) == 3
        assert "JSON serializable" in error.recovery_suggestions[0]

    def test_tool_error_format_for_llm(self):
        """format_for_llm should produce comprehensive output."""
        error = ToolError(
            "Operation failed",
            user_hint="Try a different approach",
            diagnostic_info={
                "operation": "file_write",
                "path": "/tmp/test.txt",
                "error": "Permission denied",
            },
            recovery_suggestions=[
                "Check file permissions",
                "Try writing to a different directory",
            ],
            error_code="FILE_WRITE_DENIED",
        )

        formatted = error.format_for_llm()

        assert "Error: Operation failed" in formatted
        assert "Error Code: FILE_WRITE_DENIED" in formatted
        assert "Hint: Try a different approach" in formatted
        assert "Diagnostic Info:" in formatted
        assert "operation: file_write" in formatted
        assert "Recovery Suggestions:" in formatted
        assert "1. Check file permissions" in formatted
        assert "2. Try writing to a different directory" in formatted


class TestBrowserNavigationErrorEnhancement:
    """Test BrowserNavigationError diagnostic features."""

    def test_404_error_suggestions(self):
        """404 error should provide relevant suggestions."""
        error = BrowserNavigationError(
            "Page not found",
            url="https://example.com/missing",
            status_code=404,
        )

        assert error.error_code == "BROWSER_NAV_404"
        assert error.diagnostic_info["status_code"] == 404
        suggestions_text = " ".join(error.recovery_suggestions).lower()
        assert "not found" in suggestions_text or "404" in suggestions_text
        assert "homepage" in suggestions_text or "moved" in suggestions_text

    def test_403_error_suggestions(self):
        """403 error should suggest authentication."""
        error = BrowserNavigationError(
            "Access forbidden",
            url="https://example.com/private",
            status_code=403,
        )

        assert error.error_code == "BROWSER_NAV_403"
        suggestions_text = " ".join(error.recovery_suggestions).lower()
        assert "authentication" in suggestions_text or "login" in suggestions_text

    def test_500_error_suggestions(self):
        """500 error should suggest retry."""
        error = BrowserNavigationError(
            "Server error",
            url="https://example.com",
            status_code=500,
        )

        assert error.error_code == "BROWSER_NAV_500"
        suggestions_text = " ".join(error.recovery_suggestions).lower()
        assert "retry" in suggestions_text or "wait" in suggestions_text

    def test_dns_error_suggestions(self):
        """DNS error should provide network troubleshooting."""
        error = BrowserNavigationError(
            "DNS resolution failed",
            url="https://invalid-domain-xyz.com",
            error_text="net::ERR_NAME_NOT_RESOLVED",
        )

        suggestions_text = " ".join(error.recovery_suggestions).lower()
        assert "dns" in suggestions_text
        assert "domain" in suggestions_text or "connectivity" in suggestions_text

    def test_connection_refused_suggestions(self):
        """Connection refused should suggest port/scheme check."""
        error = BrowserNavigationError(
            "Connection refused",
            url="http://localhost:9999",
            error_text="net::ERR_CONNECTION_REFUSED",
        )

        suggestions_text = " ".join(error.recovery_suggestions).lower()
        assert "port" in suggestions_text or "scheme" in suggestions_text

    def test_format_for_llm_comprehensive(self):
        """format_for_llm should provide complete diagnostic context."""
        error = BrowserNavigationError(
            "Navigation failed",
            url="https://example.com/page",
            status_code=403,
            error_text="Access denied",
            context={"retry_count": 3},
        )

        formatted = error.format_for_llm()

        assert "Error: Navigation failed" in formatted
        assert "Error Code: BROWSER_NAV_403" in formatted
        assert "url: https://example.com/page" in formatted
        assert "status_code: 403" in formatted
        assert "error_text: Access denied" in formatted
        assert "retry_count: 3" in formatted
        assert "Recovery Suggestions:" in formatted


class TestErrorContextIntegration:
    """Test error context enhancement integration."""

    def test_error_chaining_preserves_context(self):
        """Error chaining should preserve diagnostic context."""
        root_cause = ValueError("Invalid input")

        error = BrowserNavigationError(
            "Navigation failed",
            url="https://example.com/page",
            status_code=500,
            cause=root_cause,
        )

        assert error.__cause__ is root_cause
        assert error.diagnostic_info["url"] == "https://example.com/page"

    def test_multiple_errors_maintain_separate_context(self):
        """Multiple errors should maintain independent context."""
        error1 = BrowserNavigationError(
            "Nav denied",
            url="https://example.com/private",
            status_code=403,
        )
        error2 = BrowserNavigationError(
            "Nav error",
            status_code=404,
        )

        assert error1.error_code == "BROWSER_NAV_403"
        assert error2.error_code == "BROWSER_NAV_404"
        assert error1.diagnostic_info != error2.diagnostic_info

    def test_error_without_optional_fields(self):
        """Errors should work without optional diagnostic fields."""
        error = BrowserNavigationError("Generic navigation failure")

        assert error.error_code == "BROWSER_NAV_FAILED"
        assert error.diagnostic_info == {}
        assert len(error.recovery_suggestions) > 0  # Should have generic suggestions

    def test_recovery_suggestions_prioritized(self):
        """Recovery suggestions should be ordered by priority."""
        error = BrowserNavigationError(
            "Page not found",
            url="https://example.com/missing",
            status_code=404,
        )

        # First suggestion should be most specific
        first_suggestion = error.recovery_suggestions[0]
        assert "verify" in first_suggestion.lower() or "not found" in first_suggestion.lower()


class TestErrorCodeClassification:
    """Test error code generation for metrics and alerting."""

    def test_navigation_error_codes(self):
        """Navigation errors should have status-specific codes."""
        error_404 = BrowserNavigationError("Not found", status_code=404)
        error_403 = BrowserNavigationError("Forbidden", status_code=403)
        error_500 = BrowserNavigationError("Server error", status_code=500)

        assert error_404.error_code == "BROWSER_NAV_404"
        assert error_403.error_code == "BROWSER_NAV_403"
        assert error_500.error_code == "BROWSER_NAV_500"

    def test_generic_error_code_fallback(self):
        """Errors without specific info should have generic codes."""
        nav_generic = BrowserNavigationError("Failed")

        assert nav_generic.error_code == "BROWSER_NAV_FAILED"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
