"""Humanized interaction helpers — delay distribution, Bézier trajectory, wheel-burst scroll.

[INPUT]
- pool.config::HumanizeConfig, HumanizeMode (POS: interaction humanization config)

[OUTPUT]
- click_delay: compute humanized click delay (ms)
- type_delay: compute humanized typing delay (ms)
- bezier_move: move mouse along a cubic Bézier curve with wobble and overshoot
- wheel_burst: deliver a logical scroll as a burst of small wheel-input events (human inertia)
- scroll_notch_delta: one logical wheel notch size for a phase (accel/cruise/decel)
- scroll_burst_break_ms: burst-group pause between scroll notches (ms)
- scroll_phase_steps: per-scroll accel/decel step counts

[POS]
Pure helper module for humanized browser interaction. Provides delay calculation
(uniform for FAST, Gaussian for DEFAULT/CAREFUL), Bézier mouse trajectory generation
(cubic curve with ease-in-out, wobble, burst pauses, and overshoot), and wheel-burst
scroll humanization (small wheel events with inertia-like gaps and a burst-group
pause rhythm). All pauses use asyncio.sleep so the humanize stack emits no CDP wait
commands.
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.pool.config import HumanizeConfig, HumanizeMode

if TYPE_CHECKING:
    from patchright.async_api import Page


def _humanized_delay(
    cfg: HumanizeConfig, mean: float, sigma: float, lo: int, hi: int
) -> int:
    """Compute a humanized delay (ms). FAST uses uniform, DEFAULT/CAREFUL use Gaussian."""
    if cfg.mode == HumanizeMode.FAST:
        return random.randint(lo, hi)
    return max(lo, min(hi, round(random.gauss(mean, sigma))))


def click_delay(cfg: HumanizeConfig) -> int:
    """Compute humanized click delay (ms)."""
    return _humanized_delay(
        cfg,
        cfg.click_delay_mean,
        cfg.click_delay_sigma,
        cfg.click_delay_min,
        cfg.click_delay_max,
    )


def type_delay(cfg: HumanizeConfig) -> int:
    """Compute humanized typing delay per character (ms)."""
    return _humanized_delay(
        cfg,
        cfg.type_delay_mean,
        cfg.type_delay_sigma,
        cfg.type_delay_min,
        cfg.type_delay_max,
    )


def _ease_in_out(t: float) -> float:
    """Cubic ease-in-out for natural acceleration/deceleration."""
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - pow(-2.0 * t + 2.0, 3) / 2.0


async def bezier_move(
    page: Page,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    cfg: HumanizeConfig,
) -> None:
    """Move mouse from start to end along a cubic Bézier curve with wobble."""
    dist = math.hypot(end_x - start_x, end_y - start_y)
    if dist < 1:
        return

    steps = max(cfg.bezier_min_steps, min(cfg.bezier_max_steps, round(dist / 8.0)))

    dx, dy = end_x - start_x, end_y - start_y
    perp_x, perp_y = -dy / (dist or 1), dx / (dist or 1)
    bias1 = random.uniform(-0.3, 0.3) * dist
    bias2 = random.uniform(-0.3, 0.3) * dist
    cp1_x = start_x + dx * 0.25 + perp_x * bias1
    cp1_y = start_y + dy * 0.25 + perp_y * bias1
    cp2_x = start_x + dx * 0.75 + perp_x * bias2
    cp2_y = start_y + dy * 0.75 + perp_y * bias2

    burst_counter = 0
    burst_size = random.randint(3, 5)

    for i in range(steps + 1):
        t = _ease_in_out(i / steps)
        u = 1.0 - t
        px = u**3 * start_x + 3 * u**2 * t * cp1_x + 3 * u * t**2 * cp2_x + t**3 * end_x
        py = u**3 * start_y + 3 * u**2 * t * cp1_y + 3 * u * t**2 * cp2_y + t**3 * end_y

        wobble_amp = math.sin(math.pi * (i / steps)) * cfg.bezier_wobble_max
        wx = px + (random.random() - 0.5) * 2 * wobble_amp
        wy = py + (random.random() - 0.5) * 2 * wobble_amp

        await page.mouse.move(round(wx), round(wy))

        burst_counter += 1
        if burst_counter >= burst_size and i < steps:
            await asyncio.sleep(random.randint(8, 18) / 1000.0)
            burst_counter = 0
            burst_size = random.randint(3, 5)

    if random.random() < cfg.overshoot_chance:
        overshoot_dist = random.uniform(cfg.overshoot_px_min, cfg.overshoot_px_max)
        angle = math.atan2(end_y - start_y, end_x - start_x)
        await page.mouse.move(
            round(end_x + math.cos(angle) * overshoot_dist),
            round(end_y + math.sin(angle) * overshoot_dist),
        )
        await asyncio.sleep(random.randint(30, 70) / 1000.0)
        await page.mouse.move(
            round(end_x + (random.random() - 0.5) * 4),
            round(end_y + (random.random() - 0.5) * 4),
        )


async def wheel_burst(page: Page, delta: int, cfg: HumanizeConfig) -> None:
    """Deliver one logical scroll as a burst of small wheel-input events (human inertia).

    Splits ``delta`` into 20-40px wheel steps separated by 8-20ms gaps, mimicking a
    physical scroll wheel notch burst. Uses asyncio.sleep so no CDP wait command is
    emitted. FAST mode sends a single wheel event (handled by the caller).
    """
    if delta == 0:
        return
    direction = 1 if delta > 0 else -1
    remaining = abs(delta)
    while remaining > 0:
        step = random.randint(cfg.scroll_step_min, cfg.scroll_step_max)
        chunk = min(step, remaining)
        await page.mouse.wheel(0, chunk * direction)
        remaining -= chunk
        if remaining > 0:
            await asyncio.sleep(
                random.randint(cfg.scroll_gap_min, cfg.scroll_gap_max) / 1000.0
            )


def scroll_notch_delta(cfg: HumanizeConfig, phase: str, direction: int) -> int:
    """One logical wheel notch size for a phase (px), with variance.

    Phases: accel (deliberate start), cruise (scroll_delta_base), decel
    (settling before target). Returns a signed delta.
    """
    if phase == "accel":
        lo, hi = cfg.scroll_accel_delta
    elif phase == "decel":
        lo, hi = cfg.scroll_decel_delta
    else:
        lo, hi = cfg.scroll_delta_base
    delta = random.uniform(lo, hi)
    delta *= 1 + (random.random() - 0.5) * 2 * cfg.scroll_delta_variance
    return round(delta) * direction


def scroll_burst_break_ms(
    cfg: HumanizeConfig, in_burst: bool, phase_changed: bool
) -> int:
    """Pause before the next scroll notch (ms), or 0 to keep the burst running.

    Human wheel scroll is bursty: several notches fire in quick succession, then
    a pause. Returns 0 while a burst is still running (no phase transition), a
    short pause on burst boundaries, a longer pause on accel/cruise/decel
    transitions, and an occasional reading pause for realism. FAST returns 0.
    """
    if cfg.mode == HumanizeMode.FAST:
        return 0
    if in_burst and not phase_changed:
        return 0
    if phase_changed or random.random() < cfg.scroll_reading_pause_chance:
        return random.randint(*cfg.scroll_pause_slow)
    return random.randint(*cfg.scroll_pause_fast)


def scroll_phase_steps(cfg: HumanizeConfig) -> tuple[int, int]:
    """Per-scroll accel/decel step counts sampled from their config ranges."""
    accel = random.randint(cfg.scroll_accel_steps[0], cfg.scroll_accel_steps[1])
    decel = random.randint(cfg.scroll_decel_steps[0], cfg.scroll_decel_steps[1])
    return accel, decel
