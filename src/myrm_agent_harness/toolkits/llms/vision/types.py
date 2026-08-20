"""Vision toolkit shared types.

[INPUT]
None (foundational types module)

[OUTPUT]
VisionBackendKind, VisionResult, VisionCacheKey

[POS]
Vision toolkit SSOT types. Shared enums and result carriers for fallback and video analysis engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VisionBackendKind(StrEnum):
    VLM = "vlm"
    OCR = "ocr"
    FRAME = "frame"
    NATIVE_VIDEO = "native_video"


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
