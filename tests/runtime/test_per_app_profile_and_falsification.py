"""Unit tests for Per-App Operating Profiles and Ephemeral Observation Self-Healing Suite."""

from __future__ import annotations

import tempfile

from myrm_agent_harness.runtime.app_profiles import (
    AppOperatingProfile,
    AppProfileRegistry,
    EphemeralInfoDetector,
    FalsificationEvidence,
    FalsificationStatus,
    ObservationRefinementEngine,
    ObservationTier,
)


def test_ephemeral_observation_isolation() -> None:
    """Verify that fragile details (coordinates, dynamic ports, window IDs) are isolated locally."""
    assert EphemeralInfoDetector.is_ephemeral("Click button at coordinate x=1024, y=768") is True
    assert EphemeralInfoDetector.is_ephemeral("Connect to debugging port=9222 for headless inspect") is True
    assert EphemeralInfoDetector.is_ephemeral("Target window handle 0x3af8 is minimized") is True
    assert EphemeralInfoDetector.is_ephemeral("Background rendering requires explicit scene export flag") is False

    with tempfile.TemporaryDirectory() as tmpdir:
        registry = AppProfileRegistry(tmpdir)
        engine = ObservationRefinementEngine(registry)

        obs = engine.register_observation(
            app_id="blender",
            feature_key="render_button_pos",
            statement="Render button located at absolute coordinate x=1420, y=980",
        )

        assert obs.is_ephemeral is True
        assert obs.tier == ObservationTier.EPHEMERAL_LOCAL

        # Ephemeral observation cannot be promoted to universal discipline
        res = engine.evaluate_universal_promotion("render_button_pos")
        assert res.is_promoted is False
        assert res.target_tier == ObservationTier.EPHEMERAL_LOCAL


def test_code_over_prompt_enforcement() -> None:
    """Verify that lessons that can be translated to tool code are lowered rather than kept in prompts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = AppProfileRegistry(tmpdir)
        engine = ObservationRefinementEngine(registry)

        obs = engine.register_observation(
            app_id="capcut",
            feature_key="auto_detect_export_dialog",
            statement="Auto retry sibling window when export dialog is obscured",
            can_convert_to_code=True,
            code_hook_target="mac_use_driver.try_sibling_window_fallback",
        )

        assert obs.can_convert_to_code is True
        assert obs.tier == ObservationTier.CONVERTED_TO_CODE

        res = engine.evaluate_universal_promotion("auto_detect_export_dialog")
        assert res.is_promoted is False
        assert res.target_tier == ObservationTier.CONVERTED_TO_CODE
        assert "Lower logic into tool driver hook" in res.recommended_code_patch


def test_universal_rule_promotion_multi_app() -> None:
    """Verify that an observation promotes to universal rule only after replication across >= 2 apps."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = AppProfileRegistry(tmpdir)
        engine = ObservationRefinementEngine(registry)

        # 1. Observed only in App 1 (Blender)
        engine.register_observation(
            app_id="blender",
            feature_key="multi_monitor_black_screen",
            statement="Secondary monitor capture yields black frame without explicit display ID flag",
        )

        res_single = engine.evaluate_universal_promotion("multi_monitor_black_screen")
        assert res_single.is_promoted is False
        assert res_single.qualified_apps_count == 1
        assert res_single.target_tier == ObservationTier.PER_APP_STABLE

        # 2. Replicated in App 2 (CapCut)
        engine.register_observation(
            app_id="capcut",
            feature_key="multi_monitor_black_screen",
            statement="Secondary monitor capture yields black frame without explicit display ID flag",
        )

        res_dual = engine.evaluate_universal_promotion("multi_monitor_black_screen")
        assert res_dual.is_promoted is True
        assert res_dual.qualified_apps_count == 2
        assert res_dual.target_tier == ObservationTier.PROMOTED_UNIVERSAL

        # Verify profile observation tier updated to PROMOTED_UNIVERSAL
        prof_blender = registry.get_profile("blender")
        assert prof_blender is not None
        obs_blender = prof_blender.get_observation("multi_monitor_black_screen")
        assert obs_blender is not None and obs_blender.tier == ObservationTier.PROMOTED_UNIVERSAL


def test_falsification_first_refinement_and_supersede() -> None:
    """Verify empirical evidence immediately falsifies stale assumptions and supersedes them atomically."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = AppProfileRegistry(tmpdir)
        engine = ObservationRefinementEngine(registry)

        # Baseline assumption: background capture not supported
        engine.register_observation(
            app_id="wechat",
            feature_key="bg_capture",
            statement="WeChat window does not support headless background capture without active focus",
        )

        prof = registry.get_profile("wechat")
        assert prof is not None
        assert prof.is_feature_falsified("bg_capture") is False

        # Empirical runtime observation: background capture actually succeeded in new version!
        evidence = FalsificationEvidence(
            app_id="wechat",
            feature_key="bg_capture",
            observed_behavior="Captured valid non-black frame while window was in background",
            contradiction_reason="WeChat v3.8+ supports CoreGraphics background window rendering",
        )

        ok, msg = engine.falsify_and_supersede(
            evidence,
            new_statement="WeChat v3.8+ reliably supports background capture using kCGWindowListOptionAll",
        )
        assert ok is True
        assert "successfully falsified" in msg

        # Verify old observation marked FALSIFIED
        prof_updated = registry.get_profile("wechat")
        assert prof_updated is not None
        assert prof_updated.is_feature_falsified("bg_capture") is True

        old_obs = prof_updated.get_observation("bg_capture")
        assert old_obs is not None and old_obs.status == FalsificationStatus.FALSIFIED

        # Verify new observation registered
        new_obs = prof_updated.get_observation("bg_capture_v2")
        assert new_obs is not None and new_obs.status == FalsificationStatus.ACTIVE


def test_markdown_card_rendering() -> None:
    """Verify GitHub Flavored Markdown card rendering for application operating profiles."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = AppProfileRegistry(tmpdir)
        engine = ObservationRefinementEngine(registry)

        profile = AppOperatingProfile(
            app_id="doubao_work",
            display_name="豆包工作桌面版",
            bundle_id="com.bytedance.doubao.desktop",
            deterministic_features={"framework": "Electron", "internal_cdp_port": "9222"},
        )
        registry.register_or_update(profile)

        engine.register_observation(
            app_id="doubao_work",
            feature_key="electron_cdp",
            statement="Internal Chromium debugging available via remote debugging port",
        )

        card = engine.render_profile_markdown(registry.get_profile("doubao_work"))  # type: ignore[arg-type]
        assert "### 🖥️ 应用专属动态操作档案: `豆包工作桌面版`" in card
        assert "- **`framework`**: Electron" in card
        assert "> [!NOTE]" in card
