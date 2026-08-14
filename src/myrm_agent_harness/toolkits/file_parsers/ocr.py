"""OCR parser for images and scanned documents.

Uses PaddleOCR for text extraction from image files (PNG, JPG, TIFF, BMP)
and optionally from rendered PDF pages. Supports CJK languages natively.

[INPUT]
- file_path: str (Path to image file)
- PDF rendered page bytes via parse_bytes (toolkits/file_parsers/pdf_content_extractor.py)

[OUTPUT]
- OCRParser: FileParser implementation for image OCR
- OCRResult: Structured OCR result with text, confidence, and per-line details

[POS]
OCR file parser. Extracts text from images using PaddleOCR with lazy import,
graceful degradation when the dependency is not installed, and 2.x/3.x
engine compatibility (PaddleX unified inference API in 3.x).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
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
        """Lazy-initialize PaddleOCR engine (2.x / 3.x compatible)."""
        if self._engine is not None:
            return self._engine

        try:
            from paddleocr import PaddleOCR
            from paddleocr import __version__ as paddleocr_version
        except ImportError as e:
            raise ImportError("paddleocr is required for OCRParser. Install with: uv add paddleocr paddlepaddle") from e

        major = int(paddleocr_version.split(".")[0])
        if major >= 3:
            # 3.x: use_textline_orientation / device replace use_angle_cls / use_gpu
            self._engine = PaddleOCR(
                use_textline_orientation=True,
                lang=self._lang,
                device="gpu" if self._use_gpu else "cpu",
            )
        else:
            self._engine = PaddleOCR(
                use_angle_cls=True,
                lang=self._lang,
                use_gpu=self._use_gpu,
                show_log=False,
            )
        logger.info(
            "PaddleOCR engine initialized: lang=%s, gpu=%s, v%s",
            self._lang,
            self._use_gpu,
            paddleocr_version,
        )
        return self._engine

    async def parse_bytes(self, raw: bytes, *, suffix: str = ".png") -> str:
        """Parse in-memory image bytes (sandbox-safe)."""
        if not raw:
            return ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            return await self.parse(tmp.name)

    async def parse(self, file_path: str) -> str:
        """Parse image file and return extracted text."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        result = await asyncio.to_thread(self._parse_sync, file_path)

        logger.info(
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
        logger.info("OCR with details completed: %s", path.name)
        return result

    def _parse_sync(self, file_path: str) -> OCRResult:
        """Synchronous OCR parsing (core logic)."""
        engine = self._get_engine()

        try:
            if self._uses_paddlex_api():
                raw_result = engine.predict(file_path)
            else:
                raw_result = engine.ocr(file_path, cls=True)
        except Exception as e:
            logger.warning("PaddleOCR failed for %s: %s", file_path, e)
            return OCRResult(text="", lines=[], avg_confidence=0.0, engine="paddleocr")

        return self._process_raw_result(raw_result)

    def _uses_paddlex_api(self) -> bool:
        """Detect the loaded engine generation for inference-call compatibility."""
        from paddleocr import __version__ as paddleocr_version

        return int(paddleocr_version.split(".")[0]) >= 3

    def _process_raw_result(self, raw_result: list | None) -> OCRResult:
        """Process raw PaddleOCR output into structured OCRResult (2.x/3.x)."""
        if not raw_result or not raw_result[0]:
            return OCRResult(text="", lines=[], avg_confidence=0.0, engine="paddleocr")

        first = raw_result[0]
        if isinstance(first, dict) and "rec_texts" in first:
            # 3.x: PaddleX OCRResult is dict-like with rec_texts/rec_scores/dt_polys
            return self._process_paddlex_result(first)

        # 2.x: nested list of [bbox, (text, confidence)]
        lines: list[OCRLine] = []
        total_confidence = 0.0

        for item in first:
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

    def _process_paddlex_result(self, result: dict) -> OCRResult:
        """Process a PaddleX OCRResult (3.x) into structured OCRResult."""
        texts = [str(t) for t in (result.get("rec_texts") or [])]
        scores = [float(s) for s in (result.get("rec_scores") or [])]
        polys = result.get("dt_polys") or []

        lines: list[OCRLine] = []
        for idx, text in enumerate(texts):
            if not text.strip():
                continue
            confidence = scores[idx] if idx < len(scores) else 0.0
            if confidence < self._confidence_threshold:
                continue
            raw_poly = polys[idx] if idx < len(polys) else None
            # PaddleX dt_polys entries are numpy arrays; expose plain lists (2.x parity).
            bbox = raw_poly.tolist() if hasattr(raw_poly, "tolist") else raw_poly
            lines.append(OCRLine(text=text, confidence=confidence, bbox=bbox))

        avg_confidence = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
        return OCRResult(
            text="\n".join(line.text for line in lines),
            lines=lines,
            avg_confidence=avg_confidence,
            engine="paddleocr",
        )

    @property
    def supported_extensions(self) -> list[str]:
        return list(self._SUPPORTED_EXTENSIONS)
