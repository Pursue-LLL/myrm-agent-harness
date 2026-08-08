"""OCR tier must read sandbox bytes via executor, not host filesystem."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.llms.vision.ocr_tier import OcrTierEngine
from myrm_agent_harness.toolkits.llms.vision.types import VisionBackendKind


class _MemExecutor:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    async def read_file_bytes(self, path: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]


def _tiny_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


@pytest.mark.asyncio
async def test_ocr_tier_reads_bytes_via_executor() -> None:
    executor = _MemExecutor({"/sandbox/a.png": _tiny_png()})
    engine = OcrTierEngine()
    engine._paddle = MagicMock()
    engine._paddle.parse_bytes = AsyncMock(return_value="line-one")

    result = await engine.describe_local_image("/sandbox/a.png", executor)

    engine._paddle.parse_bytes.assert_awaited_once()
    assert result.backend_kind == VisionBackendKind.OCR
    assert result.text == "line-one"


@pytest.mark.asyncio
async def test_ocr_tier_empty_text_is_degraded() -> None:
    executor = _MemExecutor({"/sandbox/a.png": _tiny_png()})
    engine = OcrTierEngine()
    engine._paddle = MagicMock()
    engine._paddle.parse_bytes = AsyncMock(return_value="   ")

    result = await engine.describe_local_image("/sandbox/a.png", executor)

    assert "[OCR found no readable text]" in result.text
    assert result.degraded_from == VisionBackendKind.VLM
