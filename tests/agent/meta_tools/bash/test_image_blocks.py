"""``bash_tool._maybe_build_image_blocks`` tests (P1-3).

Verifies that when a PTC script generates image artifacts and the active LLM
supports vision, the tool returns LangChain ContentBlocks (so the model can
see the chart) instead of just a text dict.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    _maybe_build_image_blocks,
)


class _FakeExecutor:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    async def read_file_bytes(self, path: str) -> bytes:
        return self._files[path]


@pytest.fixture
def png_executor(monkeypatch: pytest.MonkeyPatch) -> _FakeExecutor:
    """Smallest valid 1x1 PNG (avoids needing Pillow at test time)."""
    raw = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    executor = _FakeExecutor({"chart.png": raw})
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.executors.base.require_executor",
        lambda: executor,
    )
    return executor


@pytest.mark.asyncio
async def test_returns_none_when_no_generated_files() -> None:
    result = await _maybe_build_image_blocks(text_content="hi", generated_files=[], context={"supports_vision": True})
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_without_image_artifacts() -> None:
    result = await _maybe_build_image_blocks(
        text_content="hi",
        generated_files=["notes.txt", "log.json"],
        context={"supports_vision": True},
    )
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_model_lacks_vision(png_executor: _FakeExecutor) -> None:
    _ = png_executor
    result = await _maybe_build_image_blocks(
        text_content="hi",
        generated_files=["chart.png"],
        context={"supports_vision": False},
    )
    assert result is None


@pytest.mark.asyncio
async def test_returns_content_blocks_when_image_inlinable(
    png_executor: _FakeExecutor,
) -> None:
    _ = png_executor
    result = await _maybe_build_image_blocks(
        text_content="rendered chart",
        generated_files=["chart.png", "notes.txt"],
        context={"supports_vision": True},
    )

    assert isinstance(result, list)
    # First block must carry the text body so LLMs without vision-only
    # rendering still see the textual context.
    first = result[0]
    payload: Any = first if isinstance(first, dict) else first.__dict__
    assert "rendered chart" in str(payload)
    # At least one image block was appended.
    assert any("image" in str(b).lower() for b in result[1:])


@pytest.mark.asyncio
async def test_caps_inlined_images_to_max_per_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token-budget guardrail: more than ``MAX_IMAGES_PER_RETURN`` images get truncated.

    Without the cap an LLM can crash UI/token budgets by producing a 100-chart
    sweep (e.g. ``plt.savefig`` in a loop). The overflow summary keeps the LLM
    aware of the remaining artifacts so it can ``file_read_tool`` them on demand.
    """
    import base64

    from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
        MAX_IMAGES_PER_RETURN,
    )

    raw = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQ42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    image_count = MAX_IMAGES_PER_RETURN + 3
    images = {f"chart_{i}.png": raw for i in range(image_count)}
    executor = _FakeExecutor(images)
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.executors.base.require_executor",
        lambda: executor,
    )

    result = await _maybe_build_image_blocks(
        text_content="batch run",
        generated_files=list(images.keys()),
        context={"supports_vision": True},
    )

    assert isinstance(result, list)

    def _is_image_block(block: Any) -> bool:
        payload = block if isinstance(block, dict) else block.__dict__
        return isinstance(payload, dict) and payload.get("type") == "image"

    image_blocks = [b for b in result if _is_image_block(b)]
    assert len(image_blocks) <= MAX_IMAGES_PER_RETURN
    # Overflow summary mentions the remaining count for ``file_read_tool`` follow-up
    assert any("additional image" in str(b).lower() for b in result)
