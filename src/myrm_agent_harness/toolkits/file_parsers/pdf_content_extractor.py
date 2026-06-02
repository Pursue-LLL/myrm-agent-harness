"""
[INPUT]
file_path: str (Path to PDF)
PDFExtractConfig: Configuration (max_pages, min_text_chars, table_format)

[OUTPUT]
extract_pdf_content: High-level PDF parsing orchestrator (Text + Hybrid Images + Table Capsules)
PDFExtractResult: Unified result container

[POS]

Smart PDF extraction orchestrator. Auto-selects Text/Hybrid(embedded image)/Image(full-page
render fallback) strategy. Supports Table Encapsulation to prevent RAG chunking from
splitting tables, using L0 summaries to ensure retrieval accuracy.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from myrm_agent_harness.toolkits.file_parsers.base import PDFTable
from myrm_agent_harness.toolkits.file_parsers.image_filter import ImageAblationFilter

logger = logging.getLogger(__name__)


@dataclass
class PDFImageContent:
    """Single page or embedded object rendered as a base64-encoded PNG."""

    data: str
    mime_type: str = "image/png"


@dataclass
class PDFExtractConfig:
    """Tunable limits for PDF extraction."""

    max_pages: int = 20
    max_pixels: int = 4_000_000
    min_text_chars: int = 200
    extract_embedded_images: bool = True  # Enable structural embedded extraction
    table_format: Literal["inline", "placeholder"] = "placeholder"  # Default to placeholder for anti-fragmentation


@dataclass
class PDFExtractResult:
    """Result of smart PDF extraction."""

    text: str = ""
    images: list[PDFImageContent] = field(default_factory=list)
    page_count: int = 0
    strategy: Literal["text", "image", "hybrid", ""] = ""
    tables: list[PDFTable] = field(default_factory=list)  # Added capsules field
    image_trace: dict[str, Any] = field(default_factory=dict)


def _extract_text_sync(file_path: str, max_pages: int, table_format: str = "inline") -> tuple[str, int, list[PDFTable]]:
    """Extract text from PDF using PDFPlumberParser (includes table extraction)."""
    from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser

    parser = PDFPlumberParser(extract_tables=True, parallel=False, table_format=table_format)
    result = parser.parse_sync(file_path)
    page_count: int = int(result.metadata.get("page_count", 0))

    if page_count > max_pages:
        lines = result.text.split("\n")
        trimmed: list[str] = []
        page_marker = f"[Page {max_pages + 1}]"
        for line in lines:
            if line.strip().startswith(page_marker):
                break
            trimmed.append(line)
        return "\n".join(trimmed), page_count, result.tables

    return result.text, page_count, result.tables


def _extract_embedded_images_sync(file_path: str, max_pages: int) -> list[PDFImageContent]:
    """Smartly extract structural embedded images (charts, photos) while ignoring background artifacts."""
    try:
        import pdfplumber
    except (ImportError, TypeError):
        logger.warning("pdfplumber required for embedded image extraction.")
        return []

    images: list[PDFImageContent] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            pages_to_render = min(len(pdf.pages), max_pages)
            for page_num in range(pages_to_render):
                page = pdf.pages[page_num]
                for img_obj in page.images:
                    x0, top, x1, bottom = (
                        img_obj.get("x0", 0),
                        img_obj.get("top", 0),
                        img_obj.get("x1", 0),
                        img_obj.get("bottom", 0),
                    )
                    if x1 <= x0 or bottom <= top:
                        continue

                    # Pre-filter extremely small bounding boxes to save CPU rendering overhead
                    if (x1 - x0) < 40 or (bottom - top) < 40:
                        continue

                    bbox = (x0, top, x1, bottom)
                    try:
                        # Crop via pdfplumber preserves exact page rendering of that object without manual color decoding
                        cropped = page.crop(bbox, strict=False)
                        pil_image = cropped.to_image(resolution=150).original
                        buf = io.BytesIO()
                        pil_image.save(buf, format="PNG")
                        b64_data = base64.b64encode(buf.getvalue()).decode("ascii")
                        images.append(PDFImageContent(data=b64_data))
                    except Exception as e:
                        logger.debug(f"Failed to crop embedded image on page {page_num}: {e}")
    except Exception as e:
        logger.warning(f"Error extracting embedded images from PDF: {e}")

    return images


def _render_pages_sync(
    file_path: str,
    max_pages: int,
    max_pixels: int,
) -> list[PDFImageContent]:
    """Render full PDF pages as PNG images (fallback for scanned documents)."""
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise ImportError("pypdfium2 is required for PDF image rendering. Run: uv add pypdfium2") from e

    images: list[PDFImageContent] = []
    pdf = pdfium.PdfDocument(file_path)

    try:
        pages_to_render = min(len(pdf), max_pages)

        for page_num in range(pages_to_render):
            try:
                page = pdf.get_page(page_num)
                width, height = page.get_size()
                page_pixels = width * height

                if page_pixels > max_pixels and page_pixels > 0:
                    scale = math.sqrt(max_pixels / page_pixels)
                else:
                    scale = 1.0

                scale = max(0.1, min(scale, 2.0))
                pil_image = page.render(scale=scale).to_pil()

                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                b64_data = base64.b64encode(buf.getvalue()).decode("ascii")
                images.append(PDFImageContent(data=b64_data))

            except Exception as e:
                logger.warning("PDF page %d render failed: %s", page_num + 1, e)
    finally:
        pdf.close()

    return images


async def extract_pdf_content(
    file_path: str,
    config: PDFExtractConfig | None = None,
) -> PDFExtractResult:
    """Smart PDF content extraction pipeline."""
    cfg = config or PDFExtractConfig()
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    # Phase 1: Text & Tables
    text, page_count, all_tables = await asyncio.to_thread(
        _extract_text_sync, file_path, cfg.max_pages, cfg.table_format
    )

    # Phase 2: Images
    raw_images: list[PDFImageContent] = []
    strategy: Literal["text", "image", "hybrid"] = "hybrid"

    if len(text.strip()) >= cfg.min_text_chars:
        if cfg.extract_embedded_images:
            raw_images = await asyncio.to_thread(_extract_embedded_images_sync, file_path, cfg.max_pages)
        else:
            strategy = "text"
    else:
        # Text sparse -> Scanned PDF
        strategy = "image"
        try:
            raw_images = await asyncio.to_thread(_render_pages_sync, file_path, cfg.max_pages, cfg.max_pixels)
        except (ImportError, TypeError):
            logger.warning("pypdfium2 not available, returning sparse text only.")
            strategy = "text"

    # Phase 3: Ablation Filter (Smart meaning verification)
    filtered_images: list[PDFImageContent] = []
    trace_dict = {}

    if raw_images:
        filter_svc = ImageAblationFilter()
        b64_list = [img.data for img in raw_images]
        kept_b64, trace = filter_svc.filter_images(b64_list)

        for data in kept_b64:
            filtered_images.append(PDFImageContent(data=data))

        trace_dict = {
            "total_processed": trace.total_processed,
            "kept_count": trace.kept_count,
            "dropped_count": trace.dropped_count,
            "drop_reasons": trace.drop_reasons,
        }

        logger.warning(
            "PDF Extraction Trace: %s | Mode: %s | Kept %d/%d images (Dropped: %s)",
            path.name,
            strategy,
            trace.kept_count,
            trace.total_processed,
            trace.drop_reasons,
        )
    else:
        logger.warning("No images extracted for PDF %s. Mode: %s", path.name, strategy)

    return PDFExtractResult(
        text=text,
        images=filtered_images,
        page_count=page_count,
        strategy=strategy,
        tables=all_tables,
        image_trace=trace_dict,
    )
