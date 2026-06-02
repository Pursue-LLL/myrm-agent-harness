"""Tests for CLI Tool Discovery module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.tool_discovery import (
    DetectedTool,
    ToolDefinition,
    detect_all,
    get_cli_tools_context,
    refresh_cache,
)
from myrm_agent_harness.toolkits.code_execution.tool_discovery.catalog import (
    TOOL_CATALOG,
)
from myrm_agent_harness.toolkits.code_execution.tool_discovery.detector import (
    _build_extra_dirs,
    _detect_one,
    _expanded_path,
)


class TestToolDefinition:
    def test_frozen_dataclass(self) -> None:
        td = ToolDefinition(
            id="test",
            bin_names=("test_bin",),
            desc_en="Test tool",
            desc_zh="测试工具",
        )
        assert td.id == "test"
        assert td.bin_names == ("test_bin",)
        with pytest.raises(AttributeError):
            td.id = "changed"  # type: ignore[misc]

    def test_default_tags(self) -> None:
        td = ToolDefinition(
            id="t",
            bin_names=("t",),
            desc_en="d",
            desc_zh="d",
        )
        assert td.tags == frozenset()

    def test_custom_tags(self) -> None:
        td = ToolDefinition(
            id="t",
            bin_names=("t",),
            desc_en="d",
            desc_zh="d",
            tags=frozenset({"json_output"}),
        )
        assert "json_output" in td.tags


class TestDetectedTool:
    def test_frozen_dataclass(self) -> None:
        dt = DetectedTool(
            id="git",
            bin_name="git",
            bin_path=Path("/usr/bin/git"),
            desc_en="Version control",
            desc_zh="版本控制",
        )
        assert dt.bin_path == Path("/usr/bin/git")
        with pytest.raises(AttributeError):
            dt.id = "changed"  # type: ignore[misc]


class TestCatalog:
    def test_catalog_not_empty(self) -> None:
        assert len(TOOL_CATALOG) > 0

    def test_unique_ids(self) -> None:
        ids = [t.id for t in TOOL_CATALOG]
        assert len(ids) == len(set(ids)), "Duplicate tool IDs in catalog"

    def test_all_entries_have_descriptions(self) -> None:
        for t in TOOL_CATALOG:
            assert t.desc_en, f"Missing desc_en for {t.id}"
            assert t.desc_zh, f"Missing desc_zh for {t.id}"

    def test_all_entries_have_bin_names(self) -> None:
        for t in TOOL_CATALOG:
            assert len(t.bin_names) > 0, f"No bin_names for {t.id}"


class TestBuildExtraDirs:
    def test_includes_homebrew(self) -> None:
        dirs = _build_extra_dirs()
        assert "/opt/homebrew/bin" in dirs

    def test_includes_local_bin(self) -> None:
        dirs = _build_extra_dirs()
        any_local = any(".local/bin" in d for d in dirs)
        assert any_local

    @patch("myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.Path.home")
    def test_handles_missing_home(self, mock_home: object) -> None:
        from unittest.mock import MagicMock

        mock_home_fn = MagicMock(side_effect=RuntimeError("no home"))
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.Path.home",
            mock_home_fn,
        ):
            dirs = _build_extra_dirs()
            assert "/usr/local/bin" in dirs
            assert not any(".local/bin" in d for d in dirs)


class TestExpandedPath:
    def test_returns_string(self) -> None:
        result = _expanded_path()
        assert isinstance(result, str)

    def test_contains_current_path(self) -> None:
        import os

        current = os.environ.get("PATH", "")
        result = _expanded_path()
        assert current in result


class TestDetectOne:
    def test_found_tool(self) -> None:
        tool = ToolDefinition(
            id="python3",
            bin_names=("python3", "python"),
            desc_en="Python 3",
            desc_zh="Python 3",
        )
        result = _detect_one(tool, _expanded_path())
        assert result is not None
        assert result.id == "python3"
        assert result.bin_path.exists()

    def test_missing_tool(self) -> None:
        tool = ToolDefinition(
            id="nonexistent",
            bin_names=("__nonexistent_tool_xyz__",),
            desc_en="No",
            desc_zh="没有",
        )
        result = _detect_one(tool, _expanded_path())
        assert result is None

    def test_first_match_wins(self) -> None:
        tool = ToolDefinition(
            id="multi",
            bin_names=("python3", "__nonexistent__"),
            desc_en="Multi",
            desc_zh="多",
        )
        result = _detect_one(tool, _expanded_path())
        assert result is not None
        assert result.bin_name == "python3"


class TestDetectAll:
    def test_returns_list(self) -> None:
        results = detect_all(use_cache=False)
        assert isinstance(results, list)

    def test_at_least_one_tool_detected(self) -> None:
        results = detect_all(use_cache=False)
        assert len(results) > 0

    def test_cache_hit(self) -> None:
        first = detect_all(use_cache=False)
        second = detect_all(use_cache=True)
        assert first is second

    def test_no_cache(self) -> None:
        detect_all(use_cache=False)
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detector.shutil.which",
            return_value=None,
        ):
            results = detect_all(use_cache=False)
            assert results == []


class TestRefreshCache:
    def test_returns_fresh_results(self) -> None:
        results = refresh_cache()
        assert isinstance(results, list)


class TestGetCliToolsContext:
    def test_returns_string_when_tools_available(self) -> None:
        result = get_cli_tools_context(lang="en")
        if result is not None:
            assert "<cli_tools>" in result
            assert "</cli_tools>" in result

    def test_english_context(self) -> None:
        result = get_cli_tools_context(lang="en")
        if result is not None:
            assert "<cli_tools>" in result

    def test_chinese_descriptions(self) -> None:
        result = get_cli_tools_context(lang="zh")
        if result is not None:
            assert "<cli_tools>" in result

    def test_returns_none_when_no_tools(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detect_all",
            return_value=[],
        ):
            result = get_cli_tools_context(lang="en")
            assert result is None

    def test_label_format_same_id(self) -> None:
        mock_tool = DetectedTool(
            id="git",
            bin_name="git",
            bin_path=Path("/usr/bin/git"),
            desc_en="Version control",
            desc_zh="版本控制",
        )
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detect_all",
            return_value=[mock_tool],
        ):
            result = get_cli_tools_context(lang="en")
            assert result is not None
            assert "git: Version control" in result

    def test_label_format_different_id(self) -> None:
        mock_tool = DetectedTool(
            id="ripgrep",
            bin_name="rg",
            bin_path=Path("/usr/bin/rg"),
            desc_en="Ultra-fast regex text search",
            desc_zh="超快正则搜索",
        )
        with patch(
            "myrm_agent_harness.toolkits.code_execution.tool_discovery.detect_all",
            return_value=[mock_tool],
        ):
            result = get_cli_tools_context(lang="en")
            assert result is not None
            assert "rg (ripgrep):" in result
