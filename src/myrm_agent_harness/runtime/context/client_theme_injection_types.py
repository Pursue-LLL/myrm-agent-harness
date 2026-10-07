"""Types and schemas for client theme introspection, wallpaper synthesis and hot-reload injection.

[INPUT]
User natural language prompts or style specifications for UI themes.

[OUTPUT]
Type-safe schemas for client UI surface introspection, synthesized palettes,
art layer configurations, theme injection payloads, and rollback records.

[POS]
Defines the SSOT contract for Agent self-reflective client theme mutation,
strictly aligned with frontend preinit.ts and server ThemeProfileRecipeModel.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

ThemeLayoutId = Literal["full-bleed", "nav-rail-focus", "chat-hero", "work-dense"]
ThemeMediaKind = Literal["none", "image", "video"]
ThemeFontId = Literal["inter", "system", "atkinson"]
ClientPlatformKind = Literal["web", "desktop_tauri", "headless"]


class ThemeMutationStatus(StrEnum):
    """Lifecycle status of a theme mutation operation."""
    SUCCESS = "success"
    ROLLED_BACK = "rolled_back"
    VALIDATION_FAILED = "validation_failed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SynthesizedThemePalette:
    """OKLCh/Hex color palette tokens for both light and dark modes."""
    primary_light: str
    primary_dark: str
    primary_hover_light: str
    primary_hover_dark: str
    primary_dark_light: str
    primary_dark_dark: str
    accent_warm_light: str | None = None
    accent_warm_dark: str | None = None
    dual_accent: bool = False


@dataclass(frozen=True)
class ThemePosterArtConfig:
    """Wallpaper and wash layer configuration with contrast protection."""
    focus_x: float = 0.5
    focus_y: float = 0.5
    wash: float = 0.45
    media_kind: ThemeMediaKind = "image"
    asset_ref: str | None = None
    poster_asset_ref: str | None = None


@dataclass(frozen=True)
class ClientThemeSurfaceCapabilities:
    """Introspection report of client UI capabilities and injection constraints."""
    platform: ClientPlatformKind
    allowed_css_variables: tuple[str, ...]
    supported_layouts: tuple[ThemeLayoutId, ...]
    supported_fonts: tuple[ThemeFontId, ...]
    current_profile_id: str
    current_color_scheme: Literal["light", "dark"]
    supports_wallpaper: bool = True
    supports_hot_reload: bool = True


@dataclass(frozen=True)
class ThemePreinitSnapshotPayload:
    """Normalized snapshot payload directly consumable by frontend preinit.ts."""
    profile_id: str
    layout_id: ThemeLayoutId
    scene_id: Literal["immersive", "functional"]
    art_on: bool
    dual_accent: bool
    is_dark: bool
    primary: str
    primary_foreground: str
    primary_hover: str
    accent_warm: str | None = None
    art_poster_url: str | None = None
    art_wash: float | None = None


@dataclass(frozen=True)
class ThemeRecipeDescriptor:
    """Full theme profile recipe descriptor compatible with ThemeProfileRecipeModel."""
    id: str
    name: str
    layout_id: ThemeLayoutId
    font_id: ThemeFontId
    palette: SynthesizedThemePalette
    art: ThemePosterArtConfig
    builtin: bool = False
    description: str | None = None
    tagline: str | None = None
    author: str | None = "Agent Autonomous Designer"


@dataclass(frozen=True)
class ThemeInjectionRecord:
    """Audit and state transition record of an applied theme patch."""
    injection_id: str
    recipe: ThemeRecipeDescriptor
    preinit_snapshot: ThemePreinitSnapshotPayload
    css_variables: dict[str, str]
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    status: ThemeMutationStatus = ThemeMutationStatus.SUCCESS
    rollback_token: str | None = None
