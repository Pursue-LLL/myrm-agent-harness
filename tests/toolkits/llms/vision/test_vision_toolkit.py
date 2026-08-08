"""Tests for vision toolkit engines and tools."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.vision.cache import build_cache_key, get_vision_cache_store
from myrm_agent_harness.toolkits.llms.vision.fallback_engine import VisionFallbackEngine
from myrm_agent_harness.toolkits.llms.vision.geometry_engine import VisionGeometryEngine
from myrm_agent_harness.toolkits.llms.vision.perception_engine import VisionPerceptionEngine
from myrm_agent_harness.toolkits.llms.vision.types import GeometryMode, PerceptionMode, VisionBackendKind, VisionResult
from myrm_agent_harness.toolkits.llms.vision.vision_agent_tools import create_vision_agent_tools


class _MemExecutor:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    async def read_file_bytes(self, path: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]


def _tiny_png() -> bytes:
    # 1x1 PNG
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


@pytest.fixture
def fallback_engine() -> VisionFallbackEngine:
    cfg = LLMConfig(model="test-vl", api_key="k", base_url="http://localhost")
    engine = VisionFallbackEngine(cfg)
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "together-answer"
    mock_model.ainvoke = AsyncMock(return_value=mock_response)
    engine._models = [mock_model]
    return engine


@pytest.mark.asyncio
async def test_describe_images_together_single_call(fallback_engine: VisionFallbackEngine) -> None:
    b64 = base64.b64encode(_tiny_png()).decode("ascii")
    result = await fallback_engine.describe_images_together([(b64, "image/png")], "compare")
    assert result == "together-answer"
    assert fallback_engine._models[0].ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_cache_key_isolated_by_task() -> None:
    store = get_vision_cache_store()
    store.clear()
    key_a = build_cache_key(content_hash="abc", mode="ocr", task="amount")
    key_b = build_cache_key(content_hash="abc", mode="ocr", task="date")
    store.set(key_a, VisionResult(text="a", backend_kind=VisionBackendKind.VLM))
    assert store.get(key_b) is None


@pytest.mark.asyncio
async def test_pixel_diff_detects_change() -> None:
    png = _tiny_png()
    img_a = png
    img_b = png + b"diff"
    executor = _MemExecutor({"/a.png": img_a, "/b.png": img_b})
    engine = VisionGeometryEngine()
    result = await engine.run(
        GeometryMode.PIXEL_DIFF,
        ["/a.png", "/b.png"],
        executor,
    )
    assert "Diff bbox" in result.text or "No pixel differences" in result.text


@pytest.mark.asyncio
async def test_create_vision_agent_tools_requires_engine() -> None:
    executor = _MemExecutor({})
    tools = create_vision_agent_tools(executor, vision_fallback_model_cfg=None)
    assert tools == []


@pytest.mark.asyncio
async def test_perception_together_uses_cache(fallback_engine: VisionFallbackEngine) -> None:
    get_vision_cache_store().clear()
    executor = _MemExecutor({"/workspace/a.png": _tiny_png()})
    perception = VisionPerceptionEngine(fallback_engine)
    first = await perception.perceive(
        PerceptionMode.TOGETHER,
        ["/workspace/a.png"],
        executor,
        task="what is this",
    )
    second = await perception.perceive(
        PerceptionMode.TOGETHER,
        ["/workspace/a.png"],
        executor,
        task="what is this",
    )
    assert first.text == second.text
    assert fallback_engine._models[0].ainvoke.await_count == 1
