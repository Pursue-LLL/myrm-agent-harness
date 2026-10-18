"""OCR tier failover for vision pipeline.

[INPUT]
myrm_agent_harness.toolkits.file_parsers.ocr::OCRParser (POS: OCR file parser. Extracts text from images using RapidOCR with lazy import and an ImportError when the optional pdf-ocr extra is missing.)
myrm_agent_harness.toolkits.llms.vision.fallback_engine::FileExecutor (POS: Sandbox byte reader protocol)

[OUTPUT]
OcrTierEngine.describe_local_image: last-resort OCR VisionResult from sandbox bytes

[POS]
Vision pipeline末级 OCR tier. Invoked when VLM chain is exhausted; reads images via sandbox executor only. A missing OCR extra raises ImportError so the caller can keep its own fallback instead of reporting an unexamined image as empty.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from myrm_agent_harness.toolkits.file_parsers.ocr import OCRParser
from myrm_agent_harness.toolkits.llms.vision.fallback_engine import FileExecutor
from myrm_agent_harness.toolkits.llms.vision.types import VisionBackendKind, VisionResult

logger = logging.getLogger(__name__)

# Emitted when OCR ran successfully but the image held no readable text. Exported so a
# caller can tell "the OCR tier looked and found nothing" apart from "OCR produced text".
NO_READABLE_TEXT = "[OCR found no readable text]"


class OcrTierEngine:
    """Last-resort OCR when VLM chain is exhausted."""

    def __init__(self) -> None:
        self._ocr = OCRParser()

    async def describe_local_image(self, path: str, executor: FileExecutor) -> VisionResult:
        suffix = PurePosixPath(path).suffix.lower() or ".png"
        try:
            raw = await executor.read_file_bytes(path)
            text = await self._ocr.parse_bytes(raw, suffix=suffix)
        except ImportError:
            # The OCR extra is absent. Surface it rather than returning the "no readable
            # text" placeholder, which would claim an image was examined when it was not.
            raise
        except Exception as exc:
            logger.warning("OCR tier failed for %s: %s", path, exc)
            text = ""
        if not text.strip():
            return VisionResult(
                text=NO_READABLE_TEXT,
                backend_kind=VisionBackendKind.OCR,
                model_id="rapidocr",
                degraded_from=VisionBackendKind.VLM,
            )
        return VisionResult(
            text=text,
            backend_kind=VisionBackendKind.OCR,
            model_id="rapidocr",
            degraded_from=VisionBackendKind.VLM,
        )
