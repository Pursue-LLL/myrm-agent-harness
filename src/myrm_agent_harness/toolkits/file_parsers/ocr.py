"""OCR parser for images and scanned documents.

Uses PaddleOCR for text extraction from image files (PNG, JPG, TIFF, BMP)
and optionally from rendered PDF pages. Supports CJK languages natively.

[INPUT]
- file_path: str (Path to image file)

[OUTPUT]
- OCRParser: FileParser implementation for image OCR
- OCRResult: Structured OCR result with text, confidence, and per-line details

[POS]
OCR file parser. Extracts text from images using PaddleOCR with lazy import
and graceful degradation when the dependency is not installed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)


@dataclass
class OCRLine:
    """Single OCR-detected text line."""

    text: str
    confidence: float
    bbox: list[list[int]] | None = None


@dataclass
class OCRResult:
    """Structured OCR result."""

    text: str
    lines: list[OCRLine] = field(default_factory=list)
    avg_confidence: float = 0.0
    language: str = ""
    engine: str = "paddleocr"


class OCRParser(FileParser):
    """OCR parser for image files using PaddleOCR.

    Supports PNG, JPG, JPEG, TIFF, BMP, and WEBP formats.
    PaddleOCR is lazily imported on first use.

    Args:
        lang: OCR language ('ch', 'en', 'japan', 'korean', etc.)
              'ch' includes Chinese + English detection.
        use_gpu: Whether to use GPU acceleration (requires paddlepaddle-gpu).
        confidence_threshold: Minimum confidence to include a text line (0.0-1.0).
    """

    _SUPPORTED_EXTENSIONS: ClassVar[list[str]] = [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"]

    def __init__(
        self,
        lang: str = "ch",
        use_gpu: bool = False,
        confidence_threshold: float = 0.5,
    ):
        self._lang = lang
        self._use_gpu = use_gpu
        self._confidence_threshold = confidence_threshold
        self._engine: object | None = None

    def _get_engine(self) -> object:
        """Lazy-initialize PaddleOCR engine."""
        if self._engine is not None:
            return self._engine

        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise ImportError("paddleocr is required for OCRParser. Install with: uv add paddleocr paddlepaddle") from e

        self._engine = PaddleOCR(
            use_angle_cls=True,
            lang=self._lang,
            use_gpu=self._use_gpu,
            show_log=False,
        )
        logger.info("PaddleOCR engine initialized: lang=%s, gpu=%s", self._lang, self._use_gpu)
        return self._engine

    async def parse(self, file_path: str) -> str:
        """Parse image file and return extracted text."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        result = await asyncio.to_thread(self._parse_sync, file_path)

        logger.warning(
            "OCR completed: %s, lines: %d, avg_confidence: %.2f, chars: %d",
            path.name,
            len(result.lines),
            result.avg_confidence,
            len(result.text),
        )
        return result.text

    async def parse_with_details(self, file_path: str) -> OCRResult:
        """Parse image and return structured OCR result with per-line details."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        result = await asyncio.to_thread(self._parse_sync, file_path)
        logger.warning("OCR with details completed: %s", path.name)
        return result

    def _parse_sync(self, file_path: str) -> OCRResult:
        """Synchronous OCR parsing (core logic)."""
        engine = self._get_engine()

        try:
            raw_result = engine.ocr(file_path, cls=True)
        except Exception as e:
            logger.warning("PaddleOCR failed for %s: %s", file_path, e)
            return OCRResult(text="", lines=[], avg_confidence=0.0, engine="paddleocr")

        return self._process_raw_result(raw_result)

    def _process_raw_result(self, raw_result: list | None) -> OCRResult:
        """Process raw PaddleOCR output into structured OCRResult."""
        if not raw_result or not raw_result[0]:
            return OCRResult(text="", lines=[], avg_confidence=0.0, engine="paddleocr")

        lines: list[OCRLine] = []
        total_confidence = 0.0

        for item in raw_result[0]:
            if not item or len(item) < 2:
                continue

            bbox = item[0]
            text_info = item[1]

            if not isinstance(text_info, (list, tuple)) or len(text_info) < 2:
                continue

            text = str(text_info[0]).strip()
            confidence = float(text_info[1])

            if not text or confidence < self._confidence_threshold:
                continue

            lines.append(
                OCRLine(
                    text=text,
                    confidence=confidence,
                    bbox=bbox if isinstance(bbox, list) else None,
                )
            )
            total_confidence += confidence

        avg_confidence = total_confidence / len(lines) if lines else 0.0
        combined_text = "\n".join(line.text for line in lines)

        return OCRResult(
            text=combined_text,
            lines=lines,
            avg_confidence=avg_confidence,
            engine="paddleocr",
        )

    @property
    def supported_extensions(self) -> list[str]:
        return list(self._SUPPORTED_EXTENSIONS)
