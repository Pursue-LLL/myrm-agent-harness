"""Tests for FileReadInput alias mapping, Pre-IO device protection, line range parsing, and Unicode path healing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import (
    FileReadInput,
    create_file_read_tool,
)
from myrm_agent_harness.agent.meta_tools.file_ops.utils.file_utils import parse_path_with_range
from myrm_agent_harness.core.context_vars import workspace_root_var
from myrm_agent_harness.utils.errors import ToolError


class TestFileReadInputAliases:
    """Verify FileReadInput maps various parameter aliases to paths."""

    def test_paths_direct(self) -> None:
        model = FileReadInput.model_validate({"paths": ["a.txt", "b.txt"]})
        assert model.paths == ["a.txt", "b.txt"]

    def test_filepath_alias(self) -> None:
        model = FileReadInput.model_validate({"filePath": ["src/app.py"]})
        assert model.paths == ["src/app.py"]

    def test_file_path_alias(self) -> None:
        model = FileReadInput.model_validate({"file_path": "src/app.py"})
        assert model.paths == ["src/app.py"]

    def test_path_alias(self) -> None:
        model = FileReadInput.model_validate({"path": "src/main.rs"})
        assert model.paths == ["src/main.rs"]

    def test_filename_alias(self) -> None:
        model = FileReadInput.model_validate({"filename": "index.ts"})
        assert model.paths == ["index.ts"]

    def test_files_alias(self) -> None:
        model = FileReadInput.model_validate({"files": ["a.go", "b.go"]})
        assert model.paths == ["a.go", "b.go"]

    def test_target_alias(self) -> None:
        model = FileReadInput.model_validate({"target": "README.md"})
        assert model.paths == ["README.md"]


class TestParsePathWithRangeValidation:
    """Verify parse_path_with_range validates positive line numbers and ordered ranges."""

    def test_valid_ranges(self) -> None:
        p, r = parse_path_with_range("app.py:1-50")
        assert p == "app.py"
        assert r is not None
        assert r.start == 1
        assert r.end == 50

        p, r = parse_path_with_range("app.py:100-")
        assert p == "app.py"
        assert r is not None
        assert r.start == 100
        assert r.end == -1

    def test_invalid_start_zero(self) -> None:
        with pytest.raises(ValueError, match="must be a positive integer"):
            parse_path_with_range("app.py:0-50")

    def test_inverted_range_start_greater_than_end(self) -> None:
        with pytest.raises(ValueError, match="cannot be less than start line"):
            parse_path_with_range("app.py:50-10")

    def test_no_range_simple_path(self) -> None:
        p, r = parse_path_with_range("app.py")
        assert p == "app.py"
        assert r is None

    def test_file_id_resolution(self) -> None:
        p, r = parse_path_with_range("@file_001")
        assert p == "@file_001"
        assert r is None


class TestFileReadPreIODevicesAndUnicode:
    """Verify Pre-IO device blocking and Unicode auto-healing in file_read_tool."""

    @pytest.mark.asyncio
    async def test_blocked_device_interception(self) -> None:
        tool = create_file_read_tool()
        config = {"configurable": {"context": {}}}

        # POSIX device
        with pytest.raises(ToolError, match="Access to device path is blocked"):
            await tool.ainvoke({"paths": ["/dev/zero"]}, config=config)

        # Windows device
        with pytest.raises(ToolError, match="Access to device path is blocked"):
            await tool.ainvoke({"paths": ["CON"]}, config=config)

        with pytest.raises(ToolError, match="Access to device path is blocked"):
            await tool.ainvoke({"paths": ["aux.json"]}, config=config)

    @pytest.mark.asyncio
    async def test_unicode_path_auto_healing(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target_file = workspace / "data_schema.json"
        target_file.write_text('{"status": "ok"}', encoding="utf-8")

        token = workspace_root_var.set(str(workspace))
        try:
            tool = create_file_read_tool()
            config = {"configurable": {"context": {"workspace_root": str(workspace)}}}

            with patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
                new_callable=AsyncMock,
                return_value=['{"status": "ok"}'],
            ) as mock_process:
                # Pass curly quotes around filename
                result = await tool.ainvoke({"paths": ["“data_schema.json”"]}, config=config)
                assert '{"status": "ok"}' in str(result)
                # Verify healed path was passed to process_text_paths
                mock_process.assert_called_once()
                call_paths = mock_process.call_args[0][0]
                assert call_paths == ["data_schema.json"]
        finally:
            workspace_root_var.reset(token)


class TestDocumentReaderMultimodalAndMagicBytes:
    """Verify document_reader returns multimodal image blocks for .ipynb and sniffs magic bytes."""

    @pytest.mark.asyncio
    async def test_ipynb_multimodal_blocks_emitted(self, tmp_path: Path) -> None:
        fake_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        nb = {
            "nbformat": 4,
            "metadata": {"kernelspec": {"language": "python"}},
            "cells": [
                {
                    "cell_type": "code",
                    "source": "import matplotlib.pyplot as plt\nplt.plot([1, 2])",
                    "outputs": [
                        {
                            "output_type": "display_data",
                            "data": {"image/png": fake_b64},
                        }
                    ],
                }
            ],
        }
        nb_file = tmp_path / "plot_test.ipynb"
        nb_file.write_text(json.dumps(nb), encoding="utf-8")

        executor = AsyncMock()
        executor.read_file_bytes.return_value = nb_file.read_bytes()

        from myrm_agent_harness.agent.meta_tools.file_ops.utils.document_reader import (
            read_document_multimodal,
        )

        blocks = await read_document_multimodal(
            str(nb_file),
            executor,
            supports_vision=True,
        )
        assert len(blocks) == 3
        assert "**Plot Output 1** (image/png)" in blocks[0]["text"]
        assert "Notebook Plot: cell 1, output 1" in blocks[1]["text"]
        assert blocks[2]["type"] in ("image", "image_url")
        b64 = blocks[2].get("base64") or blocks[2].get("data")
        assert b64 == fake_b64
