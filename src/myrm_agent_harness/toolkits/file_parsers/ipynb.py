"""Jupyter Notebook (.ipynb) parser

Extracts meaningful content (Markdown, code, raw cells) from nbformat v3/v4
notebooks, stripping metadata, outputs, and execution counts that waste LLM
tokens without adding value.

[INPUT]
- base::FileParser (POS: parser abstract base)

[OUTPUT]
- IpynbParser: Jupyter Notebook parser

[POS]
Jupyter Notebook parser. Converts .ipynb JSON to clean structured text,
saving 84-99% tokens compared to raw JSON.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)

_CELL_LABELS: dict[str, str] = {
    "markdown": "Markdown",
    "code": "Code",
    "raw": "Raw",
}


def _source_text(source: str | list[str] | None) -> str:
    """Normalize cell source to a single string (handles both str and list forms)."""
    if source is None:
        return ""
    if isinstance(source, list):
        return "".join(item for item in source if isinstance(item, str))
    return source if isinstance(source, str) else ""


def _extract_kernel_language(metadata: dict[str, object]) -> str:
    """Extract kernel language from notebook metadata, defaulting to 'python'."""
    kernelspec = metadata.get("kernelspec")
    if isinstance(kernelspec, dict):
        lang = kernelspec.get("language")
        if isinstance(lang, str) and lang.strip():
            return lang.strip().lower()

    lang_info = metadata.get("language_info")
    if isinstance(lang_info, dict):
        name = lang_info.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip().lower()

    return "python"


class IpynbParser(FileParser):
    """Jupyter Notebook parser — extracts cells as structured Markdown."""

    async def parse(self, file_path: str) -> str:
        """Parse a .ipynb file and return clean structured text."""
        import aiofiles

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        async with aiofiles.open(file_path, encoding="utf-8", errors="replace") as f:
            raw = await f.read()

        try:
            nb = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid notebook JSON: %s — %s", file_path, exc)
            return raw

        if not isinstance(nb, dict):
            return raw

        metadata = nb.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        kernel_lang = _extract_kernel_language(metadata)

        cells: list[dict[str, object]] = nb.get("cells", [])
        if not isinstance(cells, list) or not cells:
            worksheets = nb.get("worksheets", [])
            if isinstance(worksheets, list):
                cells = [
                    cell
                    for ws in worksheets
                    if isinstance(ws, dict)
                    for cell in (ws.get("cells") or [])
                ]

        if not cells:
            return raw

        counts: dict[str, int] = {"markdown": 0, "code": 0, "raw": 0}
        parts: list[str] = [f"Kernel: {kernel_lang}"]

        for cell in cells:
            if not isinstance(cell, dict):
                continue
            cell_type = cell.get("cell_type")
            if cell_type not in _CELL_LABELS:
                continue

            source = _source_text(cell.get("source")).rstrip("\n")
            if not source:
                continue

            counts[cell_type] += 1
            label = _CELL_LABELS[cell_type]
            header = f"## {label} Cell {counts[cell_type]}"

            if cell_type == "code":
                parts.extend([header, f"```{kernel_lang}", source, "```"])
            else:
                parts.extend([header, source])

        if len(parts) <= 1:
            return raw

        result = "\n\n".join(parts)
        logger.info(
            "Notebook parsed: %s — %d cells, %d chars (raw: %d chars, saved %.0f%%)",
            path.name,
            sum(counts.values()),
            len(result),
            len(raw),
            (1 - len(result) / max(len(raw), 1)) * 100,
        )
        return result

    @property
    def supported_extensions(self) -> list[str]:
        return [".ipynb"]
