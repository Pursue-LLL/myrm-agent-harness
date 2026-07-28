"""Tests for xlsx recalc check."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.utils.office_recalc import (
    run_xlsx_recalc_check,
)


@pytest.mark.asyncio
async def test_recalc_skips_silently_without_soffice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workbook_path = tmp_path / "report.xlsx"
    workbook_path.write_bytes(b"not a real xlsx")
    monkeypatch.setattr(
        "myrm_agent_harness.agent.meta_tools.file_ops.utils.office_recalc.shutil.which",
        lambda _name: None,
    )

    warnings = await run_xlsx_recalc_check(workbook_path)

    assert warnings == []
