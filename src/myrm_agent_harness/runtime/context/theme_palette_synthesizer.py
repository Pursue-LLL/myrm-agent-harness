"""Synthesizer for dynamic theme palettes, poster wash calculation, and safe CSS variables.

[INPUT]
Theme intent keywords (e.g. 'cyberpunk', 'ocean-blue', 'forest') or custom hex codes.

[OUTPUT]
Synthesized theme palettes, calibrated wash levels, and sanitized CSS variables.

[POS]
Core palette synthesis engine supporting WCAG contrast safety and XSS protection.
"""

import re
from typing import Literal

from myrm_agent_harness.runtime.context.client_theme_injection_types import (
    SynthesizedThemePalette,
    ThemePosterArtConfig,
)

_HEX_COLOR_REGEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_SAFE_COLOR_TOKEN_REGEX = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|oklch\([0-9.%\s,/]+\)|rgb\([0-9.%\s,/]+\)|hsl\([0-9.%\s,/]+\))$"
)

# Curated palette presets for canonical aesthetic archetypes
_ARCHETYPE_PALETTES: dict[str, SynthesizedThemePalette] = {
    "cyberpunk": SynthesizedThemePalette(
        primary_light="#0284c7",
        primary_dark="#38bdf8",
        primary_hover_light="#0369a1",
        primary_hover_dark="#7dd3fc",
        primary_dark_light="#0c4a6e",
        primary_dark_dark="#0369a1",
        accent_warm_light="#f43f5e",
        accent_warm_dark="#fb7185",
        dual_accent=True,
    ),
    "ocean-blue": SynthesizedThemePalette(
        primary_light="#2563eb",
        primary_dark="#60a5fa",
        primary_hover_light="#1d4ed8",
        primary_hover_dark="#93c5fd",
        primary_dark_light="#1e3a8a",
        primary_dark_dark="#1d4ed8",
        accent_warm_light="#0d9488",
        accent_warm_dark="#2dd4bf",
        dual_accent=True,
    ),
    "emerald-forest": SynthesizedThemePalette(
        primary_light="#059669",
        primary_dark="#34d399",
        primary_hover_light="#047857",
        primary_hover_dark="#6ee7b7",
        primary_dark_light="#064e3b",
        primary_dark_dark="#047857",
        accent_warm_light="#d97706",
        accent_warm_dark="#fbbf24",
        dual_accent=True,
    ),
    "sunset-gold": SynthesizedThemePalette(
        primary_light="#d97706",
        primary_dark="#fbbf24",
        primary_hover_light="#b45309",
        primary_hover_dark="#fde68a",
        primary_dark_light="#78350f",
        primary_dark_dark="#b45309",
        accent_warm_light="#e11d48",
        accent_warm_dark="#f43f5e",
        dual_accent=True,
    ),
    "minimal-monochrome": SynthesizedThemePalette(
        primary_light="#18181b",
        primary_dark="#fafafa",
        primary_hover_light="#27272a",
        primary_hover_dark="#e4e4e7",
        primary_dark_light="#09090b",
        primary_dark_dark="#71717a",
        accent_warm_light=None,
        accent_warm_dark=None,
        dual_accent=False,
    ),
}


class ThemePaletteSynthesizer:
    """Synthesizes high-aesthetic color palettes and safe CSS variable maps."""

    @classmethod
    def sanitize_color(cls, value: str) -> str:
        """Validate and return safe color string or raise ValueError."""
        clean_value = value.strip()
        if not _SAFE_COLOR_TOKEN_REGEX.match(clean_value):
            raise ValueError(f"Insecure or invalid color value: '{value}'")
        return clean_value

    @classmethod
    def synthesize_from_keywords(cls, style_prompt: str) -> SynthesizedThemePalette:
        """Derive an optimal palette based on natural language style prompt."""
        lower_prompt = style_prompt.lower()
        for key, palette in _ARCHETYPE_PALETTES.items():
            if key in lower_prompt or any(sub in lower_prompt for sub in key.split("-")):
                return palette

        # Check for blue/dark/cyber/neon/green hints
        if any(w in lower_prompt for w in ("cyber", "neon", "matrix", "future")):
            return _ARCHETYPE_PALETTES["cyberpunk"]
        if any(w in lower_prompt for w in ("ocean", "sea", "blue", "deep", "aqua")):
            return _ARCHETYPE_PALETTES["ocean-blue"]
        if any(w in lower_prompt for w in ("forest", "emerald", "green", "nature")):
            return _ARCHETYPE_PALETTES["emerald-forest"]
        if any(w in lower_prompt for w in ("sunset", "gold", "warm", "amber", "orange")):
            return _ARCHETYPE_PALETTES["sunset-gold"]

        # Default fallback is clean monochrome
        return _ARCHETYPE_PALETTES["minimal-monochrome"]

    @classmethod
    def derive_foreground_color(cls, bg_hex_or_token: str) -> str:
        """Derive high-contrast foreground color (#ffffff or #0f172a)."""
        clean_token = cls.sanitize_color(bg_hex_or_token)
        if _HEX_COLOR_REGEX.match(clean_token):
            clean_hex = clean_token.lstrip("#")
            if len(clean_hex) == 3:
                clean_hex = "".join(c * 2 for c in clean_hex)
            r = int(clean_hex[0:2], 16)
            g = int(clean_hex[2:4], 16)
            b = int(clean_hex[4:6], 16)
            # Standard perceptual luminance formula
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            return "#0f172a" if luminance > 0.55 else "#ffffff"

        # Default dark foreground for general oklch/rgb
        return "#ffffff"

    @classmethod
    def build_css_variables(
        cls,
        palette: SynthesizedThemePalette,
        color_scheme: Literal["light", "dark"],
        art: ThemePosterArtConfig,
    ) -> dict[str, str]:
        """Compile a dictionary of sanitized CSS custom properties."""
        is_dark = color_scheme == "dark"
        primary = palette.primary_dark if is_dark else palette.primary_light
        primary_hover = (
            palette.primary_hover_dark if is_dark else palette.primary_hover_light
        )
        accent_warm = (
            palette.accent_warm_dark if is_dark else palette.accent_warm_light
        )
        primary_fg = cls.derive_foreground_color(primary)

        # Clamped wash between 0.2 and 0.8
        safe_wash = max(0.2, min(0.8, art.wash))

        css_vars: dict[str, str] = {
            "--primary": cls.sanitize_color(primary),
            "--primary-foreground": cls.sanitize_color(primary_fg),
            "--primary-hover": cls.sanitize_color(primary_hover),
            "--art-wash-opacity": f"{safe_wash:.2f}",
        }
        if accent_warm:
            css_vars["--accent-warm"] = cls.sanitize_color(accent_warm)

        return css_vars
