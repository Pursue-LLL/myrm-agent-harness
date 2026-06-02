"""Tests for FormatObserver and FormatterCache."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.format_observer import (
    FORMATTER_RULES,
    FormatObserver,
    FormatterRule,
    _FormatterCache,
)


class TestFormatterRule:
    def test_build_cmd(self):
        rule = FormatterRule(
            extensions=frozenset({".py"}), bin_name="ruff", args_template=("format", "--quiet", "{path}")
        )
        cmd = rule.build_cmd("/tmp/test.py")
        assert cmd == ["ruff", "format", "--quiet", "/tmp/test.py"]

    def test_all_rules_have_extensions(self):
        for rule in FORMATTER_RULES:
            assert len(rule.extensions) > 0
            assert rule.bin_name

    def test_python_has_ruff_and_black(self):
        py_rules = [r for r in FORMATTER_RULES if ".py" in r.extensions]
        bin_names = {r.bin_name for r in py_rules}
        assert "ruff" in bin_names
        assert "black" in bin_names


class TestFormatterCache:
    @pytest.mark.asyncio
    async def test_resolve_unknown_ext(self):
        cache = _FormatterCache()
        with patch("myrm_agent_harness.agent.meta_tools.file_ops.observers.format_observer._which", return_value=None):
            result = await cache.resolve(".xyz")
            assert result is None

    @pytest.mark.asyncio
    async def test_resolve_with_available_formatter(self):
        cache = _FormatterCache()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.observers.format_observer._which",
            side_effect=lambda name: "/usr/bin/ruff" if name == "ruff" else None,
        ):
            result = await cache.resolve(".py")
            assert result is not None
            assert result.bin_name == "ruff"

    @pytest.mark.asyncio
    async def test_first_available_wins(self):
        """ruff should win over black for .py if both available."""
        cache = _FormatterCache()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.observers.format_observer._which", return_value="/usr/bin/found"
        ):
            result = await cache.resolve(".py")
            assert result is not None
            assert result.bin_name == "ruff"

    @pytest.mark.asyncio
    async def test_project_config_detection(self, tmp_path: Path):
        cache = _FormatterCache()
        (tmp_path / "ruff.toml").write_text("")
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.observers.format_observer._which",
            side_effect=lambda name: f"/usr/bin/{name}" if name in ("ruff", "black") else None,
        ):
            result = await cache.resolve(".py", str(test_file))
            assert result is not None
            assert result.bin_name == "ruff"


class TestFormatObserver:
    @pytest.mark.asyncio
    async def test_on_file_created_triggers_format(self):
        observer = FormatObserver()
        with patch.object(observer, "_try_format", new_callable=AsyncMock) as mock:
            await observer.on_file_created("/test.py", "content")
            mock.assert_called_once_with("/test.py")

    @pytest.mark.asyncio
    async def test_on_file_modified_triggers_format(self):
        observer = FormatObserver()
        with patch.object(observer, "_try_format", new_callable=AsyncMock) as mock:
            await observer.on_file_modified("/test.py", "old", "new")
            mock.assert_called_once_with("/test.py")

    @pytest.mark.asyncio
    async def test_on_file_viewed_noop(self):
        observer = FormatObserver()
        await observer.on_file_viewed("/test.py")

    @pytest.mark.asyncio
    async def test_no_extension_skips(self):
        observer = FormatObserver()
        with patch("myrm_agent_harness.agent.meta_tools.file_ops.observers.format_observer._cache") as mock_cache:
            await observer._try_format("/Makefile")
            mock_cache.resolve.assert_not_called()
