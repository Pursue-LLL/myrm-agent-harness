"""Fixture-style regression tests for content sniff routing."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.file_parsers import get_parser
from myrm_agent_harness.toolkits.file_parsers.content_format_sniff import (
    sniff_content_format,
)
from myrm_agent_harness.toolkits.file_parsers.gfm_normalize import (
    normalize_to_gfm_markdown,
)


@pytest.mark.parametrize(
    ("filename", "payload", "expected_ext"),
    [
        ("mislabeled.txt", b"%PDF-1.4\n", ".pdf"),
        ("upload.bin", b"{\\rtf1\\ansi Snapshot}", ".rtf"),
        ("data.dat", b"a,b\n1,2\n3,4\n", ".csv"),
    ],
)
def test_sniff_fixture_matrix(
    tmp_path: Path,
    filename: str,
    payload: bytes,
    expected_ext: str,
) -> None:
    target = tmp_path / filename
    target.write_bytes(payload)
    assert sniff_content_format(target) == expected_ext


@pytest.mark.asyncio
async def test_sniff_fixture_epub_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "book.wrongext"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "chapter.xhtml", "<html><body><p>Fixture EPUB</p></body></html>"
        )
    assert sniff_content_format(target) == ".epub"
    parser = get_parser(str(target))
    text = normalize_to_gfm_markdown(await parser.parse(str(target)))
    assert "Fixture EPUB" in text
