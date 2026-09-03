"""Wiki ingress request/result types (clip + URL markdown).

[INPUT]
- 无（纯类型定义）

[OUTPUT]
- ClipMode: FULL_PAGE / SELECTION 枚举
- ClipIngressRequest / ClipAssetInput / ClipIngressResult / UrlMarkdownIngressRequest: 请求与结果 dataclass

[POS]
Shared type contracts for the wiki raw-ingress pipeline, decoupling transport
(shapes validated at API boundary) from ingestion logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.types import (
        RawConflictPolicy,
        RawGateCaller,
    )


class ClipMode(StrEnum):
    FULL_PAGE = "full_page"
    SELECTION = "selection"


@dataclass(frozen=True, slots=True)
class ClipAssetInput:
    """Binary asset uploaded by the browser extension (cookie-authenticated fetch)."""

    source_url: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ClipIngressRequest:
    source_url: str
    title: str
    clip_mode: ClipMode
    html: str = ""
    markdown: str = ""
    agent_id: str | None = None
    folder_path: str = ""
    assets: tuple[ClipAssetInput, ...] = ()


@dataclass(frozen=True, slots=True)
class UrlMarkdownIngressRequest:
    url: str
    filename: str = ""
    folder_path: str = ""
    relative_path: str = ""
    localize_public_assets: bool = True
    conflict_policy: RawConflictPolicy | None = None
    supersede_reason: str = ""
    caller: RawGateCaller = "agent"


@dataclass(frozen=True, slots=True)
class IngressAssetStats:
    stored: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class ClipIngressResult:
    relative_path: str
    written: bool
    skipped: bool
    conflict: bool
    security_blocked: bool
    assets_localized: Literal["full", "partial", "remote"] = "remote"
    asset_stats: IngressAssetStats = field(default_factory=IngressAssetStats)
    superseded: bool = False
    security_redacted: bool = False


@dataclass(frozen=True, slots=True)
class MediaTranscriptSegment:
    """Timestamped speech segment transcribed from media."""

    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None


@dataclass(frozen=True, slots=True)
class MediaKeyframe:
    """Key visual slide or scene snapshot extracted from video."""

    timestamp_seconds: float
    image_bytes: bytes
    ocr_text: str = ""
    mime_type: str = "image/jpeg"
    description: str = ""


@dataclass(frozen=True, slots=True)
class MediaIngressRequest:
    """Input request for ingesting video/audio media into wiki."""

    title: str
    media_filename: str
    media_bytes: bytes | None = None
    source_url: str = ""
    duration_seconds: float = 0.0
    segments: tuple[MediaTranscriptSegment, ...] = ()
    keyframes: tuple[MediaKeyframe, ...] = ()
    folder_path: str = "videos"
    agent_id: str | None = None
    caller: RawGateCaller = "agent"
    conflict_policy: RawConflictPolicy | None = None
    supersede_reason: str = ""


@dataclass(frozen=True, slots=True)
class VideoUrlIngressRequest:
    """Request to fetch video transcripts from URL and ingest into wiki."""

    url: str
    folder_path: str = "videos"
    filename: str = ""
    preferred_languages: tuple[str, ...] = ("zh-Hans", "zh-CN", "zh", "en")
    window_duration_seconds: int = 45
    window_max_chars: int = 350
    conflict_policy: RawConflictPolicy | None = None
    supersede_reason: str = ""
    caller: RawGateCaller = "agent"


