"""Tests for regex_validator — ReDoS protection and safe regex execution.

Covers:
- Pattern length validation
- Dangerous pattern detection (nested quantifiers, .+/.*)
- Alternation complexity check
- Compile with timeout (signal-based and threading-based)
- safe_search with timeout
- time_limit context manager
- Valid patterns pass through
- Edge cases (empty pattern, boundary patterns)
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.config import FileIOConfig
from myrm_agent_harness.agent.meta_tools.file_search.regex_validator import (
    RegexValidator,
    _timeout_wrapper,
    time_limit,
)
from myrm_agent_harness.utils.errors import ToolError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def validator() -> RegexValidator:
    """Create a RegexValidator with default config."""
    return RegexValidator(FileIOConfig())


@pytest.fixture
def strict_validator() -> RegexValidator:
    """Create a RegexValidator with strict limits."""
    return RegexValidator(FileIOConfig(max_regex_length=50, regex_timeout_seconds=0.5))


# ---------------------------------------------------------------------------
# Tests: Pattern length validation
# ---------------------------------------------------------------------------


class TestPatternLength:
    def test_short_pattern_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile("hello")
        assert result.pattern == "hello"

    def test_exact_max_length_accepted(self) -> None:
        v = RegexValidator(FileIOConfig(max_regex_length=10))
        result = v.validate_and_compile("a" * 10)
        assert result.pattern == "a" * 10

    def test_over_max_length_rejected(self) -> None:
        v = RegexValidator(FileIOConfig(max_regex_length=10))
        with pytest.raises(ToolError, match="too long"):
            v.validate_and_compile("a" * 11)


# ---------------------------------------------------------------------------
# Tests: Dangerous pattern detection
# ---------------------------------------------------------------------------


class TestDangerousPatterns:
    def test_nested_plus_plus(self, validator: RegexValidator) -> None:
        with pytest.raises(ToolError, match="[Dd]angerous|[Nn]ested"):
            validator.validate_and_compile("(a+)+")

    def test_nested_star_star(self, validator: RegexValidator) -> None:
        with pytest.raises(ToolError, match="[Dd]angerous|[Nn]ested"):
            validator.validate_and_compile("(a*)*")

    def test_nested_plus_star(self, validator: RegexValidator) -> None:
        with pytest.raises(ToolError, match="[Dd]angerous|[Nn]ested"):
            validator.validate_and_compile("(a+)*")

    def test_nested_star_plus(self, validator: RegexValidator) -> None:
        with pytest.raises(ToolError, match="[Dd]angerous|[Nn]ested"):
            validator.validate_and_compile("(a*)+")

    def test_dot_plus_nested(self, validator: RegexValidator) -> None:
        with pytest.raises(ToolError, match="[Dd]angerous|[Nn]ested"):
            validator.validate_and_compile("(.+)+")

    def test_dot_star_nested(self, validator: RegexValidator) -> None:
        with pytest.raises(ToolError, match="[Dd]angerous|[Nn]ested"):
            validator.validate_and_compile("(.*)*")

    def test_safe_pattern_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile(r"def \w+\(")
        assert result is not None

    def test_simple_quantifier_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile(r"a+b*c?")
        assert result is not None

    def test_character_class_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile(r"[a-z]+")
        assert result is not None

    def test_lookahead_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile(r"(?=.*test)")
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: Alternation complexity
# ---------------------------------------------------------------------------


class TestAlternationComplexity:
    def test_few_alternations_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile("a|b|c|d|e")
        assert result is not None

    def test_20_alternations_accepted(self, validator: RegexValidator) -> None:
        pattern = "|".join(f"alt{i}" for i in range(20))
        result = validator.validate_and_compile(pattern)
        assert result is not None

    def test_21_alternations_rejected(self, validator: RegexValidator) -> None:
        pattern = "|".join(f"alt{i}" for i in range(22))
        with pytest.raises(ToolError, match="alternation"):
            validator.validate_and_compile(pattern)


# ---------------------------------------------------------------------------
# Tests: Compilation and flags
# ---------------------------------------------------------------------------


class TestCompilation:
    def test_compile_with_ignorecase(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile("hello", re.IGNORECASE)
        assert result.search("HELLO") is not None

    def test_compile_with_multiline(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile("^test", re.MULTILINE)
        assert result.search("line1\ntest line2") is not None

    def test_invalid_regex_rejected(self, validator: RegexValidator) -> None:
        with pytest.raises(ToolError, match="[Ii]nvalid regex"):
            validator.validate_and_compile("[unclosed")

    def test_empty_pattern_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile("")
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: safe_search
# ---------------------------------------------------------------------------


class TestSafeSearch:
    def test_basic_match(self, validator: RegexValidator) -> None:
        compiled = re.compile("hello")
        result = validator.safe_search(compiled, "hello world")
        assert result is not None
        assert result.group() == "hello"

    def test_no_match(self, validator: RegexValidator) -> None:
        compiled = re.compile("xyz")
        result = validator.safe_search(compiled, "hello world")
        assert result is None

    def test_custom_timeout(self, validator: RegexValidator) -> None:
        compiled = re.compile("test")
        result = validator.safe_search(compiled, "this is a test", timeout=1.0)
        assert result is not None

    def test_regex_match_returns_correct_group(self, validator: RegexValidator) -> None:
        compiled = re.compile(r"def (\w+)")
        result = validator.safe_search(compiled, "def hello_world():")
        assert result is not None
        assert result.group(1) == "hello_world"


# ---------------------------------------------------------------------------
# Tests: _timeout_wrapper
# ---------------------------------------------------------------------------


class TestTimeoutWrapper:
    def test_fast_function_succeeds(self) -> None:
        result = _timeout_wrapper(lambda: 42, timeout=1.0)
        assert result == 42

    def test_exception_propagated(self) -> None:
        def raise_error() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            _timeout_wrapper(raise_error, timeout=1.0)


# ---------------------------------------------------------------------------
# Tests: time_limit context manager
# ---------------------------------------------------------------------------


class TestTimeLimit:
    def test_fast_block_succeeds(self) -> None:
        with time_limit(1.0):
            x = sum(range(100))
        assert x == 4950

    def test_context_manager_cleans_up(self) -> None:
        with time_limit(1.0):
            pass


# ---------------------------------------------------------------------------
# Tests: Edge cases — dangerous pattern re.error skip
# ---------------------------------------------------------------------------


class TestDangerousPatternsEdgeCases:
    def test_safe_complex_pattern(self, validator: RegexValidator) -> None:
        """Complex but safe pattern should compile fine."""
        result = validator.validate_and_compile(r"(?:def|class)\s+\w+")
        assert result is not None

    def test_backreference_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile(r"(\w+)\s+\1")
        assert result is not None

    def test_anchored_group_accepted(self, validator: RegexValidator) -> None:
        result = validator.validate_and_compile(r"^(?:abc)$")
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: Windows path simulation
# ---------------------------------------------------------------------------


class TestWindowsPathSimulation:
    def test_validate_compile_with_windows_mock(self) -> None:
        """Simulates Windows platform for threading-based compile path."""
        v = RegexValidator(FileIOConfig(regex_timeout_seconds=2.0))
        with patch("myrm_agent_harness.agent.meta_tools.file_search.regex_validator.platform") as mock_platform:
            mock_platform.system.return_value = "Windows"
            result = v.validate_and_compile("hello")
            assert result.pattern == "hello"

    def test_safe_search_with_windows_mock(self) -> None:
        """Simulates Windows platform for threading-based search path."""
        v = RegexValidator(FileIOConfig(regex_timeout_seconds=2.0))
        compiled = re.compile("hello")
        with patch("myrm_agent_harness.agent.meta_tools.file_search.regex_validator.platform") as mock_platform:
            mock_platform.system.return_value = "Windows"
            result = v.safe_search(compiled, "hello world")
            assert result is not None


# ---------------------------------------------------------------------------
# Tests: time_limit signal-unavailable fallback
# ---------------------------------------------------------------------------


class TestTimeLimitFallback:
    def test_time_limit_on_windows_mock(self) -> None:
        """When platform is Windows, time_limit yields without signal."""
        with patch("myrm_agent_harness.agent.meta_tools.file_search.regex_validator.platform") as mock_platform:
            mock_platform.system.return_value = "Windows"
            with time_limit(1.0):
                x = 42
            assert x == 42
