"""Unit tests for session/humanize.py — delay distribution and Bézier helpers."""

from __future__ import annotations

import statistics
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import HumanizeConfig, HumanizeMode
from myrm_agent_harness.toolkits.browser.session.humanize import (
    bezier_move,
    click_delay,
    scroll_burst_break_ms,
    scroll_notch_delta,
    scroll_phase_steps,
    type_delay,
    wheel_burst,
)


class TestClickDelay:
    """click_delay: FAST uses uniform, DEFAULT/CAREFUL use Gaussian."""

    def test_fast_mode_within_range(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.FAST)
        for _ in range(200):
            d = click_delay(cfg)
            assert cfg.click_delay_min <= d <= cfg.click_delay_max

    def test_default_mode_within_range(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
        for _ in range(200):
            d = click_delay(cfg)
            assert cfg.click_delay_min <= d <= cfg.click_delay_max

    def test_careful_mode_within_range(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        for _ in range(200):
            d = click_delay(cfg)
            assert cfg.click_delay_min <= d <= cfg.click_delay_max

    def test_gaussian_mean_approximation(self) -> None:
        """DEFAULT mode should produce delays whose mean is close to click_delay_mean."""
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
        samples = [click_delay(cfg) for _ in range(1000)]
        mean = statistics.mean(samples)
        assert (
            abs(mean - cfg.click_delay_mean) < 15
        ), f"Mean {mean} too far from {cfg.click_delay_mean}"


class TestTypeDelay:
    """type_delay: same distribution logic as click_delay."""

    def test_fast_mode_within_range(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.FAST)
        for _ in range(200):
            d = type_delay(cfg)
            assert cfg.type_delay_min <= d <= cfg.type_delay_max

    def test_careful_mode_within_range(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        for _ in range(200):
            d = type_delay(cfg)
            assert cfg.type_delay_min <= d <= cfg.type_delay_max

    def test_gaussian_mean_approximation(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        samples = [type_delay(cfg) for _ in range(1000)]
        mean = statistics.mean(samples)
        assert (
            abs(mean - cfg.type_delay_mean) < 15
        ), f"Mean {mean} too far from {cfg.type_delay_mean}"


class TestBezierMove:
    """bezier_move: edge cases and basic trajectory validation."""

    @pytest.mark.asyncio
    async def test_skip_when_distance_less_than_one(self) -> None:
        page = MagicMock()
        page.mouse = MagicMock()
        page.mouse.move = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        await bezier_move(page, 100.0, 100.0, 100.5, 100.5, cfg)

        page.mouse.move.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_mouse_move_for_long_distance(self) -> None:
        page = MagicMock()
        page.mouse = MagicMock()
        page.mouse.move = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        await bezier_move(page, 0.0, 0.0, 500.0, 500.0, cfg)

        assert page.mouse.move.call_count >= cfg.bezier_min_steps

    @pytest.mark.asyncio
    async def test_steps_clamped_by_config(self) -> None:
        page = MagicMock()
        page.mouse = MagicMock()
        page.mouse.move = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        await bezier_move(page, 0.0, 0.0, 10000.0, 0.0, cfg)

        move_count = page.mouse.move.call_count
        max_expected = cfg.bezier_max_steps + 5  # +5 for overshoot moves
        assert move_count <= max_expected, f"Too many moves: {move_count}"

    @pytest.mark.asyncio
    async def test_ends_near_target(self) -> None:
        page = MagicMock()
        page.mouse = MagicMock()
        page.mouse.move = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        cfg = HumanizeConfig(
            mode=HumanizeMode.CAREFUL,
            enable_bezier_mouse=True,
            overshoot_chance=0.0,
        )

        await bezier_move(page, 0.0, 0.0, 300.0, 400.0, cfg)

        last_call = page.mouse.move.call_args
        last_x, last_y = last_call[0]
        assert abs(last_x - 300) < 10, f"Last x={last_x}, expected ~300"
        assert abs(last_y - 400) < 10, f"Last y={last_y}, expected ~400"


class TestWheelBurst:
    """wheel_burst: splits a logical scroll into small wheel-input bursts."""

    def _make_page(self) -> MagicMock:
        page = MagicMock()
        page.mouse = MagicMock()
        page.mouse.wheel = AsyncMock()
        return page

    @pytest.mark.asyncio
    async def test_splits_delta_into_small_steps(self) -> None:
        page = self._make_page()
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)

        with patch("asyncio.sleep", new=AsyncMock()):
            await wheel_burst(page, 250, cfg)

        calls = [c.args[1] for c in page.mouse.wheel.call_args_list]
        assert calls, "expected at least one wheel event"
        assert sum(calls) == 250
        for chunk in calls[:-1]:
            assert cfg.scroll_step_min <= chunk <= cfg.scroll_step_max
        assert 1 <= calls[-1] <= cfg.scroll_step_max

    @pytest.mark.asyncio
    async def test_zero_delta_no_events(self) -> None:
        page = self._make_page()
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)

        with patch("asyncio.sleep", new=AsyncMock()):
            await wheel_burst(page, 0, cfg)

        page.mouse.wheel.assert_not_called()

    @pytest.mark.asyncio
    async def test_negative_delta_negative_steps(self) -> None:
        page = self._make_page()
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)

        with patch("asyncio.sleep", new=AsyncMock()):
            await wheel_burst(page, -250, cfg)

        calls = [c.args[1] for c in page.mouse.wheel.call_args_list]
        assert calls
        assert sum(calls) == -250
        for chunk in calls:
            assert chunk < 0


class TestScrollNotchDelta:
    """scroll_notch_delta: phase-based notch sizes with variance and sign."""

    def test_cruise_within_variance_bounds(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
        lo, hi = cfg.scroll_delta_base
        lo *= 1 - cfg.scroll_delta_variance
        hi *= 1 + cfg.scroll_delta_variance
        for _ in range(300):
            d = scroll_notch_delta(cfg, "cruise", 1)
            assert round(lo) <= d <= round(hi)

    def test_accel_within_config_bounds(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
        lo, hi = cfg.scroll_accel_delta
        lo *= 1 - cfg.scroll_delta_variance
        hi *= 1 + cfg.scroll_delta_variance
        for _ in range(200):
            d = scroll_notch_delta(cfg, "accel", 1)
            assert round(lo) <= d <= round(hi)

    def test_decel_within_config_bounds(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
        lo, hi = cfg.scroll_decel_delta
        lo *= 1 - cfg.scroll_delta_variance
        hi *= 1 + cfg.scroll_delta_variance
        for _ in range(200):
            d = scroll_notch_delta(cfg, "decel", 1)
            assert round(lo) <= d <= round(hi)

    def test_decel_positive_and_negative_sign(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
        for _ in range(200):
            assert scroll_notch_delta(cfg, "decel", 1) > 0
            assert scroll_notch_delta(cfg, "decel", -1) < 0


class TestScrollBurstBreakMs:
    """scroll_burst_break_ms: FAST instant; bursts skip pauses; boundaries pause."""

    def test_fast_mode_zero_pause(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.FAST)
        assert scroll_burst_break_ms(cfg, in_burst=True, phase_changed=False) == 0
        assert scroll_burst_break_ms(cfg, in_burst=False, phase_changed=True) == 0

    def test_inside_burst_no_pause(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
        assert scroll_burst_break_ms(cfg, in_burst=True, phase_changed=False) == 0

    def test_phase_transition_slow_pause(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        with patch("random.random", return_value=0.9):  # no reading pause
            for _ in range(100):
                pause = scroll_burst_break_ms(cfg, in_burst=True, phase_changed=True)
                assert cfg.scroll_pause_slow[0] <= pause <= cfg.scroll_pause_slow[1]

    def test_burst_boundary_short_pause(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        with patch("random.random", return_value=0.9):  # no reading pause
            for _ in range(100):
                pause = scroll_burst_break_ms(cfg, in_burst=False, phase_changed=False)
                assert cfg.scroll_pause_fast[0] <= pause <= cfg.scroll_pause_fast[1]

    def test_reading_pause_slow_range(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        with patch("random.random", return_value=0.0):  # reading pause triggers
            for _ in range(100):
                pause = scroll_burst_break_ms(cfg, in_burst=False, phase_changed=False)
                assert cfg.scroll_pause_slow[0] <= pause <= cfg.scroll_pause_slow[1]


class TestScrollPhaseSteps:
    """scroll_phase_steps: accel/decel counts sampled from config ranges."""

    def test_counts_within_ranges(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.DEFAULT)
        for _ in range(200):
            accel, decel = scroll_phase_steps(cfg)
            assert cfg.scroll_accel_steps[0] <= accel <= cfg.scroll_accel_steps[1]
            assert cfg.scroll_decel_steps[0] <= decel <= cfg.scroll_decel_steps[1]


class TestHumanizeConfigValidation:
    """HumanizeConfig __post_init__ boundary validation."""

    def test_click_delay_min_gt_max_raises(self) -> None:
        with pytest.raises(ValueError, match="click_delay_min"):
            HumanizeConfig(click_delay_min=200, click_delay_max=100)

    def test_type_delay_min_gt_max_raises(self) -> None:
        with pytest.raises(ValueError, match="type_delay_min"):
            HumanizeConfig(type_delay_min=200, type_delay_max=100)

    def test_negative_sigma_raises(self) -> None:
        with pytest.raises(ValueError, match="sigma"):
            HumanizeConfig(click_delay_sigma=-1.0)

    def test_bezier_min_gt_max_raises(self) -> None:
        with pytest.raises(ValueError, match="bezier_min_steps"):
            HumanizeConfig(bezier_min_steps=100, bezier_max_steps=10)

    def test_scroll_step_min_gt_max_raises(self) -> None:
        with pytest.raises(ValueError, match="scroll_step_min"):
            HumanizeConfig(scroll_step_min=100, scroll_step_max=10)

    def test_scroll_gap_min_gt_max_raises(self) -> None:
        with pytest.raises(ValueError, match="scroll_gap_min"):
            HumanizeConfig(scroll_gap_min=100, scroll_gap_max=10)

    def test_scroll_delta_variance_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="scroll_delta_variance"):
            HumanizeConfig(scroll_delta_variance=1.5)

    def test_scroll_overshoot_chance_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="scroll_overshoot_chance"):
            HumanizeConfig(scroll_overshoot_chance=-0.1)

    def test_scroll_reading_pause_chance_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="scroll_reading_pause_chance"):
            HumanizeConfig(scroll_reading_pause_chance=1.5)

    def test_scroll_target_zone_invalid_raises(self) -> None:
        for kwargs in (
            {"scroll_target_zone": (0.5, 1.5)},
            {"scroll_target_zone": (-0.1, 0.5)},
            {"scroll_target_zone": (0.7, 0.3)},
            {"scroll_target_zone": (0.4, 0.4)},
        ):
            with pytest.raises(ValueError, match="scroll_target_zone"):
                HumanizeConfig(**kwargs)

    def test_scroll_target_zone_default(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        lo, hi = cfg.scroll_target_zone
        assert 0.0 <= lo < hi <= 1.0

    def test_scroll_tuple_range_invalid_raises(self) -> None:
        for name in (
            "scroll_delta_base",
            "scroll_accel_delta",
            "scroll_decel_delta",
            "scroll_pause_fast",
            "scroll_pause_slow",
            "scroll_accel_steps",
            "scroll_decel_steps",
            "scroll_overshoot_px",
            "scroll_settle_delay",
            "scroll_pre_move_delay",
        ):
            with pytest.raises(ValueError, match=name):
                HumanizeConfig(**{name: (300, 100)})

    def test_valid_config_no_error(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        assert cfg.enable_bezier_mouse is True
        assert cfg.mode == HumanizeMode.CAREFUL
