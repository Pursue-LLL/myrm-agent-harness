"""Tests for ExecutionResult.error_hint and generate_error_hint."""

from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.models import (
    ExecutionResult,
    generate_error_hint,
)

# Mock _get_preferred_pip_installer to return "pip" for deterministic tests
_PIP_MOCK = patch(
    "myrm_agent_harness.toolkits.code_execution.executors.models._get_preferred_pip_installer",
    return_value="pip",
)
# Mock _lookup_install_hint to return None (P0 behavior: no catalog lookup)
_LOOKUP_MOCK = patch(
    "myrm_agent_harness.toolkits.code_execution.executors.models._lookup_install_hint",
    return_value=None,
)


# ============================================================================
# generate_error_hint — import errors
# ============================================================================


@_PIP_MOCK
class TestImportHint:
    def test_extracts_module_name(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="ModuleNotFoundError: No module named 'pandas'",
            error_category="import",
        )
        hint = generate_error_hint(result)
        assert hint == "Try: pip install pandas"

    def test_extracts_module_without_quotes(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="ModuleNotFoundError: No module named numpy",
            error_category="import",
        )
        hint = generate_error_hint(result)
        assert hint == "Try: pip install numpy"

    def test_fallback_when_no_module_name(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="ImportError: cannot import name 'foo'",
            error_category="import",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "pip install" in hint

    @pytest.mark.parametrize(
        "import_name,expected_pypi",
        [
            ("PIL", "Pillow"),
            ("cv2", "opencv-python"),
            ("sklearn", "scikit-learn"),
            ("skimage", "scikit-image"),
            ("yaml", "PyYAML"),
            ("bs4", "beautifulsoup4"),
            ("dateutil", "python-dateutil"),
            ("dotenv", "python-dotenv"),
        ],
    )
    def test_import_to_pypi_mapping(self, _mock_pip: object, import_name: str, expected_pypi: str) -> None:
        result = ExecutionResult(
            success=False,
            stderr=f"ModuleNotFoundError: No module named '{import_name}'",
            error_category="import",
        )
        hint = generate_error_hint(result)
        assert hint == f"Try: pip install {expected_pypi}"

    def test_unmapped_module_uses_original_name(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="ModuleNotFoundError: No module named 'some_new_lib'",
            error_category="import",
        )
        hint = generate_error_hint(result)
        assert hint == "Try: pip install some_new_lib"


# ============================================================================
# generate_error_hint — not_found errors
# ============================================================================


@_LOOKUP_MOCK
class TestNotFoundHint:
    def test_extracts_command_name(self, _mock_lookup: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="ffmpeg: command not found",
            error_category="not_found",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "ffmpeg" in hint

    def test_alternative_not_found_pattern(self, _mock_lookup: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="jq: not found",
            error_category="not_found",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "jq" in hint

    def test_fallback_for_file_not_found(self, _mock_lookup: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="FileNotFoundError: [Errno 2] No such file or directory: '/tmp/data.csv'",
            error_category="not_found",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "not found" in hint.lower()


# ============================================================================
# generate_error_hint — permission errors
# ============================================================================


class TestPermissionHint:
    def test_extracts_file_path(self) -> None:
        result = ExecutionResult(
            success=False,
            stderr="bash: ./script.sh: Permission denied",
            error_category="permission",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "chmod" in hint

    def test_permission_with_path(self) -> None:
        result = ExecutionResult(
            success=False,
            stderr="PermissionError: Permission denied: '/usr/local/bin/app'",
            error_category="permission",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "chmod" in hint or "permission" in hint.lower()


# ============================================================================
# generate_error_hint — timeout / oom
# ============================================================================


class TestTimeoutHint:
    def test_timeout_hint(self) -> None:
        result = ExecutionResult(
            success=False,
            stderr="TimeoutError: execution timed out after 300s",
            error_category="timeout",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "timed out" in hint.lower() or "timeout" in hint.lower()


class TestOomHint:
    def test_oom_hint(self) -> None:
        result = ExecutionResult(
            success=False,
            stderr="MemoryError: out of memory",
            error_category="oom",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "memory" in hint.lower()


# ============================================================================
# generate_error_hint — no hint for syntax/unknown
# ============================================================================


class TestNoHint:
    def test_syntax_returns_none(self) -> None:
        result = ExecutionResult(
            success=False,
            stderr="SyntaxError: invalid syntax",
            error_category="syntax",
        )
        assert generate_error_hint(result) is None

    def test_unknown_returns_none(self) -> None:
        result = ExecutionResult(
            success=False,
            stderr="something unexpected happened",
            error_category="unknown",
        )
        assert generate_error_hint(result) is None

    def test_success_returns_none(self) -> None:
        result = ExecutionResult(success=True)
        assert generate_error_hint(result) is None


# ============================================================================
# ExecutionResult.__post_init__ integration
# ============================================================================


@_PIP_MOCK
class TestPostInitIntegration:
    def test_auto_populates_error_hint(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="ModuleNotFoundError: No module named 'requests'",
        )
        assert result.error_category == "import"
        assert result.error_hint is not None
        assert "requests" in result.error_hint

    def test_preserves_explicit_hint(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="ModuleNotFoundError: No module named 'pandas'",
            error_hint="Custom hint from caller",
        )
        assert result.error_hint == "Custom hint from caller"

    def test_success_no_hint(self, _mock_pip: object) -> None:
        result = ExecutionResult(success=True, stdout="ok")
        assert result.error_hint is None
        assert result.error_category is None

    def test_syntax_error_no_hint(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="SyntaxError: invalid syntax",
        )
        assert result.error_category == "syntax"
        assert result.error_hint is None


# ============================================================================
# Edge cases
# ============================================================================


@_PIP_MOCK
class TestEdgeCases:
    def test_empty_stderr_uses_error_field(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="",
            error="ModuleNotFoundError: No module named 'flask'",
            error_category="import",
        )
        hint = generate_error_hint(result)
        assert hint == "Try: pip install flask"

    def test_both_stderr_and_error_empty(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="",
            error=None,
            error_category="import",
        )
        hint = generate_error_hint(result)
        assert hint is not None
        assert "pip install" in hint

    def test_none_category_returns_none(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr="some error",
            error_category=None,
        )
        assert generate_error_hint(result) is None

    def test_multiple_modules_extracts_first(self, _mock_pip: object) -> None:
        result = ExecutionResult(
            success=False,
            stderr=("ModuleNotFoundError: No module named 'pandas'\nModuleNotFoundError: No module named 'numpy'"),
            error_category="import",
        )
        hint = generate_error_hint(result)
        assert hint == "Try: pip install pandas"

    def test_pypi_mapping_integration(self, _mock_pip: object) -> None:
        """End-to-end: PIL in stderr → Pillow in hint via __post_init__."""
        result = ExecutionResult(
            success=False,
            stderr="ModuleNotFoundError: No module named 'PIL'",
        )
        assert result.error_category == "import"
        assert result.error_hint == "Try: pip install Pillow"
