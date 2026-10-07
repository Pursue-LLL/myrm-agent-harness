"""Unit tests for Agent self-reflective client theme introspection, wallpaper synthesis, and hot-reload injection.

Validates the full loop benchmarked against Alibaba Qoder agentic client theme customization.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from myrm_agent_harness.runtime.context.client_theme_injection_engine import (
    AgentSelfReflectiveThemeEngine,
)
from myrm_agent_harness.runtime.context.client_theme_injection_types import (
    ThemeMutationStatus,
    ThemePosterArtConfig,
)
from myrm_agent_harness.runtime.context.theme_palette_synthesizer import (
    ThemePaletteSynthesizer,
)


def test_client_theme_surface_introspection() -> None:
    """Verifies that the Agent can introspect client UI boundaries and allowed CSS variables."""
    engine = AgentSelfReflectiveThemeEngine(platform="desktop_tauri")
    caps = engine.inspect_client_theme_surface()

    assert caps.platform == "desktop_tauri"
    assert "--primary" in caps.allowed_css_variables
    assert "--art-wash-opacity" in caps.allowed_css_variables
    assert "nav-rail-focus" in caps.supported_layouts
    assert "inter" in caps.supported_fonts
    assert caps.current_profile_id == "official-default"
    assert caps.current_color_scheme == "dark"
    assert caps.supports_wallpaper is True
    assert caps.supports_hot_reload is True


def test_multimodal_palette_synthesis_and_contrast_safety() -> None:
    """Verifies style keywords map to canonical palettes and enforce contrast safety."""
    cyber_palette = ThemePaletteSynthesizer.synthesize_from_keywords("Cyberpunk neon future")
    assert cyber_palette.dual_accent is True
    assert cyber_palette.primary_dark == "#38bdf8"
    assert cyber_palette.accent_warm_dark == "#fb7185"

    ocean_palette = ThemePaletteSynthesizer.synthesize_from_keywords("Deep ocean blue calm")
    assert ocean_palette.primary_light == "#2563eb"
    assert ocean_palette.accent_warm_light == "#0d9488"

    # Contrast foreground derivation
    fg_for_light = ThemePaletteSynthesizer.derive_foreground_color("#ffffff")
    assert fg_for_light == "#0f172a"

    fg_for_dark = ThemePaletteSynthesizer.derive_foreground_color("#000000")
    assert fg_for_dark == "#ffffff"

    # Insecure CSS injection attempt rejection
    with pytest.raises(ValueError, match="Insecure or invalid color value"):
        ThemePaletteSynthesizer.sanitize_color("red; background: url('evil.com')")


def test_poster_wash_calibration_and_wcag_bounds() -> None:
    """Verifies wash levels are strictly bounded in [0.2, 0.8] for text readability."""
    cyber_palette = ThemePaletteSynthesizer.synthesize_from_keywords("cyberpunk")

    # Lower bound test (0.05 -> clamped to 0.20)
    low_art = ThemePosterArtConfig(wash=0.05, media_kind="image")
    css_low = ThemePaletteSynthesizer.build_css_variables(
        palette=cyber_palette,
        color_scheme="dark",
        art=low_art,
    )
    assert css_low["--art-wash-opacity"] == "0.20"

    # Upper bound test (0.95 -> clamped to 0.80)
    high_art = ThemePosterArtConfig(wash=0.95, media_kind="image")
    css_high = ThemePaletteSynthesizer.build_css_variables(
        palette=cyber_palette,
        color_scheme="dark",
        art=high_art,
    )
    assert css_high["--art-wash-opacity"] == "0.80"


def test_theme_injection_and_frontend_preinit_contract() -> None:
    """Verifies full injection generates payloads 100% compliant with frontend preinit.ts."""
    engine = AgentSelfReflectiveThemeEngine(platform="web")

    recipe = engine.synthesize_theme_recipe(
        style_prompt="cyberpunk neon",
        name="Night City Cyber Glow",
        layout_id="full-bleed",
        poster_asset_ref="file:///assets/wallpapers/night_city.png",
        wash=0.50,
    )

    assert recipe.name == "Night City Cyber Glow"
    assert recipe.layout_id == "full-bleed"
    assert recipe.art.media_kind == "image"
    assert recipe.art.poster_asset_ref == "file:///assets/wallpapers/night_city.png"

    # Apply injection
    record = engine.apply_theme_injection(recipe=recipe, color_scheme="dark")
    assert record.status == ThemeMutationStatus.SUCCESS
    assert record.rollback_token is not None
    assert record.css_variables["--primary"] == "#38bdf8"
    assert record.css_variables["--art-wash-opacity"] == "0.50"

    # Check preinit snapshot
    snap = engine.get_active_theme_snapshot()
    assert snap.profile_id == recipe.id
    assert snap.layout_id == "full-bleed"
    assert snap.scene_id == "immersive"
    assert snap.art_on is True
    assert snap.is_dark is True
    assert snap.primary == "#38bdf8"
    assert snap.art_poster_url == "file:///assets/wallpapers/night_city.png"
    assert snap.art_wash == 0.50

    # Ensure recorded in history
    history = engine.get_injection_history()
    assert len(history) == 1
    assert history[0].injection_id == record.injection_id


def test_atomic_rollback_and_concurrent_safety() -> None:
    """Verifies atomic rollback restores prior snapshot and thread-safety under concurrency."""
    engine = AgentSelfReflectiveThemeEngine(platform="web")
    initial_snapshot = engine.get_active_theme_snapshot()
    assert initial_snapshot.profile_id == "official-default"

    # 1. Apply customized theme
    recipe = engine.synthesize_theme_recipe(style_prompt="sunset-gold")
    record = engine.apply_theme_injection(recipe=recipe, color_scheme="dark")
    assert engine.get_active_theme_snapshot().profile_id == recipe.id
    rollback_token = record.rollback_token
    assert rollback_token is not None

    # 2. Rollback to initial
    rb_record = engine.rollback_theme_injection(rollback_token)
    assert rb_record is not None
    assert rb_record.status == ThemeMutationStatus.ROLLED_BACK
    assert engine.get_active_theme_snapshot().profile_id == "official-default"

    # 3. Second rollback on same token fails gracefully
    assert engine.rollback_theme_injection(rollback_token) is None

    # 4. Concurrency test across 10 threads
    def _worker(thread_idx: int) -> str:
        t_recipe = engine.synthesize_theme_recipe(
            style_prompt=f"theme-{thread_idx}",
            name=f"Concurrent Theme {thread_idx}",
        )
        t_record = engine.apply_theme_injection(t_recipe, color_scheme="dark")
        return t_record.injection_id

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_worker, range(10)))

    assert len(results) == 10
    # Initial 1 + rollback 1 + 10 concurrent = 12 total entries in audit log
    assert len(engine.get_injection_history()) == 12
