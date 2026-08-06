"""Wiki ingress request/result types (clip + URL markdown)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


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
    localize_public_assets: bool = True


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
