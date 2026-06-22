"""Tests for IpynbParser

Tests Jupyter Notebook (.ipynb) parsing: cell extraction, kernel language
detection, v3/v4 format support, error handling, and token savings.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from myrm_agent_harness.toolkits.file_parsers import IpynbParser, get_parser, is_supported
from myrm_agent_harness.toolkits.file_parsers.ipynb import (
    _extract_kernel_language,
    _source_text,
)


class TestIpynbParserRegistry:
    """Test parser registration and discovery."""

    def test_ipynb_is_supported(self) -> None:
        assert is_supported("notebook.ipynb") is True

    def test_get_parser_returns_ipynb_parser(self) -> None:
        parser = get_parser("analysis.ipynb")
        assert isinstance(parser, IpynbParser)

    def test_supported_extensions(self) -> None:
        parser = IpynbParser()
        assert parser.supported_extensions == [".ipynb"]


class TestSourceText:
    """Test _source_text helper."""

    def test_string_source(self) -> None:
        assert _source_text("hello") == "hello"

    def test_list_source(self) -> None:
        assert _source_text(["line1\n", "line2"]) == "line1\nline2"

    def test_none_source(self) -> None:
        assert _source_text(None) == ""

    def test_non_string_items_filtered(self) -> None:
        assert _source_text(["a", 123, "b"]) == "ab"

    def test_non_string_non_list(self) -> None:
        assert _source_text(42) == ""


class TestKernelLanguage:
    """Test _extract_kernel_language helper."""

    def test_from_kernelspec(self) -> None:
        meta = {"kernelspec": {"language": "R"}}
        assert _extract_kernel_language(meta) == "r"

    def test_from_language_info(self) -> None:
        meta = {"language_info": {"name": "Julia"}}
        assert _extract_kernel_language(meta) == "julia"

    def test_kernelspec_priority(self) -> None:
        meta = {
            "kernelspec": {"language": "R"},
            "language_info": {"name": "python"},
        }
        assert _extract_kernel_language(meta) == "r"

    def test_default_python(self) -> None:
        assert _extract_kernel_language({}) == "python"

    def test_empty_string_ignored(self) -> None:
        meta = {"kernelspec": {"language": "  "}}
        assert _extract_kernel_language(meta) == "python"


def _write_notebook(nb: dict[str, object]) -> str:
    fd, path = tempfile.mkstemp(suffix=".ipynb")
    with os.fdopen(fd, "w") as f:
        json.dump(nb, f)
    return path


class TestIpynbParserV4:
    """Test nbformat v4 parsing (cells at top level)."""

    @pytest.fixture()
    def parser(self) -> IpynbParser:
        return IpynbParser()

    @pytest.mark.asyncio()
    async def test_basic_markdown_and_code(self, parser: IpynbParser) -> None:
        nb = {
            "nbformat": 4,
            "metadata": {"kernelspec": {"language": "python"}},
            "cells": [
                {"cell_type": "markdown", "source": "# Title"},
                {"cell_type": "code", "source": "print('hello')"},
            ],
        }
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert "Kernel: python" in result
            assert "## Markdown Cell 1" in result
            assert "# Title" in result
            assert "## Code Cell 1" in result
            assert "```python" in result
            assert "print('hello')" in result
            assert "```" in result
        finally:
            os.unlink(path)

    @pytest.mark.asyncio()
    async def test_raw_cell(self, parser: IpynbParser) -> None:
        nb = {
            "nbformat": 4,
            "metadata": {},
            "cells": [{"cell_type": "raw", "source": "raw content"}],
        }
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert "## Raw Cell 1" in result
            assert "raw content" in result
        finally:
            os.unlink(path)

    @pytest.mark.asyncio()
    async def test_list_source(self, parser: IpynbParser) -> None:
        nb = {
            "nbformat": 4,
            "metadata": {},
            "cells": [
                {"cell_type": "code", "source": ["import os\n", "os.getcwd()"]},
            ],
        }
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert "import os" in result
            assert "os.getcwd()" in result
        finally:
            os.unlink(path)

    @pytest.mark.asyncio()
    async def test_empty_cells_skipped(self, parser: IpynbParser) -> None:
        nb = {
            "nbformat": 4,
            "metadata": {},
            "cells": [
                {"cell_type": "code", "source": "a = 1"},
                {"cell_type": "code", "source": ""},
                {"cell_type": "code", "source": "b = 2"},
            ],
        }
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert "Code Cell 1" in result
            assert "Code Cell 2" in result
            assert "Code Cell 3" not in result
        finally:
            os.unlink(path)

    @pytest.mark.asyncio()
    async def test_metadata_and_outputs_stripped(self, parser: IpynbParser) -> None:
        nb = {
            "nbformat": 4,
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python"}},
            "cells": [
                {
                    "cell_type": "code",
                    "source": "x = 1",
                    "execution_count": 42,
                    "outputs": [{"output_type": "execute_result", "data": {"text/plain": "1"}}],
                },
            ],
        }
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert "execution_count" not in result
            assert "execute_result" not in result
            assert "text/plain" not in result
            assert "x = 1" in result
        finally:
            os.unlink(path)


class TestIpynbParserV3:
    """Test nbformat v3 parsing (cells inside worksheets)."""

    @pytest.fixture()
    def parser(self) -> IpynbParser:
        return IpynbParser()

    @pytest.mark.asyncio()
    async def test_v3_worksheets(self, parser: IpynbParser) -> None:
        nb = {
            "nbformat": 3,
            "metadata": {},
            "worksheets": [
                {
                    "cells": [
                        {"cell_type": "code", "source": "v3_code"},
                        {"cell_type": "markdown", "source": "v3_text"},
                    ]
                }
            ],
        }
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert "v3_code" in result
            assert "v3_text" in result
        finally:
            os.unlink(path)


class TestIpynbParserKernel:
    """Test kernel language detection in output."""

    @pytest.fixture()
    def parser(self) -> IpynbParser:
        return IpynbParser()

    @pytest.mark.asyncio()
    async def test_r_kernel(self, parser: IpynbParser) -> None:
        nb = {
            "nbformat": 4,
            "metadata": {"kernelspec": {"language": "R"}},
            "cells": [{"cell_type": "code", "source": "x <- 1"}],
        }
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert "Kernel: r" in result
            assert "```r" in result
        finally:
            os.unlink(path)


class TestIpynbParserErrorHandling:
    """Test error handling and fallback behavior."""

    @pytest.fixture()
    def parser(self) -> IpynbParser:
        return IpynbParser()

    @pytest.mark.asyncio()
    async def test_invalid_json_returns_raw(self, parser: IpynbParser) -> None:
        fd, path = tempfile.mkstemp(suffix=".ipynb")
        with os.fdopen(fd, "w") as f:
            f.write("{invalid json!!!")
        try:
            result = await parser.parse(path)
            assert result == "{invalid json!!!"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio()
    async def test_non_dict_root_returns_raw(self, parser: IpynbParser) -> None:
        fd, path = tempfile.mkstemp(suffix=".ipynb")
        with os.fdopen(fd, "w") as f:
            json.dump([1, 2, 3], f)
        try:
            result = await parser.parse(path)
            assert "[1, 2, 3]" in result
        finally:
            os.unlink(path)

    @pytest.mark.asyncio()
    async def test_empty_cells_returns_raw(self, parser: IpynbParser) -> None:
        nb = {"nbformat": 4, "metadata": {}, "cells": []}
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert '"cells": []' in result
        finally:
            os.unlink(path)

    @pytest.mark.asyncio()
    async def test_file_not_found(self, parser: IpynbParser) -> None:
        with pytest.raises(FileNotFoundError):
            await parser.parse("/nonexistent/path.ipynb")

    @pytest.mark.asyncio()
    async def test_all_empty_source_returns_raw(self, parser: IpynbParser) -> None:
        nb = {
            "nbformat": 4,
            "metadata": {},
            "cells": [
                {"cell_type": "code", "source": ""},
                {"cell_type": "markdown", "source": ""},
            ],
        }
        path = _write_notebook(nb)
        try:
            result = await parser.parse(path)
            assert '"cells"' in result
        finally:
            os.unlink(path)


class TestIpynbParserTokenSavings:
    """Verify that parsed output is significantly smaller than raw JSON."""

    @pytest.mark.asyncio()
    async def test_token_savings(self) -> None:
        nb = {
            "nbformat": 4,
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                },
                "language_info": {
                    "codemirror_mode": {"name": "ipython", "version": 3},
                    "file_extension": ".py",
                    "mimetype": "text/x-python",
                    "name": "python",
                    "version": "3.10.0",
                },
            },
            "cells": [
                {
                    "cell_type": "code",
                    "source": "x = 1",
                    "execution_count": 1,
                    "outputs": [
                        {
                            "output_type": "execute_result",
                            "data": {"text/plain": "1"},
                            "execution_count": 1,
                            "metadata": {},
                        }
                    ],
                    "metadata": {"trusted": True},
                },
            ],
        }
        raw_json = json.dumps(nb)
        path = _write_notebook(nb)
        try:
            parser = IpynbParser()
            result = await parser.parse(path)
            savings = 1 - len(result) / len(raw_json)
            assert savings > 0.5, f"Expected >50% savings, got {savings:.0%}"
        finally:
            os.unlink(path)
