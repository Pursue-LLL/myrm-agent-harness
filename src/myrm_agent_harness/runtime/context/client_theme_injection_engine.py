"""Agent self-reflective client theme introspection and hot-reload injection engine.

[INPUT]
Client environment metadata, user styling prompts, and theme rollback tokens.

[OUTPUT]
Introspected capabilities, synthesized ThemeRecipeDescriptors, active preinit snapshots,
and atomic hot-reload injection records.

[POS]
Core runtime engine enabling Agent self-directed UI customization and wallpaper injection,
benchmarked against Alibaba Qoder agentic UI customization paradigms.
"""

import threading
import uuid
from typing import Literal

from myrm_agent_harness.runtime.context.client_theme_injection_types import (
    ClientPlatformKind,
    ClientThemeSurfaceCapabilities,
    SynthesizedThemePalette,
    ThemeFontId,
    ThemeInjectionRecord,
    ThemeLayoutId,
    ThemeMutationStatus,
    ThemePosterArtConfig,
    ThemePreinitSnapshotPayload,
    ThemeRecipeDescriptor,
)
from myrm_agent_harness.runtime.context.theme_palette_synthesizer import (
    ThemePaletteSynthesizer,
)

_DEFAULT_ALLOWED_CSS_VARS: tuple[str, ...] = (
    "--primary",
    "--primary-foreground",
    "--primary-hover",
    "--accent-warm",
    "--art-wash-opacity",
)

_SUPPORTED_LAYOUTS: tuple[ThemeLayoutId, ...] = (
    "full-bleed",
    "nav-rail-focus",
    "chat-hero",
    "work-dense",
)

_SUPPORTED_FONTS: tuple[ThemeFontId, ...] = ("inter", "system", "atkinson")


