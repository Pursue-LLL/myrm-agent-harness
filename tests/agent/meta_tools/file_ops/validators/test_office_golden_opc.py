"""Golden-style OPC fidelity checks for Office bash audit."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit import (
    OfficeBashAudit,
)


def _write_docx_with_run_properties(path: Path, run_properties: int) -> None:
    rpr_blocks = "".join("<w:rPr/>" for _ in range(run_properties))
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r>{rpr_blocks}<w:t>Contract clause</w:t></w:r></w:p></w:body>
</w:document>""".encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", document)


@pytest.mark.asyncio
async def test_golden_docx_opc_degradation_detected(tmp_path: Path) -> None:
    """Simulates paragraph.text-style rewrite that strips run properties."""
    docx_path = tmp_path / "contract.docx"
    _write_docx_with_run_properties(docx_path, run_properties=12)
    command = f"python rewrite {docx_path}"
    snapshots = OfficeBashAudit.prepare_snapshots(str(tmp_path), command)
    _write_docx_with_run_properties(docx_path, run_properties=1)

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_layout_qa_check",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.validators.office_bash_audit.run_xlsx_recalc_check",
            new=AsyncMock(return_value=[]),
        ),
    ):
        warnings = await OfficeBashAudit.finalize_audit(
            snapshots,
            str(tmp_path),
            command,
            None,
        )

    assert any("formatting" in warning.lower() for warning in warnings)
