"""Tests for layout QA observer."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.layout_qa_observer import (
    run_layout_qa_check,
)


def _write_minimal_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr(
            "word/document.xml",
            b"""<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>""",
        )


@pytest.mark.asyncio
async def test_layout_qa_skips_silently_without_soffice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docx_path = tmp_path / "report.docx"
    _write_minimal_docx(docx_path)
    monkeypatch.setattr(
        "myrm_agent_harness.agent.meta_tools.file_ops.observers.layout_qa_observer.shutil.which",
        lambda _name: None,
    )

    warnings = await run_layout_qa_check(docx_path)

    assert warnings == []
