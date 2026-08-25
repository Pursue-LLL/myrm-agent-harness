"""Tests for CumulativeMultiTurnImagePayloadBudgetGovernor (MediaBudgetGovernorProcessor)."""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from PIL import Image

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.media_budget_governor import (
    CumulativeImageBudgetGovernor,
    MediaBudgetGovernorProcessor,
    _downsample_base64_image,
)


def _make_dummy_base64_image(width: int = 800, height: int = 600, color: tuple[int, int, int] = (100, 150, 200)) -> str:
    """Generate a test base64 WebP/JPEG data URL."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    raw = buf.getvalue()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _make_human_image_message(data_url: str, text: str = "check this") -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )


def _make_tool_image_message(data_url: str, tool_call_id: str = "call_1") -> ToolMessage:
    return ToolMessage(
        content=[
            {"type": "text", "text": "screenshot output"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
        tool_call_id=tool_call_id,
    )


class TestCumulativeImageBudgetGovernor:
    """Unit tests for the budget calculation and progressive eviction algorithm."""

    def test_downsample_base64_image_reduces_size(self) -> None:
        large_url = _make_dummy_base64_image(width=1200, height=1200)
        downsampled = _downsample_base64_image(large_url, max_dim=256, quality=0.5)
        assert downsampled is not None
        assert downsampled.startswith("data:image/webp;base64,")
        assert len(downsampled) < len(large_url)

    def test_downsample_invalid_returns_none(self) -> None:
        assert _downsample_base64_image("http://example.com/not_base64.png") is None
        assert _downsample_base64_image("data:image/png;base64,INVALID_CORRUPT") is None

    @pytest.mark.asyncio
    async def test_under_budget_fast_path(self) -> None:
        """When total payload is below max_cumulative_bytes, messages remain untouched."""
        gov = CumulativeImageBudgetGovernor(max_cumulative_bytes=5 * 1024 * 1024)
        img1 = _make_dummy_base64_image(width=400, height=300)
        img2 = _make_dummy_base64_image(width=400, height=300)

        msgs: list[BaseMessage] = [
            _make_human_image_message(img1, "turn 1"),
            AIMessage(content="response 1"),
            _make_human_image_message(img2, "turn 2"),
        ]

        downsampled, textified = await gov.enforce_budget(msgs)
        assert downsampled == 0
        assert textified == 0
        assert msgs[0].content[1]["image_url"]["url"] == img1  # type: ignore[index]
        assert msgs[2].content[1]["image_url"]["url"] == img2  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_over_budget_downsamples_oldest_non_focus(self) -> None:
        """When total payload exceeds budget, older non-focus images are downsampled to Tier 2."""
        img_large = _make_dummy_base64_image(width=1000, height=1000)
        img_focus = _make_dummy_base64_image(width=1000, height=1000)
        single_img_size = len(img_large)

        # Set budget lower than 2 large images (~44KB) but higher than 1 large + 1 small (~23KB)
        small_budget = int(single_img_size * 1.5)
        gov = CumulativeImageBudgetGovernor(
            max_cumulative_bytes=small_budget,
            focus_window_turns=1,  # Only last turn is protected
        )

        msgs: list[BaseMessage] = [
            _make_human_image_message(img_large, "turn 1 (old)"),
            AIMessage(content="response 1"),
            _make_human_image_message(img_focus, "turn 2 (focus)"),
        ]

        downsampled, textified = await gov.enforce_budget(msgs)
        assert downsampled >= 1
        # Old image was downsampled to WebP
        assert msgs[0].content[1]["image_url"]["url"].startswith("data:image/webp;base64,")  # type: ignore[index]
        # Focus image remained original JPEG
        assert msgs[2].content[1]["image_url"]["url"] == img_focus  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_extreme_over_budget_textifies_historical_images(self) -> None:
        """When payload is still over budget after downsampling, older images become text summaries."""
        img1 = _make_dummy_base64_image(width=800, height=800)
        img2 = _make_dummy_base64_image(width=800, height=800)
        img_focus = _make_dummy_base64_image(width=800, height=800)

        # Tiny budget force-triggering Tier 3 textification for old turns
        tiny_budget = 1000  # 1KB
        gov = CumulativeImageBudgetGovernor(
            max_cumulative_bytes=tiny_budget,
            focus_window_turns=1,
        )

        msgs: list[BaseMessage] = [
            _make_human_image_message(img1, "turn 1"),
            _make_tool_image_message(img2, "call_1"),
            _make_human_image_message(img_focus, "turn 3 (focus)"),
        ]

        downsampled, textified = await gov.enforce_budget(msgs)
        assert textified >= 1

        # Turn 1 should be converted to text placeholder
        assert msgs[0].content[1]["type"] == "text"  # type: ignore[index]
        assert "[Historical Image omitted" in msgs[0].content[1]["text"]  # type: ignore[index]


class TestMediaBudgetGovernorProcessor:
    """Unit tests for pipeline processor execution and token savings."""

    @pytest.mark.asyncio
    async def test_processor_pipeline_integration(self) -> None:
        proc = MediaBudgetGovernorProcessor(
            max_cumulative_bytes=1000,
            focus_window_turns=1,
        )

        img1 = _make_dummy_base64_image(width=600, height=600)
        img2 = _make_dummy_base64_image(width=600, height=600)

        ctx = ProcessorContext(
            messages=[
                _make_human_image_message(img1, "turn 1"),
                _make_human_image_message(img2, "turn 2"),
            ],
            user_query="test query",
        )

        assert await proc.should_process(ctx) is True
        result_ctx = await proc.process(ctx)

        assert result_ctx.tokens_saved > 0
        assert proc.name == "media_budget_governor"
