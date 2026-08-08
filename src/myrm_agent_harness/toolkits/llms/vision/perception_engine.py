"""Semantic vision perception (together, ground, region, OCR).

[INPUT]
myrm_agent_harness.toolkits.llms.vision.fallback_engine::VisionFallbackEngine (POS: 视觉能力降级服务)
myrm_agent_harness.toolkits.llms.vision.ocr_tier::OcrTierEngine (POS: Vision pipeline末级 OCR tier)
myrm_agent_harness.toolkits.llms.vision.cache::get_vision_cache_store (POS: In-memory vision result cache)

[OUTPUT]
VisionPerceptionEngine.perceive: together / ground / region / ocr semantic analysis

[POS]
Semantic vision perception engine. Orchestrates VLM calls, cache, and OCR failover for agent tools.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
from pathlib import PurePosixPath

from PIL import Image

from myrm_agent_harness.toolkits.llms.vision.cache import build_cache_key, get_vision_cache_store
from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
    FileExecutor,
    VisionDescriptionError,
    VisionFallbackEngine,
)
from myrm_agent_harness.toolkits.llms.vision.ocr_tier import OcrTierEngine
from myrm_agent_harness.toolkits.llms.vision.types import (
    BBox,
    GroundScope,
    PerceptionMode,
    VisionBackendKind,
    VisionResult,
)

logger = logging.getLogger(__name__)

_MAX_TOGETHER_IMAGES = 4
_BBOX_PATTERN = re.compile(
    r"\{?\s*\"?x1\"?\s*[:=]\s*(\d+)\s*,\s*\"?y1\"?\s*[:=]\s*(\d+)\s*,\s*\"?x2\"?\s*[:=]\s*(\d+)\s*,\s*\"?y2\"?\s*[:=]\s*(\d+)\s*\}?",
    re.IGNORECASE,
)


class VisionPerceptionEngine:
    """Agent-facing semantic vision operations built on VisionFallbackEngine."""

    def __init__(
        self,
        fallback_engine: VisionFallbackEngine,
        *,
        ocr_engine: OcrTierEngine | None = None,
    ) -> None:
        self._engine = fallback_engine
        self._ocr = ocr_engine or OcrTierEngine()
        self._cache = get_vision_cache_store()

    async def perceive(
        self,
        mode: PerceptionMode,
        paths: list[str],
        executor: FileExecutor,
        *,
        task: str | None = None,
        region: str | None = None,
        ground_scope: GroundScope = GroundScope.ONE,
        target: str | None = None,
    ) -> VisionResult:
        if mode == PerceptionMode.TOGETHER:
            return await self._together(paths, executor, task=task)
        if mode == PerceptionMode.GROUND:
            return await self._ground(paths[0], executor, target=target or task or "", scope=ground_scope)
        if mode == PerceptionMode.REGION:
            if not region:
                raise ValueError("region mode requires region=X1,Y1,X2,Y2")
            return await self._region(paths[0], executor, region=region, task=task)
        if mode == PerceptionMode.OCR:
            return await self._ocr_path(paths[0], executor, task=task)
        raise ValueError(f"Unsupported perception mode: {mode}")

    async def _together(
        self,
        paths: list[str],
        executor: FileExecutor,
        *,
        task: str | None,
    ) -> VisionResult:
        if not paths:
            raise ValueError("together requires at least one image path")
        if len(paths) > _MAX_TOGETHER_IMAGES:
            raise ValueError(f"together supports at most {_MAX_TOGETHER_IMAGES} images")
        content_hash = _hash_paths(paths)
        cache_key = build_cache_key(content_hash=content_hash, mode="together", task=task)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        images: list[tuple[str, str]] = []
        for path in paths:
            b64, mime = await self._load_image_b64(path, executor)
            images.append((b64, mime))

        prompt = self._engine.build_together_prompt(task, len(images))
        try:
            text = await self._engine.describe_images_together(images, prompt)
            result = VisionResult(
                text=text,
                backend_kind=VisionBackendKind.VLM,
                model_id=self._engine.last_success_model,
            )
        except VisionDescriptionError:
            if len(paths) == 1:
                result = await self._ocr.describe_local_image(paths[0], executor)
            else:
                raise
        self._cache.set(cache_key, result)
        return result

    async def _ground(
        self,
        path: str,
        executor: FileExecutor,
        *,
        target: str,
        scope: GroundScope,
    ) -> VisionResult:
        if not target.strip():
            raise ValueError("ground requires a target description")
        content_hash = _hash_paths([path])
        cache_key = build_cache_key(
            content_hash=content_hash,
            mode=f"ground:{scope.value}",
            task=target,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        b64, mime = await self._load_image_b64(path, executor)
        if scope == GroundScope.ALL:
            prompt = (
                f"{self._engine.build_vision_prompt(hint=target, source='user')}\n\n"
                "Locate every instance of the requested kind. "
                "Return JSON array of objects with x1,y1,x2,y2 pixel coordinates."
            )
        else:
            prompt = (
                f"{self._engine.build_vision_prompt(hint=target, source='user')}\n\n"
                "Locate the single best matching target. "
                "Return one JSON object with x1,y1,x2,y2 pixel coordinates only."
            )
        text = await self._engine.describe_image_b64(b64, mime, prompt=prompt)
        result = VisionResult(
            text=text,
            backend_kind=VisionBackendKind.VLM,
            model_id=self._engine.last_success_model,
        )
        self._cache.set(cache_key, result)
        return result

    async def _region(
        self,
        path: str,
        executor: FileExecutor,
        *,
        region: str,
        task: str | None,
    ) -> VisionResult:
        bbox = _parse_region(region)
        content_hash = _hash_paths([path, region])
        cache_key = build_cache_key(
            content_hash=content_hash,
            mode="region",
            task=task,
            region=region,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        b64, mime = await self._load_image_b64(path, executor, crop=bbox)
        prompt = self._engine.build_vision_prompt(hint=task, source="user")
        text = await self._engine.describe_image_b64(b64, mime, prompt=prompt)
        result = VisionResult(
            text=text,
            backend_kind=VisionBackendKind.VLM,
            model_id=self._engine.last_success_model,
        )
        self._cache.set(cache_key, result)
        return result

    async def _ocr_path(
        self,
        path: str,
        executor: FileExecutor,
        *,
        task: str | None,
    ) -> VisionResult:
        content_hash = _hash_paths([path])
        cache_key = build_cache_key(content_hash=content_hash, mode="ocr", task=task)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            b64, mime = await self._load_image_b64(path, executor)
            prompt = (
                "Transcribe every piece of visible text verbatim, line by line. "
                "Do not summarize or translate."
            )
            if task:
                prompt = f"{self._engine.build_vision_prompt(hint=task, source='user')}\n\n{prompt}"
            text = await self._engine.describe_image_b64(b64, mime, prompt=prompt)
            result = VisionResult(
                text=text,
                backend_kind=VisionBackendKind.VLM,
                model_id=self._engine.last_success_model,
            )
        except VisionDescriptionError:
            result = await self._ocr.describe_local_image(path, executor)
        self._cache.set(cache_key, result)
        return result

    async def _load_image_b64(
        self,
        path: str,
        executor: FileExecutor,
        *,
        crop: BBox | None = None,
    ) -> tuple[str, str]:
        from myrm_agent_harness.utils.mime_types import IMAGE_MIME_TYPES as MIME_TYPES

        raw = await executor.read_file_bytes(path)
        suffix = PurePosixPath(path).suffix.lower()
        mime = MIME_TYPES.get(suffix, "image/png")
        if crop is not None:
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
                box = crop.clamp(width, height)
                if not box.is_valid():
                    raise ValueError("Invalid crop region for image")
                cropped = image.crop((box.x1, box.y1, box.x2, box.y2))
                buffer = io.BytesIO()
                cropped.save(buffer, format="PNG")
                raw = buffer.getvalue()
                mime = "image/png"
        return base64.standard_b64encode(raw).decode("ascii"), mime


def parse_bbox_from_text(text: str) -> BBox | None:
    match = _BBOX_PATTERN.search(text)
    if not match:
        return None
    return BBox(
        x1=int(match.group(1)),
        y1=int(match.group(2)),
        x2=int(match.group(3)),
        y2=int(match.group(4)),
    )


def _parse_region(region: str) -> BBox:
    parts = [int(v.strip()) for v in region.split(",")]
    if len(parts) != 4:
        raise ValueError("region must be X1,Y1,X2,Y2")
    return BBox(x1=parts[0], y1=parts[1], x2=parts[2], y2=parts[3])


def _hash_paths(paths: list[str]) -> str:
    joined = "|".join(sorted(paths))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
