"""Local deterministic vision geometry helpers.

[INPUT]
myrm_agent_harness.toolkits.llms.vision.fallback_engine::FileExecutor (POS: Sandbox byte reader protocol)
PIL (image diff and crop)

[OUTPUT]
VisionGeometryEngine.run: pixel_diff and crop geometry analysis

[POS]
Deterministic pixel geometry engine without VLM calls. Used by vision_geometry_tool.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import PurePosixPath

from PIL import Image, ImageChops

from myrm_agent_harness.toolkits.llms.vision.fallback_engine import FileExecutor
from myrm_agent_harness.toolkits.llms.vision.types import BBox, GeometryMode, VisionBackendKind, VisionResult

logger = logging.getLogger(__name__)


class VisionGeometryEngine:
    """Pixel-level geometry operations without VLM calls."""

    async def run(
        self,
        mode: GeometryMode,
        paths: list[str],
        executor: FileExecutor,
        *,
        region: str | None = None,
        threshold: int = 30,
    ) -> VisionResult:
        if mode == GeometryMode.PIXEL_DIFF:
            if len(paths) != 2:
                raise ValueError("pixel_diff requires exactly two image paths")
            return await self._pixel_diff(paths[0], paths[1], executor, threshold=threshold)
        if mode == GeometryMode.CROP:
            if len(paths) != 1 or not region:
                raise ValueError("crop requires one image path and a region")
            return await self._crop(paths[0], region, executor)
        raise ValueError(f"Unsupported geometry mode: {mode}")

    async def _read_image_bytes(self, path: str, executor: FileExecutor) -> bytes:
        return await executor.read_file_bytes(path)

    async def _pixel_diff(
        self,
        path_a: str,
        path_b: str,
        executor: FileExecutor,
        *,
        threshold: int,
    ) -> VisionResult:
        raw_a = await self._read_image_bytes(path_a, executor)
        raw_b = await self._read_image_bytes(path_b, executor)
        img_a = Image.open(io.BytesIO(raw_a)).convert("RGB")
        img_b = Image.open(io.BytesIO(raw_b)).convert("RGB")
        if img_a.size != img_b.size:
            img_b = img_b.resize(img_a.size)
        diff = ImageChops.difference(img_a, img_b).convert("L")
        bbox = diff.point(lambda p: 255 if p > threshold else 0).getbbox()
        if bbox is None:
            text = "No pixel differences detected above threshold."
        else:
            x1, y1, x2, y2 = bbox
            text = f"Diff bbox (pixels): {x1},{y1},{x2},{y2}"
        return VisionResult(text=text, backend_kind=VisionBackendKind.GEOMETRY, model_id="pixel_diff")

    async def _crop(self, path: str, region: str, executor: FileExecutor) -> VisionResult:
        bbox = _parse_region(region)
        raw = await self._read_image_bytes(path, executor)
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            box = bbox.clamp(width, height)
            if not box.is_valid():
                raise ValueError(f"Invalid crop region after clamping: {region}")
            cropped = image.crop((box.x1, box.y1, box.x2, box.y2))
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
        b64 = base64.standard_b64encode(buffer.getvalue()).decode("ascii")
        stem = PurePosixPath(path).stem
        text = (
            f"Cropped region {box.as_csv()} from {path} ({stem}). "
            f"Inline crop data_url=data:image/png;base64,{b64}"
        )
        return VisionResult(text=text, backend_kind=VisionBackendKind.GEOMETRY, model_id="crop")


def _parse_region(region: str) -> BBox:
    parts = [int(v.strip()) for v in region.split(",")]
    if len(parts) != 4:
        raise ValueError("region must be X1,Y1,X2,Y2")
    return BBox(x1=parts[0], y1=parts[1], x2=parts[2], y2=parts[3])
