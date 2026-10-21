"""Unit tests for Code-Over-Prompt and Roundtrip Compression Suite."""

from __future__ import annotations

from myrm_agent_harness.runtime.code_over_prompt import (
    AppDisplayNameResolver,
    CoordinateFormat,
    CoordinateNormalizer,
    DisplayBounds,
    RoundtripBudgetGate,
    ScreenshotFailureReason,
    ScreenshotFallbackDriver,
    WindowDescriptor,
)


def test_coordinate_normalization_three_formats() -> None:
    """Verify coordinate normalization across percentage, Retina scaled, and physical pixels."""
    display = DisplayBounds(width=1920, height=1080, scale_factor=2.0)
    normalizer = CoordinateNormalizer(display)

    # 1. Percentage floating coordinates (0.5, 0.25) -> (960, 270)
    p_pct = normalizer.normalize(0.5, 0.25)
    assert p_pct.format_detected == CoordinateFormat.PERCENTAGE
    assert p_pct.x == 960
    assert p_pct.y == 270

    # 2. Retina scaled points (960, 540) on 2x display -> (1919, 1079 clamped)
    p_retina = normalizer.normalize(960.0, 540.0)
    assert p_retina.format_detected == CoordinateFormat.RETINA_SCALED
    assert p_retina.x == 1919  # Clamped to width - 1
    assert p_retina.y == 1079  # Clamped to height - 1

    # 3. Explicit physical device pixels (500, 300)
    p_pixel = normalizer.normalize(500, 300, forced_format=CoordinateFormat.PIXEL)
    assert p_pixel.format_detected == CoordinateFormat.PIXEL
    assert p_pixel.x == 500
    assert p_pixel.y == 300

    # 4. Out-of-bounds negative coordinates clamped safely to zero
    p_clamped = normalizer.normalize(-50, -100, forced_format=CoordinateFormat.PIXEL)
    assert p_clamped.x == 0
    assert p_clamped.y == 0


def test_screenshot_fallback_self_healing() -> None:
    """Verify screenshot driver automatically falls back to sibling windows upon primary window failure."""
    main_win = WindowDescriptor(
        window_id=101,
        owner_pid=4200,
        title="Blender Main Viewport",
        width=1600,
        height=900,
    )
    sibling_win = WindowDescriptor(
        window_id=102,
        owner_pid=4200,
        title="Blender Shader Editor",
        width=1200,
        height=700,
    )
    unrelated_win = WindowDescriptor(
        window_id=201,
        owner_pid=9999,
        title="System Desktop",
        width=1920,
        height=1080,
    )

    windows = [main_win, sibling_win, unrelated_win]

    def mock_capture(win_id: int) -> tuple[bool, str, ScreenshotFailureReason | None]:
        if win_id == 101:
            # Primary window fails due to black screen
            return False, "", ScreenshotFailureReason.BLACK_SCREEN
        if win_id == 102:
            # Sibling window succeeds
            return True, "valid_shader_editor_screenshot_data", None
        return False, "", ScreenshotFailureReason.UNKNOWN

    driver = ScreenshotFallbackDriver(mock_capture)
    result = driver.capture_with_fallback(main_win, windows)

    # Invariant: Driver resolves fallback in code, requiring only 1 model roundtrip
    assert result.success is True
    assert result.attempted_sibling is True
    assert result.sibling_window_id == 102
    assert result.data_or_token == "valid_shader_editor_screenshot_data"
    assert result.roundtrip_cost == 1


def test_app_display_name_resolver() -> None:
    """Verify colloquial and Chinese display name resolution into bundle IDs."""
    resolver = AppDisplayNameResolver()

    # 1. Exact Chinese display name
    wechat = resolver.resolve("微信")
    assert wechat is not None
    assert wechat.bundle_id == "com.tencent.xinWeChat"
    assert wechat.executable_name == "WeChat"

    # 2. English alias lookup
    capcut = resolver.resolve("capcut")
    assert capcut is not None
    assert capcut.bundle_id == "com.lemon.lv"

    # 3. Feishu lookup
    feishu = resolver.resolve("飞书")
    assert feishu is not None
    assert feishu.bundle_id == "com.electron.lark"

    # 4. Unknown app returns None
    unknown = resolver.resolve("non_existent_fake_app_xyz")
    assert unknown is None


def test_roundtrip_budget_gate_and_markdown() -> None:
    """Verify roundtrip budget enforcement gate (budget <= 2) and markdown card formatting."""
    gate = RoundtripBudgetGate(task_name="导出剪映视频工程", max_budget=2)

    # Turn 1: Take screenshot
    gate.record_turn("screenshot_capture", count=1)
    v1 = gate.evaluate()
    assert v1.passed is True
    assert v1.current_roundtrips == 1
    assert v1.efficiency_ratio > 0.0

    # Turn 2: Click export button
    gate.record_turn("click_export", count=1)
    v2 = gate.evaluate()
    assert v2.passed is True
    assert v2.current_roundtrips == 2

    # Verify Markdown card for compliant execution
    md_pass = gate.render_markdown_card()
    assert "### 🎯 经验代码化往返压缩审计卡片: `导出剪映视频工程`" in md_pass
    assert "> [!NOTE]" in md_pass
    assert "**[指标达成]**" in md_pass

    # Turn 3: Exceeds budget -> warning alert triggered
    gate.record_turn("extra_retry", count=1)
    v3 = gate.evaluate()
    assert v3.passed is False
    assert v3.current_roundtrips == 3
    assert v3.exceeded_by == 1

    md_fail = gate.render_markdown_card()
    assert "> [!WARNING]" in md_fail
    assert "**[预算超标]**" in md_fail
