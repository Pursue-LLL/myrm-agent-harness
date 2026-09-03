"""
[INPUT]
file_path: str (Path to PDF)
PDFExtractConfig: Configuration (max_pages, min_text_chars, table_format, ocr_pages, ocr_lang)

[OUTPUT]
extract_pdf_content: High-level PDF parsing orchestrator (Text + Hybrid Images + Table Capsules + OCR)
PDFExtractResult: Unified result container

[POS]

Smart PDF extraction orchestrator. Auto-selects Text/Hybrid(embedded image)/Image(full-page
render fallback) strategy. Scanned PDFs (sparse text layer) are additionally OCR'd via the
optional PaddleOCR parser so text-only consumers (RAG ingestion, non-vision models) still
get readable text. Supports Table Encapsulation to prevent RAG chunking from splitting
tables, using L0 summaries to ensure retrieval accuracy.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

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

    max_pages: int = 500
    max_pixels: int = 4_000_000
    min_text_chars: int = 200
    extract_embedded_images: bool = True  # Enable structural embedded extraction
    table_format: Literal["inline", "placeholder"] = "placeholder"  # Default to placeholder for anti-fragmentation
    ocr_pages: int = 30  # Max pages OCR'd for scanned PDFs (0 disables OCR fallback)
    ocr_lang: str = "ch"  # PaddleOCR language ('en', 'japan', 'korean', ...); 'ch' covers Chinese + English


@dataclass
class PDFExtractResult:
    """Result of smart PDF extraction."""

    text: str = ""
    images: list[PDFImageContent] = field(default_factory=list)
    page_count: int = 0
    parsed_pages: int = 0
    strategy: Literal["text", "image", "hybrid", ""] = ""
    tables: list[PDFTable] = field(default_factory=list)
    image_trace: dict[str, object] = field(default_factory=dict)


def _extract_text_sync(
    file_path: str, max_pages: int, table_format: str = "inline"
) -> tuple[str, int, int, list[PDFTable]]:
    """Extract text from PDF using PDFPlumberParser (includes table extraction).

    Returns: (text, page_count, parsed_pages, tables)
    """
    from .pdf import PDFPlumberParser

    parser = PDFPlumberParser(
        extract_tables=True,
        parallel=True,
        table_format=table_format,
        max_pages=max_pages,
    )
    result = parser.parse_sync(file_path)
    page_count: int = int(result.metadata.get("page_count", 0))
    parsed_pages: int = int(result.metadata.get("parsed_pages", min(page_count, max_pages)))

    tables = [t for t in result.tables if t.page_number <= max_pages] if page_count > max_pages else result.tables
    text = result.text

    # Safety fallback: if custom mock or external parser didn't physically slice pages,
    # ensure text does not exceed max_pages while avoiding substring collisions
    if page_count > max_pages:
        page_marker = f"\n[Page {max_pages + 1}]\n"
        idx = text.find(page_marker)
        if idx != -1:
            text = text[:idx]

    return text, page_count, parsed_pages, tables


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
                        logger.debug("Failed to crop embedded image on page %d: %s", page_num, e)
    except Exception as e:
        logger.warning("Error extracting embedded images from PDF: %s", e)

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


async def _ocr_rendered_pages_async(
    images: list[PDFImageContent],
    ocr_pages: int,
    lang: str = "ch",
    confidence_threshold: float = 0.5,
) -> str:
    """Best-effort OCR over rendered page images; returns `[Page N]`-marked text.

    PaddleOCR is optional: when unavailable or a page fails, that page is skipped
    and the caller falls back to its existing behavior. Never raises.
    """
    from myrm_agent_harness.toolkits.file_parsers.ocr import OCRParser

    parser = OCRParser(lang=lang, confidence_threshold=confidence_threshold)
    parts: list[str] = []
    for idx, img in enumerate(images):
        if idx >= ocr_pages:
            break
        try:
            raw = base64.b64decode(img.data)
            page_text = await parser.parse_bytes(raw, suffix=".png")
        except ImportError:
            # PaddleOCR unavailable: remaining pages would fail the same way.
            break
        except Exception as exc:
            logger.warning("PDF OCR failed for page %d: %s", idx + 1, exc)
            continue
        if page_text.strip():
            parts.append(f"[Page {idx + 1}]\n{page_text}")
    return "\n".join(parts)


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
    text, page_count, parsed_pages, all_tables = await asyncio.to_thread(
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
        # Render only the OCR window (all pages when OCR is disabled, e.g. vision-only
        # consumers) so large scans stay bounded in time/memory and render/OCR ranges match.
        render_limit = min(cfg.max_pages, cfg.ocr_pages) if cfg.ocr_pages > 0 else cfg.max_pages
        try:
            raw_images = await asyncio.to_thread(_render_pages_sync, file_path, render_limit, cfg.max_pixels)
        except (ImportError, TypeError):
            logger.warning("pypdfium2 not available, returning sparse text only.")
            strategy = "text"

        # OCR fallback for scanned PDFs (best-effort; PaddleOCR optional).
        # Keeps sparse text intact when OCR is unavailable or every page fails.
        if raw_images and cfg.ocr_pages > 0:
            ocr_text = await _ocr_rendered_pages_async(raw_images, cfg.ocr_pages, lang=cfg.ocr_lang)
            if ocr_text.strip():
                text = ocr_text

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

        logger.info(
            "PDF Extraction Trace: %s | Mode: %s | Kept %d/%d images (Dropped: %s)",
            path.name,
            strategy,
            trace.kept_count,
            trace.total_processed,
            trace.drop_reasons,
        )
    else:
        logger.info("No images extracted for PDF %s. Mode: %s", path.name, strategy)

    # Calibrate strategy: "hybrid" only when images actually survived filtering.
    if strategy == "hybrid" and not filtered_images:
        strategy = "text"

    return PDFExtractResult(
        text=text,
        images=filtered_images,
        page_count=page_count,
        parsed_pages=parsed_pages,
        strategy=strategy,
        tables=all_tables,
        image_trace=trace_dict,
    )
