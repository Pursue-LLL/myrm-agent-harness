"""Layout QA helper for Office documents after writes.

[INPUT]
- Path to .docx on disk

[OUTPUT]
- run_layout_qa_check: optional soffice conversion sanity check

[POS]
Optional soffice headless PDF conversion check; invoked by OfficeBashAudit finalize step.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_layout_qa_check(file_path: Path) -> list[str]:
    """Run a lightweight layout QA gate when soffice is available."""
    warnings: list[str] = []
    if file_path.suffix.lower() not in {".docx", ".doc"}:
        return warnings
    if not file_path.is_file():
        return warnings

    soffice = shutil.which("soffice")
    if soffice is None:
        logger.debug("Layout QA skipped: soffice not available for %s", file_path)
        return warnings

    with tempfile.TemporaryDirectory(prefix="office-layout-qa-") as tmp_dir:
        tmp = Path(tmp_dir)
        cmd = [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp),
            str(file_path.resolve()),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()
        except OSError as exc:
            logger.warning("Layout QA soffice failed for %s: %s", file_path, exc)
            warnings.append(f"Layout QA failed to run soffice: {exc}")
            return warnings

        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            warnings.append(
                f"Layout QA failed: soffice could not convert {file_path.name} "
                f"(exit {proc.returncode}). {detail[:200]}"
            )
            return warnings

        pdf_path = tmp / f"{file_path.stem}.pdf"
        if not pdf_path.is_file() or pdf_path.stat().st_size < 128:
            warnings.append(
                f"Layout QA failed: converted PDF for {file_path.name} is missing or empty."
            )

    return warnings

