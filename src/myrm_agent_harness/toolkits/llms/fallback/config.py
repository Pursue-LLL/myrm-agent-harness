"""Probe and cooldown configuration for model fallback.

[INPUT]

[OUTPUT]
- ProbeConfig: Probe and cooldown configuration dataclass

[POS]
Configurable probe and cooldown policies for model fallback management.
Allows users to customize cooldown periods, probe intervals, and retry limits
based on their specific business requirements.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProbeConfig:
    """Configuration for probe and cooldown behavior.

    Attributes:
        cooldown_ms: Duration to wait after model failure before retrying (milliseconds)
        probe_interval_ms: Minimum interval between probe attempts (milliseconds)
        max_probe_attempts: Maximum number of probe attempts before giving up
        global_throttle_ms: Global throttle interval to prevent probe storms (milliseconds)

    Examples:
        # Aggressive recovery (for high-frequency APIs)
        config = ProbeConfig(
            cooldown_ms=15_000,  # 15s cooldown
            probe_interval_ms=10_000,  # 10s probe interval
        )

        # Conservative recovery (for rate-limited APIs)
        config = ProbeConfig(
            cooldown_ms=120_000,  # 2min cooldown
            probe_interval_ms=60_000,  # 1min probe interval
        )
    """

    cooldown_ms: int = 30_000  # 30 seconds
    probe_interval_ms: int = 30_000  # 30 seconds
    max_probe_attempts: int = 3
    global_throttle_ms: int = 30_000  # 30 seconds

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.cooldown_ms < 0:
            raise ValueError(f"cooldown_ms must be non-negative, got {self.cooldown_ms}")
        if self.probe_interval_ms < 0:
            raise ValueError(f"probe_interval_ms must be non-negative, got {self.probe_interval_ms}")
        if self.max_probe_attempts < 1:
            raise ValueError(f"max_probe_attempts must be at least 1, got {self.max_probe_attempts}")
        if self.global_throttle_ms < 0:
            raise ValueError(f"global_throttle_ms must be non-negative, got {self.global_throttle_ms}")


# Preset configurations for common scenarios
PRESET_CONFIGS = {
    "default": ProbeConfig(),
    "aggressive": ProbeConfig(
        cooldown_ms=15_000,
        probe_interval_ms=10_000,
        max_probe_attempts=5,
        global_throttle_ms=10_000,
    ),
    "conservative": ProbeConfig(
        cooldown_ms=120_000,
        probe_interval_ms=60_000,
        max_probe_attempts=2,
        global_throttle_ms=60_000,
    ),
    "balanced": ProbeConfig(
        cooldown_ms=30_000,
        probe_interval_ms=30_000,
        max_probe_attempts=3,
        global_throttle_ms=30_000,
    ),
}


def get_preset_config(preset_name: str) -> ProbeConfig:
    """Get a preset probe configuration.

    Args:
        preset_name: Name of the preset ("default", "aggressive", "conservative", "balanced")

    Returns:
        ProbeConfig instance

    Raises:
        ValueError: If preset_name is not recognized
    """
    if preset_name not in PRESET_CONFIGS:
        available = ", ".join(PRESET_CONFIGS.keys())
        raise ValueError(f"Unknown preset '{preset_name}'. Available: {available}")

    return PRESET_CONFIGS[preset_name]
