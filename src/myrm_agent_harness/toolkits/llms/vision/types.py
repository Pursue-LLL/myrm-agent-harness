"""Vision toolkit shared types.

[INPUT]
None (foundational types module)

[OUTPUT]
VisionBackendKind, PerceptionMode, GeometryMode, VisionResult, BBox, VisionCacheKey

[POS]
Vision toolkit SSOT types. Shared enums and result carriers for perception and geometry engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VisionBackendKind(StrEnum):
    VLM = "vlm"
    OCR = "ocr"
    FRAME = "frame"
    NATIVE_VIDEO = "native_video"
    GEOMETRY = "geometry"


class PerceptionMode(StrEnum):
    TOGETHER = "together"
    GROUND = "ground"
    REGION = "region"
    OCR = "ocr"


class GeometryMode(StrEnum):
    PIXEL_DIFF = "pixel_diff"
    CROP = "crop"


class GroundScope(StrEnum):
    ONE = "one"
    ALL = "all"


@dataclass(frozen=True)
class BBox:
    x1: int
    y1: int
    x2: int
    y2: int

    def clamp(self, width: int, height: int) -> BBox:
        return BBox(
            x1=max(0, min(self.x1, width)),
            y1=max(0, min(self.y1, height)),
            x2=max(0, min(self.x2, width)),
            y2=max(0, min(self.y2, height)),
        )

    def is_valid(self) -> bool:
        return self.x2 > self.x1 and self.y2 > self.y1

    def as_csv(self) -> str:
        return f"{self.x1},{self.y1},{self.x2},{self.y2}"


@dataclass(frozen=True)
class VisionResult:
    text: str
    backend_kind: VisionBackendKind
    model_id: str | None = None
    degraded_from: VisionBackendKind | None = None

    def format_for_agent(self) -> str:
        header = f"[vision:{self.backend_kind.value}"
        if self.model_id:
            header += f" model={self.model_id}"
        if self.degraded_from is not None:
            header += f" degraded_from={self.degraded_from.value}"
        header += "]\n"
        return header + self.text


@dataclass(frozen=True)
class VisionCacheKey:
    content_hash: str
    mode: str
    task_hash: str
    region: str | None = None

    def digest(self) -> str:
        region_part = self.region or ""
        return f"{self.content_hash}:{self.mode}:{self.task_hash}:{region_part}"
