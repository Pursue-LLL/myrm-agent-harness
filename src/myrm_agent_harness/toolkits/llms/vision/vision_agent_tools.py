"""LangChain adapter for semantic and geometry vision tools.

[INPUT]
myrm_agent_harness.toolkits.llms.vision.fallback_engine::create_vision_fallback_engine (POS: 视觉能力降级服务)
myrm_agent_harness.toolkits.llms.vision.perception_engine::VisionPerceptionEngine (POS: Semantic vision perception engine)
myrm_agent_harness.toolkits.llms.vision.geometry_engine::VisionGeometryEngine (POS: Deterministic pixel geometry engine)

[OUTPUT]
create_vision_agent_tools: EXTENDED vision_semantic_tool and vision_geometry_tool list

[POS]
LangChain adapter for vision toolkit. Mounted only when vision-toolkit skill is bound.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
    FileExecutor,
    VisionFallbackEngine,
    create_vision_fallback_engine,
)
from myrm_agent_harness.toolkits.llms.vision.geometry_engine import VisionGeometryEngine
from myrm_agent_harness.toolkits.llms.vision.perception_engine import VisionPerceptionEngine
from myrm_agent_harness.toolkits.llms.vision.types import GeometryMode, GroundScope, PerceptionMode

logger = logging.getLogger(__name__)

_MAX_CALLS_PER_TURN = 3


class VisionToolkitTurnGuard:
    """Simple per-turn call budget for vision semantic tool."""

    def __init__(self, limit: int = _MAX_CALLS_PER_TURN) -> None:
        self._limit = limit
        self._count = 0

    def consume(self) -> None:
        self._count += 1
        if self._count > self._limit:
            raise RuntimeError(
                f"vision_semantic_tool limit reached ({self._limit} calls per turn). "
                "Use file_read_tool for additional single-image reads."
            )


def create_vision_agent_tools(
    executor: FileExecutor,
    *,
    vision_fallback_model_cfg: object | None = None,
    vision_fallback_model_cfgs: object | None = None,
    include_geometry: bool = True,
    semantic_call_limit: int = _MAX_CALLS_PER_TURN,
) -> list[object]:
    """Create EXTENDED vision tools bound to sandbox executor and vision configs."""
    engine = create_vision_fallback_engine(
        vision_fallback_model_cfg,
        vision_fallback_model_cfgs,
    )
    if engine is None:
        return []

    perception = VisionPerceptionEngine(engine)
    geometry = VisionGeometryEngine()
    guard = VisionToolkitTurnGuard(limit=semantic_call_limit)

    class SemanticInput(BaseModel):
        mode: Literal["together", "ground", "region", "ocr"] = Field(
            description=(
                "together=multi-image joint analysis; ground=find target bbox; "
                "region=crop+analyze; ocr=verbatim text."
            )
        )
        paths: list[str] = Field(
            description="Sandbox image path(s). Single-image reads can use file_read_tool instead."
        )
        task: str = Field(
            default="",
            description="User question or target description. Required for ground; recommended otherwise.",
        )
        region: str = Field(
            default="",
            description="Pixel region X1,Y1,X2,Y2. Required when mode=region.",
        )
        ground_scope: Literal["one", "all"] = Field(
            default="one",
            description="For mode=ground: one target or all instances of a kind.",
        )

    @tool("vision_semantic_tool", args_schema=SemanticInput)
    async def vision_semantic(
        mode: Literal["together", "ground", "region", "ocr"],
        paths: list[str],
        task: str = "",
        region: str = "",
        ground_scope: Literal["one", "all"] = "one",
    ) -> str:
        """Analyze sandbox images with semantic vision (VLM/OCR failover).

        Prefer file_read_tool for a single undifferentiated image read.
        Use together for before/after comparisons in one call.
        Use ground before desktop_vision_tool coordinate clicks.
        """
        guard.consume()
        scope = GroundScope.ALL if ground_scope == "all" else GroundScope.ONE
        result = await perception.perceive(
            PerceptionMode(mode),
            paths,
            executor,
            task=task or None,
            region=region or None,
            ground_scope=scope,
            target=task or None,
        )
        return result.format_for_agent()

    tools: list[object] = [vision_semantic]

    if include_geometry:

        class GeometryInput(BaseModel):
            mode: Literal["pixel_diff", "crop"] = Field(
                description="pixel_diff=find changed bbox; crop=cut region bytes."
            )
            paths: list[str] = Field(description="One path for crop; two paths for pixel_diff.")
            region: str = Field(default="", description="Required for crop: X1,Y1,X2,Y2.")
            threshold: int = Field(default=30, description="pixel_diff sensitivity (0-255).")

        @tool("vision_geometry_tool", args_schema=GeometryInput)
        async def vision_geometry(
            mode: Literal["pixel_diff", "crop"],
            paths: list[str],
            region: str = "",
            threshold: int = 30,
        ) -> str:
            """Deterministic pixel operations. Use for exact diff boxes before semantic region reads."""
            result = await geometry.run(
                GeometryMode(mode),
                paths,
                executor,
                region=region or None,
                threshold=threshold,
            )
            return result.format_for_agent()

        tools.append(vision_geometry)

    return tools
