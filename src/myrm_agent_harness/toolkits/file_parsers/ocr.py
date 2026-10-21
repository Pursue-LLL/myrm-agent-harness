"""OCR parser for images and scanned documents.

Uses RapidOCR (ONNX Runtime) for text extraction from image files (PNG, JPG,
TIFF, BMP) and optionally from rendered PDF pages. Supports CJK languages
natively.

[INPUT]
- file_path: str (Path to image file)
- PDF rendered page bytes via parse_bytes (toolkits/file_parsers/pdf_content_extractor.py)

[OUTPUT]
- OCRParser: FileParser implementation for image OCR
- OCRResult: Structured OCR result with text, confidence, and per-line details

[POS]
OCR file parser. Extracts text from images using RapidOCR with a lazy import; a missing
engine surfaces as an ``ImportError`` at call time (the file_parsers convention, so a
misconfigured deployment is visible instead of silently returning empty text). RapidOCR
runs the PP-OCR models on ONNX Runtime, so it carries no PyTorch/PaddlePaddle weight and
does not pin PyYAML/numpy against the rest of the dependency tree.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol, cast

from myrm_agent_harness.toolkits.file_parsers.base import FileParser

logger = logging.getLogger(__name__)


class _OcrEngine(Protocol):
    """The slice of RapidOCR's engine surface this parser calls."""

    def __call__(self, img_content: str) -> object:
        """Run detection + recognition and return the OCR result."""
        ...


# RapidOCR engine name -> the detection/recognition language it runs. PP-OCR ships a
# Chinese recognizer that also covers Latin script, so it is the default for 'ch'.
_REC_LANG_ALIASES: dict[str, str] = {"chinese": "ch", "english": "en"}
# Detector language must match the recognizer script, or CJK pages degrade badly.
_DET_LANG_FOR_SCRIPT: dict[str, str] = {
    "ch": "ch",
    "chinese_cht": "ch",
    "japan": "ch",
    "korean": "ch",
    "en": "en",
    "latin": "en",
}
_DEFAULT_REC_LANG = "ch"


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
    engine: str = "rapidocr"


class OCRParser(FileParser):
    """OCR parser for image files using RapidOCR.

    Supports PNG, JPG, JPEG, TIFF, BMP, and WEBP formats. The engine is lazily
    imported and built on first use; a missing dependency surfaces as an
    ``ImportError`` at call time so callers can degrade instead of crashing import.

    Args:
        lang: OCR recognition language ('ch', 'en', 'japan', 'korean', ...).
              'ch' covers Chinese + English detection.
        use_gpu: Whether to request GPU execution providers (falls back to CPU).
        confidence_threshold: Minimum confidence to include a text line (0.0-1.0).
    """

    _SUPPORTED_EXTENSIONS: ClassVar[list[str]] = [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"]

    def __init__(
        self,
        lang: str = "ch",
        use_gpu: bool = False,
        confidence_threshold: float = 0.5,
    ):
        self._lang = _REC_LANG_ALIASES.get(lang, lang)
        self._use_gpu = use_gpu
        self._confidence_threshold = confidence_threshold
        self._engine: _OcrEngine | None = None

    def _get_engine(self) -> _OcrEngine:
        """Lazy-initialize the RapidOCR engine."""
        if self._engine is not None:
            return self._engine

        try:
            from rapidocr import RapidOCR  # type: ignore[import-not-found]  # optional pdf-ocr extra
        except ImportError as e:
            raise ImportError("rapidocr is required for OCRParser. Install with: uv add rapidocr onnxruntime") from e

        # Engine construction is the only place the language is applied; RapidOCR reads
        # its parameters once, so a later change would not take effect.
        self._engine = cast(
            "_OcrEngine",
            RapidOCR(
                params={
                    "Det.lang_type": _DET_LANG_FOR_SCRIPT.get(self._lang, "ch"),
                    "Rec.lang_type": self._lang,
                    # ONNX Runtime offers CUDA when asked; CPU stays the safe default.
                    "EngineConfig.onnxruntime.use_cuda": self._use_gpu,
                    "Global.log_level": "warning",
                }
            ),
        )
        logger.info("RapidOCR engine initialized: lang=%s, gpu=%s", self._lang, self._use_gpu)
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
            raw_result = engine(file_path)
        except Exception as e:
            logger.warning("RapidOCR failed for %s: %s", file_path, e)
            return OCRResult(text="", lines=[], avg_confidence=0.0, engine="rapidocr")

        return self._process_result(raw_result)

    def _process_result(self, raw_result: object) -> OCRResult:
        """Turn a RapidOCR result into a structured ``OCRResult``.

        RapidOCR returns parallel ``txts``/``scores``/``boxes`` tuples; a falsy result
        (no text found) is a normal outcome and yields empty text, not an error.
        """
        texts = tuple(getattr(raw_result, "txts", None) or ())
        scores = tuple(getattr(raw_result, "scores", None) or ())
        boxes = getattr(raw_result, "boxes", None)

        lines: list[OCRLine] = []
        for index, text in enumerate(texts):
            if not text or not str(text).strip():
                continue
            confidence = float(scores[index]) if index < len(scores) else 0.0
            if confidence < self._confidence_threshold:
                continue
            raw_box: object = boxes[index] if boxes is not None and index < len(boxes) else None
            # RapidOCR exposes numpy arrays; hand back plain lists for a stable contract.
            tolist = getattr(raw_box, "tolist", None)
            bbox = tolist() if callable(tolist) else raw_box
            lines.append(OCRLine(text=str(text), confidence=confidence, bbox=cast("list[list[int]] | None", bbox)))

        avg_confidence = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
        return OCRResult(
            text="\n".join(line.text for line in lines),
            lines=lines,
            avg_confidence=avg_confidence,
            language=self._lang,
            engine="rapidocr",
        )

    @property
    def supported_extensions(self) -> list[str]:
        return list(self._SUPPORTED_EXTENSIONS)
