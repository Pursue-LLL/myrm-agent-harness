"""Tests for P1: CLI auto-install hint integration.

Covers:
- ToolDefinition.install_hints field
- get_install_hint() lookup with _BIN_TO_TOOL reverse index
- detect_all / refresh_cache / get_cli_tools_context
- generate_error_hint not_found → catalog install command
- import hint smart package manager adaptation (uv preference)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from myrm_agent_harness.toolkits.code_execution.executors.models import (
    ExecutionResult,
    _get_preferred_pip_installer,
    _lookup_install_hint,
    generate_error_hint,
)
from myrm_agent_harness.toolkits.code_execution.tool_discovery import (
    get_cli_tools_context,
)
from myrm_agent_harness.toolkits.code_execution.tool_discovery.detector import (
    _build_extra_dirs,
    _detect_one,
    _expanded_path,
    detect_all,
    get_install_hint,
    refresh_cache,
)
from myrm_agent_harness.toolkits.code_execution.tool_discovery.types import (
    DetectedTool,
    ToolDefinition,
)

# ============================================================================
# ToolDefinition.install_hints
# ============================================================================


class TestToolDefinitionInstallHints:
    def test_default_empty_dict(self) -> None:
        td = ToolDefinition(id="test", bin_names=("test",), desc_en="t", desc_zh="t")
        assert td.install_hints == {}

    def test_with_install_hints(self) -> None:
        td = ToolDefinition(
            id="jq",
            bin_names=("jq",),
            desc_en="JSON processor",
            desc_zh="JSON 处理器",
            install_hints={"Darwin": "brew install jq", "Linux": "apt install jq"},
        )
        assert td.install_hints["Darwin"] == "brew install jq"
        assert td.install_hints["Linux"] == "apt install jq"
        assert "Windows" not in td.install_hints


# ============================================================================
# get_install_hint() — reverse index lookup
# ============================================================================


class TestGetInstallHint:
    def test_known_tool_darwin(self) -> None:
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.platform") as mock_plat:
            mock_plat.system.return_value = "Darwin"
            hint = get_install_hint("jq")
            assert hint == "brew install jq"

    def test_known_tool_linux(self) -> None:
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.platform") as mock_plat:
            mock_plat.system.return_value = "Linux"
            hint = get_install_hint("jq")
            assert hint == "apt install jq"

    def test_unknown_tool_returns_none(self) -> None:
        assert get_install_hint("some_unknown_tool_xyz") is None

    def test_tool_without_install_hints(self) -> None:
        assert get_install_hint("tar") is None or get_install_hint("ssh") is None

    def test_tool_with_no_hint_for_platform(self) -> None:
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.platform") as mock_plat:
            mock_plat.system.return_value = "FreeBSD"
            hint = get_install_hint("jq")
            assert hint is None

    def test_alternate_bin_name(self) -> None:
        """fdfind is an alternate bin_name for fd."""
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.platform") as mock_plat:
            mock_plat.system.return_value = "Linux"
            hint = get_install_hint("fdfind")
            assert hint == "apt install fd-find"

    def test_rg_darwin(self) -> None:
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.platform") as mock_plat:
            mock_plat.system.return_value = "Darwin"
            hint = get_install_hint("rg")
            assert hint == "brew install ripgrep"


# ============================================================================
# _lookup_install_hint (models.py wrapper)
# ============================================================================


class TestLookupInstallHint:
    def test_delegates_to_get_install_hint(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._lookup_install_hint",
            wraps=_lookup_install_hint,
        ), patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.platform") as mock_plat:
            mock_plat.system.return_value = "Darwin"
            result = _lookup_install_hint("ffmpeg")
            assert result == "brew install ffmpeg"


# ============================================================================
# generate_error_hint — not_found with catalog install command
# ============================================================================


class TestNotFoundWithCatalogHint:
    def test_catalog_tool_gets_install_command(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._lookup_install_hint",
            return_value="brew install jq",
        ):
            result = ExecutionResult(
                success=False,
                stderr="jq: command not found",
                error_category="not_found",
            )
            hint = generate_error_hint(result)
            assert hint == "Command 'jq' not found. Try: brew install jq"

    def test_non_catalog_tool_gets_generic_hint(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._lookup_install_hint",
            return_value=None,
        ):
            result = ExecutionResult(
                success=False,
                stderr="mycustomtool: command not found",
                error_category="not_found",
            )
            hint = generate_error_hint(result)
            assert hint == "Command 'mycustomtool' not found. Install it or check the PATH."

    def test_ffmpeg_not_found_darwin(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._lookup_install_hint",
            return_value="brew install ffmpeg",
        ):
            result = ExecutionResult(
                success=False,
                stderr="ffmpeg: command not found",
                error_category="not_found",
            )
            hint = generate_error_hint(result)
            assert "brew install ffmpeg" in hint  # type: ignore[operator]

    def test_rg_not_found_linux(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._lookup_install_hint",
            return_value="apt install ripgrep",
        ):
            result = ExecutionResult(
                success=False,
                stderr="rg: command not found",
                error_category="not_found",
            )
            hint = generate_error_hint(result)
            assert "apt install ripgrep" in hint  # type: ignore[operator]


# ============================================================================
# _get_preferred_pip_installer — uv preference
# ============================================================================


class TestPreferredPipInstaller:
    def test_returns_uv_pip_when_uv_detected(self) -> None:
        from pathlib import Path

        mock_tools = [
            DetectedTool(id="uv", bin_name="uv", bin_path=Path("/usr/local/bin/uv"), desc_en="", desc_zh=""),
            DetectedTool(id="pip", bin_name="pip", bin_path=Path("/usr/bin/pip"), desc_en="", desc_zh=""),
        ]
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.detect_all",
            return_value=mock_tools,
        ):
            assert _get_preferred_pip_installer() == "uv pip"

    def test_returns_pip_when_no_uv(self) -> None:
        from pathlib import Path

        mock_tools = [
            DetectedTool(id="pip", bin_name="pip", bin_path=Path("/usr/bin/pip"), desc_en="", desc_zh=""),
        ]
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.detect_all",
            return_value=mock_tools,
        ):
            assert _get_preferred_pip_installer() == "pip"

    def test_returns_pip_when_empty_tools(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.detect_all",
            return_value=[],
        ):
            assert _get_preferred_pip_installer() == "pip"


# ============================================================================
# generate_error_hint — import with smart installer
# ============================================================================


class TestImportHintWithSmartInstaller:
    def test_uses_uv_pip_when_uv_available(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._get_preferred_pip_installer",
            return_value="uv pip",
        ):
            result = ExecutionResult(
                success=False,
                stderr="ModuleNotFoundError: No module named 'pandas'",
                error_category="import",
            )
            hint = generate_error_hint(result)
            assert hint == "Try: uv pip install pandas"

    def test_uses_pip_when_no_uv(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._get_preferred_pip_installer",
            return_value="pip",
        ):
            result = ExecutionResult(
                success=False,
                stderr="ModuleNotFoundError: No module named 'numpy'",
                error_category="import",
            )
            hint = generate_error_hint(result)
            assert hint == "Try: pip install numpy"

    def test_pypi_mapping_with_uv(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._get_preferred_pip_installer",
            return_value="uv pip",
        ):
            result = ExecutionResult(
                success=False,
                stderr="ModuleNotFoundError: No module named 'PIL'",
                error_category="import",
            )
            hint = generate_error_hint(result)
            assert hint == "Try: uv pip install Pillow"


# ============================================================================
# ExecutionResult.__post_init__ integration (P1)
# ============================================================================


class TestPostInitP1Integration:
    def test_not_found_auto_populates_catalog_hint(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.executors.models._lookup_install_hint",
            return_value="brew install tree",
        ):
            result = ExecutionResult(
                success=False,
                stderr="tree: command not found",
            )
            assert result.error_category == "not_found"
            assert result.error_hint is not None
            assert "brew install tree" in result.error_hint


# ============================================================================
# _build_extra_dirs / _expanded_path / _detect_one
# ============================================================================


class TestBuildExtraDirs:
    def test_returns_tuple(self) -> None:
        result = _build_extra_dirs()
        assert isinstance(result, tuple)
        assert "/usr/local/bin" in result

    def test_home_missing_graceful(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.Path.home", side_effect=RuntimeError
        ):
            result = _build_extra_dirs()
            assert "/usr/local/bin" in result
            assert not any(".local" in d for d in result)


class TestExpandedPath:
    def test_returns_string(self) -> None:
        result = _expanded_path()
        assert isinstance(result, str)

    def test_includes_system_path(self) -> None:
        import os

        sys_path = os.environ.get("PATH", "")
        result = _expanded_path()
        assert sys_path in result


class TestDetectOne:
    def test_found_tool(self) -> None:
        tool = ToolDefinition(id="test", bin_names=("sh",), desc_en="shell", desc_zh="shell")
        result = _detect_one(tool, "/bin:/usr/bin")
        assert result is not None
        assert result.id == "test"
        assert result.bin_name == "sh"

    def test_not_found_tool(self) -> None:
        tool = ToolDefinition(id="nope", bin_names=("nonexistent_binary_xyz_999",), desc_en="n", desc_zh="n")
        result = _detect_one(tool, "/bin")
        assert result is None


# ============================================================================
# detect_all / refresh_cache
# ============================================================================


class TestDetectAll:
    def test_returns_list(self) -> None:
        result = detect_all()
        assert isinstance(result, list)

    def test_cache_behavior(self) -> None:
        r1 = detect_all(use_cache=True)
        r2 = detect_all(use_cache=True)
        assert r1 is r2

    def test_no_cache(self) -> None:
        r1 = detect_all(use_cache=False)
        r2 = detect_all(use_cache=False)
        assert r1 is not r2
        assert len(r1) == len(r2)


class TestRefreshCache:
    def test_returns_fresh_results(self) -> None:
        r1 = detect_all()
        r2 = refresh_cache()
        assert r1 is not r2
        assert len(r1) == len(r2)


# ============================================================================
# get_cli_tools_context
# ============================================================================


class TestGetCliToolsContext:
    def test_returns_string_when_tools_found(self) -> None:
        mock_tools = [
            DetectedTool(
                id="jq",
                bin_name="jq",
                bin_path=Path("/usr/local/bin/jq"),
                desc_en="JSON processor",
                desc_zh="JSON 处理器",
            ),
        ]
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detect_all", return_value=mock_tools):
            result = get_cli_tools_context(lang="en")
            assert result is not None
            assert "jq" in result
            assert "JSON processor" in result
            assert "<cli_tools>" in result

    def test_returns_none_when_no_tools(self) -> None:
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detect_all", return_value=[]):
            result = get_cli_tools_context()
            assert result is None

    def test_zh_lang(self) -> None:
        mock_tools = [
            DetectedTool(
                id="jq",
                bin_name="jq",
                bin_path=Path("/usr/local/bin/jq"),
                desc_en="JSON processor",
                desc_zh="JSON 处理器",
            ),
        ]
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detect_all", return_value=mock_tools):
            result = get_cli_tools_context(lang="zh-CN")
            assert result is not None
            assert "JSON 处理器" in result

    def test_label_format_with_different_names(self) -> None:
        mock_tools = [
            DetectedTool(
                id="ripgrep", bin_name="rg", bin_path=Path("/usr/bin/rg"), desc_en="fast grep", desc_zh="快速搜索"
            ),
        ]
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detect_all", return_value=mock_tools):
            result = get_cli_tools_context(lang="en")
            assert result is not None
            assert "rg (ripgrep)" in result

    def test_label_format_same_name(self) -> None:
        mock_tools = [
            DetectedTool(
                id="curl", bin_name="curl", bin_path=Path("/usr/bin/curl"), desc_en="HTTP client", desc_zh="HTTP 客户端"
            ),
        ]
        with patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detect_all", return_value=mock_tools):
            result = get_cli_tools_context(lang="en")
            assert result is not None
            assert "curl:" in result
            assert "(curl)" not in result
