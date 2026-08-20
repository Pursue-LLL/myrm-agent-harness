"""Jupyter Notebook (.ipynb) parser

Extracts structured Markdown, code, raw cells, execution outputs, and cell tags
from nbformat v3/v4 notebooks. Supports multimodal image extraction (Matplotlib/Seaborn
PNG/JPEG plots) and applies bounded 10K char / 100 line safe truncation to voluminous text
outputs (e.g. large DataFrames/logs) to prevent context explosion.

[INPUT]
- base::FileParser (POS: parser abstract base)

[OUTPUT]
- IpynbParser: Jupyter Notebook parser
- NotebookParsedResult: Container for parsed Markdown text and extracted image blocks

[POS]
Jupyter Notebook parser. Converts .ipynb JSON to clean structured text with embedded
multimodal plot representations and safe output truncation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 10_000
_MAX_OUTPUT_LINES = 100
_MAX_IMAGES_PER_NOTEBOOK = 5

_CELL_LABELS: dict[str, str] = {
    "markdown": "Markdown",
    "code": "Code",
    "raw": "Raw",
}


@dataclass(slots=True)
class NotebookImageBlock:
    """Represents an extracted image output from a notebook cell."""

    mime_type: str
    base64_data: str
    cell_index: int
    output_index: int


@dataclass(slots=True)
class NotebookParsedResult:
    """Result of parsing a notebook, containing text and extracted visual blocks."""

    text: str
    images: list[NotebookImageBlock] = field(default_factory=list)


def _source_text(source: str | list[str] | None) -> str:
    """Normalize cell source to a single string (handles both str and list forms)."""
    if source is None:
        return ""
    if isinstance(source, list):
        return "".join(item for item in source if isinstance(item, str))
    return source if isinstance(source, str) else ""


def _truncate_output_text(text: str, max_chars: int = _MAX_OUTPUT_CHARS, max_lines: int = _MAX_OUTPUT_LINES) -> str:
    """Safely truncate large text/table outputs to prevent context explosion."""
    if not text:
        return ""
    lines = text.splitlines()
    total_lines = len(lines)
    if total_lines > max_lines:
        truncated_lines = lines[:max_lines]
        omitted = total_lines - max_lines
        truncated = "\n".join(truncated_lines)
        if len(truncated) > max_chars:
            truncated = truncated[:max_chars]
        return f"{truncated}\n... [Output truncated: omitted {omitted} lines / total {total_lines} lines]"

    if len(text) > max_chars:
        omitted_chars = len(text) - max_chars
        return f"{text[:max_chars]}\n... [Output truncated: omitted {omitted_chars} chars]"

    return text


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


def _format_cell_tags(metadata: dict[str, object]) -> str:
    """Format cell tags (e.g. parameters, hide_code) as a subtle badge."""
    tags = metadata.get("tags")
    if isinstance(tags, list) and tags:
        valid_tags = [str(t) for t in tags if t]
        if valid_tags:
            return f" `[Tags: {', '.join(valid_tags)}]`"
    return ""


def _extract_cell_outputs(
    outputs: list[object],
    cell_idx: int,
    collected_images: list[NotebookImageBlock],
    max_images: int = _MAX_IMAGES_PER_NOTEBOOK,
) -> list[str]:
    """Parse output objects (stream, execute_result, display_data, error) from a code cell."""
    output_parts: list[str] = []

    for out_idx, out in enumerate(outputs, 1):
        if not isinstance(out, dict):
            continue

        output_type = out.get("output_type")
        if output_type == "stream":
            text = _source_text(out.get("text"))
            if text.strip():
                name = out.get("name", "stdout")
                output_parts.append(f"**Output ({name})**:\n```\n{_truncate_output_text(text)}\n```")

        elif output_type in ("execute_result", "display_data"):
            data = out.get("data")
            if isinstance(data, dict):
                # 1. Check for image plots (PNG/JPEG)
                image_found = False
                for mime in ("image/png", "image/jpeg"):
                    b64_img = data.get(mime)
                    if isinstance(b64_img, str) and b64_img.strip():
                        # Clean whitespace or line breaks in base64 string
                        clean_b64 = "".join(b64_img.split())
                        if len(collected_images) < max_images:
                            collected_images.append(
                                NotebookImageBlock(
                                    mime_type=mime,
                                    base64_data=clean_b64,
                                    cell_index=cell_idx,
                                    output_index=out_idx,
                                )
                            )
                            output_parts.append(
                                f"**Plot Output {len(collected_images)}** ({mime}): `[Extracted Visual Image Block {len(collected_images)}]`"
                            )
                        else:
                            output_parts.append(
                                f"**Plot Output** ({mime}): `[Plot omitted: reached maximum {max_images} images cap]`"
                            )
                        image_found = True
                        break

                # 2. Text or HTML representation
                if not image_found:
                    if "text/plain" in data:
                        text_val = _source_text(data.get("text/plain"))
                        if text_val.strip():
                            output_parts.append(
                                f"**Result**:\n```\n{_truncate_output_text(text_val)}\n```"
                            )
                    elif "text/html" in data:
                        html_val = _source_text(data.get("text/html"))
                        if html_val.strip():
                            output_parts.append(
                                f"**HTML Output**:\n```html\n{_truncate_output_text(html_val)}\n```"
                            )

        elif output_type == "error":
            ename = out.get("ename", "Error")
            evalue = out.get("evalue", "")
            traceback = out.get("traceback")
            tb_text = "\n".join(traceback) if isinstance(traceback, list) else str(traceback or "")
            error_body = tb_text if tb_text.strip() else f"{ename}: {evalue}"
            output_parts.append(f"**Error ({ename})**:\n```\n{_truncate_output_text(error_body)}\n```")

    return output_parts


class IpynbParser(FileParser):
    """Jupyter Notebook parser — extracts cells as structured Markdown with multimodal support."""

    async def parse_with_images(self, file_path: str) -> NotebookParsedResult:
        """Parse a .ipynb file and return text + extracted plot image blocks."""
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
            return NotebookParsedResult(text=raw)

        if not isinstance(nb, dict):
            return NotebookParsedResult(text=raw)

        metadata = nb.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        kernel_lang = _extract_kernel_language(metadata)

        cells: list[dict[str, object]] = nb.get("cells", [])
        if not isinstance(cells, list) or not cells:
            worksheets = nb.get("worksheets", [])
            if isinstance(worksheets, list):
                cells = [cell for ws in worksheets if isinstance(ws, dict) for cell in (ws.get("cells") or [])]

        if not cells:
            return NotebookParsedResult(text=raw)

        counts: dict[str, int] = {"markdown": 0, "code": 0, "raw": 0}
        parts: list[str] = [f"Kernel: {kernel_lang}"]
        images: list[NotebookImageBlock] = []

        for cell_idx, cell in enumerate(cells, 1):
            if not isinstance(cell, dict):
                continue
            cell_type = cell.get("cell_type")
            if cell_type not in _CELL_LABELS:
                continue

            source = _source_text(cell.get("source")).rstrip("\n")
            cell_meta = cell.get("metadata")
            tags_badge = _format_cell_tags(cell_meta if isinstance(cell_meta, dict) else {})

            counts[cell_type] += 1
            label = _CELL_LABELS[cell_type]
            header = f"## {label} Cell {counts[cell_type]}{tags_badge}"

            if cell_type == "code":
                cell_parts = [header]
                if source:
                    cell_parts.extend([f"```{kernel_lang}", source, "```"])

                # Parse cell outputs (plots, tables, streams, errors)
                outputs = cell.get("outputs")
                if isinstance(outputs, list) and outputs:
                    out_text_blocks = _extract_cell_outputs(outputs, cell_idx, images)
                    if out_text_blocks:
                        cell_parts.extend(out_text_blocks)

                parts.append("\n\n".join(cell_parts))
            else:
                if source:
                    parts.extend([header, source])

        if len(parts) <= 1:
            return NotebookParsedResult(text=raw)

        result = "\n\n".join(parts)
        logger.info(
            "Notebook parsed: %s — %d cells, %d chars, %d images extracted (raw: %d chars, saved %.0f%%)",
            path.name,
            sum(counts.values()),
            len(result),
            len(images),
            len(raw),
            (1 - len(result) / max(len(raw), 1)) * 100,
        )
        return NotebookParsedResult(text=result, images=images)

    async def parse(self, file_path: str) -> str:
        """Parse a .ipynb file and return clean structured text (FileParser contract)."""
        res = await self.parse_with_images(file_path)
        return res.text

    @property
    def supported_extensions(self) -> list[str]:
        return [".ipynb"]
