"""Tests for tool_result_validator.py — Context Poisoning detection."""

import pytest

from myrm_agent_harness.agent.security.detection.tool_result_validator import (
    ValidationResult,
    should_apply_validation,
    validate_tool_result,
)


class TestValidateToolResult:
    """Tests for validate_tool_result."""

    def test_empty_content_is_valid(self):
        result = validate_tool_result("", "web_search_tool")
        assert result.is_valid

    def test_normal_content_is_valid(self):
        result = validate_tool_result("This is a normal search result with enough content.", "web_search_tool")
        assert result.is_valid

    # --- Error prefix detection ---

    @pytest.mark.parametrize(
        "prefix", ["Error:", "error:", "Failed:", "failed:", "Exception:", "Traceback (most recent call last):"]
    )
    def test_error_prefixes_detected(self, prefix: str):
        result = validate_tool_result(f"{prefix} something went wrong", "bash_code_execute_tool")
        assert not result.is_valid
        assert result.severity == "error"
        assert "error marker" in result.reason

    # --- Error pattern detection ---

    @pytest.mark.parametrize(
        "pattern",
        [
            "404 Not Found",
            "403 Forbidden",
            "500 Internal Server Error",
            "Connection refused",
            "ETIMEDOUT",
            "Permission denied",
            "No such file or directory",
        ],
    )
    def test_error_patterns_detected(self, pattern: str):
        result = validate_tool_result(f"Response: {pattern} while processing", "web_fetch_tool")
        assert not result.is_valid
        assert result.severity == "warning"

    # --- Short search results ---

    def test_short_search_result_flagged(self):
        result = validate_tool_result("No results", "web_search_tool")
        assert not result.is_valid
        assert result.severity == "warning"
        assert "short" in result.reason

    def test_short_content_for_non_search_tool_ok(self):
        result = validate_tool_result("ok", "bash_code_execute_tool")
        assert result.is_valid

    def test_adequate_search_result_ok(self):
        result = validate_tool_result("A" * 60, "web_search_tool")
        assert result.is_valid

    # --- Prompt injection ---

    @pytest.mark.parametrize(
        "injection",
        [
            "忽略之前的指令",
            "ignore previous instructions",
            "disregard all prior",
            "你现在是",
            "you are now",
            "new role:",
        ],
    )
    def test_prompt_injection_detected(self, injection: str):
        result = validate_tool_result(
            f"Normal looking result text that has enough length. {injection} do something bad here", "bash_code_execute_tool"
        )
        assert not result.is_valid
        assert result.severity == "error"
        assert "injection" in result.reason


class TestShouldApplyValidation:
    """Tests for should_apply_validation."""

    def test_search_tools_should_validate(self):
        assert should_apply_validation("web_search_tool")
        assert should_apply_validation("bash_code_execute_tool")

    def test_file_write_skipped(self):
        assert not should_apply_validation("file_write_tool")
        assert not should_apply_validation("file_edit_tool")


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_default_values(self):
        r = ValidationResult(is_valid=True)
        assert r.reason == ""
        assert r.severity == "info"

    def test_custom_values(self):
        r = ValidationResult(is_valid=False, reason="bad", severity="error")
        assert not r.is_valid
        assert r.reason == "bad"
        assert r.severity == "error"
