"""OCR tier failover for vision pipeline.

[INPUT]
myrm_agent_harness.toolkits.file_parsers.ocr::OCRParser (POS: OCR file parser. Extracts text from images using PaddleOCR with lazy import, graceful degradation when the dependency is not installed, and 2.x/3.x engine compatibility (PaddleX unified inference API in 3.x).)
myrm_agent_harness.toolkits.llms.vision.fallback_engine::FileExecutor (POS: Sandbox byte reader protocol)

[OUTPUT]
OcrTierEngine.describe_local_image: last-resort OCR VisionResult from sandbox bytes

[POS]
Vision pipeline末级 OCR tier. Invoked when VLM chain is exhausted; reads images via sandbox executor only.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from myrm_agent_harness.toolkits.file_parsers.ocr import OCRParser
from myrm_agent_harness.toolkits.llms.vision.fallback_engine import FileExecutor
from myrm_agent_harness.toolkits.llms.vision.types import VisionBackendKind, VisionResult

logger = logging.getLogger(__name__)


class OcrTierEngine:
    """Last-resort OCR when VLM chain is exhausted."""

    def __init__(self) -> None:
        self._paddle = OCRParser()

    async def describe_local_image(self, path: str, executor: FileExecutor) -> VisionResult:
        suffix = PurePosixPath(path).suffix.lower() or ".png"
        try:
            raw = await executor.read_file_bytes(path)
            text = await self._paddle.parse_bytes(raw, suffix=suffix)
        except Exception as exc:
            logger.warning("OCR tier failed for %s: %s", path, exc)
            text = ""
        if not text.strip():
            return VisionResult(
                text="[OCR found no readable text]",
                backend_kind=VisionBackendKind.OCR,
                model_id="paddleocr",
                degraded_from=VisionBackendKind.VLM,
            )
        return VisionResult(
            text=text,
            backend_kind=VisionBackendKind.OCR,
            model_id="paddleocr",
            degraded_from=VisionBackendKind.VLM,
        )