class AgentSelfReflectiveThemeEngine:
    """Engine allowing the Agent to introspect and autonomously restyle client hosts."""

    def __init__(self, platform: ClientPlatformKind = "web") -> None:
        self._platform: ClientPlatformKind = platform
        self._lock = threading.RLock()
        self._history: list[ThemeInjectionRecord] = []
        self._rollback_map: dict[str, ThemeInjectionRecord] = {}

        # Default fallback baseline theme
        default_palette = SynthesizedThemePalette(
            primary_light="#18181b",
            primary_dark="#fafafa",
            primary_hover_light="#27272a",
            primary_hover_dark="#e4e4e7",
            primary_dark_light="#09090b",
            primary_dark_dark="#71717a",
            accent_warm_light=None,
            accent_warm_dark=None,
            dual_accent=False,
        )
        self._current_recipe = ThemeRecipeDescriptor(
            id="official-default",
            name="Official Default Theme",
            layout_id="nav-rail-focus",
            font_id="inter",
            palette=default_palette,
            art=ThemePosterArtConfig(media_kind="none", wash=0.45),
            builtin=True,
        )
        self._current_snapshot = self._build_snapshot_from_recipe(
            recipe=self._current_recipe,
            color_scheme="dark",
        )

    def inspect_client_theme_surface(self) -> ClientThemeSurfaceCapabilities:
        """Introspect client UI surface boundaries and allowed injection points."""
        with self._lock:
            return ClientThemeSurfaceCapabilities(
                platform=self._platform,
                allowed_css_variables=_DEFAULT_ALLOWED_CSS_VARS,
                supported_layouts=_SUPPORTED_LAYOUTS,
                supported_fonts=_SUPPORTED_FONTS,
                current_profile_id=self._current_recipe.id,
                current_color_scheme=(
                    "dark" if self._current_snapshot.is_dark else "light"
                ),
                supports_wallpaper=True,
                supports_hot_reload=True,
            )

    def synthesize_theme_recipe(
        self,
        style_prompt: str,
        name: str | None = None,
        layout_id: ThemeLayoutId = "nav-rail-focus",
        font_id: ThemeFontId = "inter",
        poster_asset_ref: str | None = None,
        wash: float = 0.45,
    ) -> ThemeRecipeDescriptor:
        """Synthesize a complete theme recipe from user intent and art assets."""
        palette = ThemePaletteSynthesizer.synthesize_from_keywords(style_prompt)
        clamped_wash = max(0.2, min(0.8, wash))

        art = ThemePosterArtConfig(
            focus_x=0.5,
            focus_y=0.5,
            wash=clamped_wash,
            media_kind="image" if poster_asset_ref else "none",
            asset_ref=poster_asset_ref,
            poster_asset_ref=poster_asset_ref,
        )

        theme_slug = f"theme-{uuid.uuid4().hex[:8]}"
        display_name = name or f"Autonomous {style_prompt.capitalize()} Theme"

        return ThemeRecipeDescriptor(
            id=theme_slug,
            name=display_name,
            layout_id=layout_id,
            font_id=font_id,
            palette=palette,
            art=art,
            builtin=False,
            description=f"Generated via AgentSelfReflectiveThemeEngine from '{style_prompt}'",
            tagline="Custom theme tailored to user preference",
        )

    def apply_theme_injection(
        self,
        recipe: ThemeRecipeDescriptor,
        color_scheme: Literal["light", "dark"] = "dark",
    ) -> ThemeInjectionRecord:
        """Apply new theme recipe, generate frontend preinit payload, and register rollback."""
        with self._lock:
            # 1. Compile CSS variables
            css_vars = ThemePaletteSynthesizer.build_css_variables(
                palette=recipe.palette,
                color_scheme=color_scheme,
                art=recipe.art,
            )

            # 2. Build preinit snapshot for frontend hydration
            snapshot = self._build_snapshot_from_recipe(
                recipe=recipe,
                color_scheme=color_scheme,
            )

            # 3. Formulate rollback token and preserve previous snapshot
            rollback_token = f"rb-{uuid.uuid4().hex[:12]}"
            injection_id = f"inj-{uuid.uuid4().hex[:8]}"

            # Keep reference of current snapshot under rollback token
            previous_record = ThemeInjectionRecord(
                injection_id=f"prev-{self._current_recipe.id}",
                recipe=self._current_recipe,
                preinit_snapshot=self._current_snapshot,
                css_variables=ThemePaletteSynthesizer.build_css_variables(
                    palette=self._current_recipe.palette,
                    color_scheme=(
                        "dark" if self._current_snapshot.is_dark else "light"
                    ),
                    art=self._current_recipe.art,
                ),
                status=ThemeMutationStatus.SUCCESS,
            )
            self._rollback_map[rollback_token] = previous_record

            # 4. Commit active state
            self._current_recipe = recipe
            self._current_snapshot = snapshot

            record = ThemeInjectionRecord(
                injection_id=injection_id,
                recipe=recipe,
                preinit_snapshot=snapshot,
                css_variables=css_vars,
                status=ThemeMutationStatus.SUCCESS,
                rollback_token=rollback_token,
            )
            self._history.append(record)
            return record

    def rollback_theme_injection(
        self, rollback_token: str
    ) -> ThemeInjectionRecord | None:
        """Roll back an injected theme to its prior state via rollback token."""
        with self._lock:
            prior_record = self._rollback_map.get(rollback_token)
            if not prior_record:
                return None

            self._current_recipe = prior_record.recipe
            self._current_snapshot = prior_record.preinit_snapshot

            rollback_applied_record = ThemeInjectionRecord(
                injection_id=f"rb-applied-{uuid.uuid4().hex[:8]}",
                recipe=prior_record.recipe,
                preinit_snapshot=prior_record.preinit_snapshot,
                css_variables=prior_record.css_variables,
                status=ThemeMutationStatus.ROLLED_BACK,
            )
            self._history.append(rollback_applied_record)
            del self._rollback_map[rollback_token]
            return rollback_applied_record

    def get_active_theme_snapshot(self) -> ThemePreinitSnapshotPayload:
        """Fetch current active preinit snapshot."""
        with self._lock:
            return self._current_snapshot

    def get_injection_history(self) -> list[ThemeInjectionRecord]:
        """Fetch read-only audit log of theme injections."""
        with self._lock:
            return list(self._history)

    def _build_snapshot_from_recipe(
        self,
        recipe: ThemeRecipeDescriptor,
        color_scheme: Literal["light", "dark"],
    ) -> ThemePreinitSnapshotPayload:
        """Construct frontend-compatible ThemePreinitSnapshotPayload."""
        is_dark = color_scheme == "dark"
        primary = (
            recipe.palette.primary_dark if is_dark else recipe.palette.primary_light
        )
        primary_hover = (
            recipe.palette.primary_hover_dark
            if is_dark
            else recipe.palette.primary_hover_light
        )
        accent_warm = (
            recipe.palette.accent_warm_dark
            if is_dark
            else recipe.palette.accent_warm_light
        )
        primary_fg = ThemePaletteSynthesizer.derive_foreground_color(primary)

        return ThemePreinitSnapshotPayload(
            profile_id=recipe.id,
            layout_id=recipe.layout_id,
            scene_id="immersive" if recipe.art.media_kind != "none" else "functional",
            art_on=recipe.art.media_kind != "none",
            dual_accent=recipe.palette.dual_accent,
            is_dark=is_dark,
            primary=primary,
            primary_foreground=primary_fg,
            primary_hover=primary_hover,
            accent_warm=accent_warm,
            art_poster_url=recipe.art.poster_asset_ref,
            art_wash=recipe.art.wash,
        )
