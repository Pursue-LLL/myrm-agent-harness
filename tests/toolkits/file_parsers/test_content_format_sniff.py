"""Tests for content-based file format sniffing."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.file_parsers import get_parser, is_supported
from myrm_agent_harness.toolkits.file_parsers.content_format_sniff import (
    sniff_content_format,
)
from myrm_agent_harness.toolkits.file_parsers.csv_parser import CsvParser
from myrm_agent_harness.toolkits.file_parsers.rtf_parser import RtfParser


def test_sniff_pdf_from_mislabeled_path(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_bytes(b"%PDF-1.4 fake pdf body")
    assert sniff_content_format(target) == ".pdf"
    assert is_supported(str(target)) is True
    assert isinstance(get_parser(str(target)), object)


def test_sniff_rtf(tmp_path: Path) -> None:
    target = tmp_path / "upload.bin"
    target.write_text("{\\rtf1\\ansi Hello RTF}", encoding="utf-8")
    assert sniff_content_format(target) == ".rtf"
    assert isinstance(get_parser(str(target)), RtfParser)


def test_sniff_csv_text(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_text("name,score\nalice,1\nbob,2\n", encoding="utf-8")
    assert sniff_content_format(target) == ".csv"
    assert isinstance(get_parser(str(target)), CsvParser)


def test_sniff_epub_mimetype(tmp_path: Path) -> None:
    target = tmp_path / "book.dat"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("chapter.xhtml", "<html><body><p>Hello EPUB</p></body></html>")
    assert sniff_content_format(target) == ".epub"


@pytest.mark.asyncio
async def test_csv_parser_renders_markdown_table(tmp_path: Path) -> None:
    target = tmp_path / "grid.csv"
    target.write_text("h1,h2\nv1,v2\n", encoding="utf-8")
    parser = CsvParser()
    text = await parser.parse(str(target))
    assert "| h1 | h2 |" in text
    assert "| v1 | v2 |" in text
