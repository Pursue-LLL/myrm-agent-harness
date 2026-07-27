"""Tests for LegacyFormatParser

Tests OLE2 magic detection, non-OLE2 passthrough to delegate, and soffice
unavailability error handling.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.file_parsers import LegacyFormatParser
from myrm_agent_harness.toolkits.file_parsers.base import FileParser

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class _FakeDelegate(FileParser):
    """Delegate that records calls and returns fixed text."""

    def __init__(self) -> None:
        self.called_with: str | None = None

    async def parse(self, file_path: str) -> str:
        self.called_with = file_path
        return "delegate-result"

    @property
    def supported_extensions(self) -> list[str]:
        return [".docx"]


class TestOLE2Detection:
    """Test _is_ole2 correctly identifies OLE2 vs non-OLE2 files."""

    def test_ole2_magic_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "legacy.doc"
        f.write_bytes(_OLE2_MAGIC + b"\x00" * 100)
        parser = LegacyFormatParser(".docx", _FakeDelegate())
        assert parser._is_ole2(f) is True

    def test_non_ole2_not_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "modern.doc"
        f.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        parser = LegacyFormatParser(".docx", _FakeDelegate())
        assert parser._is_ole2(f) is False

    def test_short_file_not_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "tiny.doc"
        f.write_bytes(b"\xd0\xcf")
        parser = LegacyFormatParser(".docx", _FakeDelegate())
        assert parser._is_ole2(f) is False

    def test_missing_file_not_detected(self, tmp_path: Path) -> None:
        parser = LegacyFormatParser(".docx", _FakeDelegate())
        assert parser._is_ole2(tmp_path / "nonexistent.doc") is False


class TestNonOLE2Passthrough:
    """When file is NOT OLE2 (e.g. a .docx renamed to .doc), delegate directly."""

    @pytest.mark.asyncio
    async def test_passthrough_to_delegate(self, tmp_path: Path) -> None:
        f = tmp_path / "modern.doc"
        f.write_bytes(b"PK\x03\x04" + b"\x00" * 100)

        delegate = _FakeDelegate()
        parser = LegacyFormatParser(".docx", delegate)
        result = await parser.parse(str(f))

        assert result == "delegate-result"
        assert delegate.called_with == str(f)


class TestSofficeUnavailable:
    """When file IS OLE2 but soffice is not installed, raise RuntimeError."""

    @pytest.mark.asyncio
    async def test_raises_when_soffice_missing(self, tmp_path: Path) -> None:
        f = tmp_path / "legacy.doc"
        f.write_bytes(_OLE2_MAGIC + b"\x00" * 100)

        parser = LegacyFormatParser(".docx", _FakeDelegate())
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="soffice is not available"):
                await parser.parse(str(f))


class TestFileNotFound:
    """parse() raises FileNotFoundError for missing files."""

    @pytest.mark.asyncio
    async def test_missing_file_raises(self) -> None:
        parser = LegacyFormatParser(".docx", _FakeDelegate())
        with pytest.raises(FileNotFoundError):
            await parser.parse("/nonexistent/path/file.doc")


class TestSupportedExtensions:
    """Test supported_extensions property."""

    def test_docx_target(self) -> None:
        parser = LegacyFormatParser(".docx", _FakeDelegate())
        assert parser.supported_extensions == [".doc"]

    def test_xlsx_target(self) -> None:
        parser = LegacyFormatParser(".xlsx", _FakeDelegate())
        assert parser.supported_extensions == [".xls"]

    def test_pptx_target(self) -> None:
        parser = LegacyFormatParser(".pptx", _FakeDelegate())
        assert parser.supported_extensions == [".ppt"]
