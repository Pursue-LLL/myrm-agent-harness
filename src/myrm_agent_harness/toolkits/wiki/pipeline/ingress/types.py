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
