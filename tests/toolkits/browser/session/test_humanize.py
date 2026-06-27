"""Unit tests for session/humanize.py — delay distribution and Bézier helpers."""

from __future__ import annotations

import statistics
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import HumanizeConfig, HumanizeMode
from myrm_agent_harness.toolkits.browser.session.humanize import (
    bezier_move,
    click_delay,
    type_delay,
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
        assert abs(mean - cfg.click_delay_mean) < 15, f"Mean {mean} too far from {cfg.click_delay_mean}"


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
        assert abs(mean - cfg.type_delay_mean) < 15, f"Mean {mean} too far from {cfg.type_delay_mean}"


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

    def test_valid_config_no_error(self) -> None:
        cfg = HumanizeConfig.from_mode(HumanizeMode.CAREFUL)
        assert cfg.enable_bezier_mouse is True
        assert cfg.mode == HumanizeMode.CAREFUL
